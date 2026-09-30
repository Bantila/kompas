"""Сценарии чат-бота, не знающие, в каком мессенджере они работают.

Ядро принимает разобранное событие (кто написал и что) и возвращает ответ —
текст плюс кнопки. Отправку и разбор входящего делают адаптеры: telegram.py
сейчас, max.py — когда появится доступ к платформе. Благодаря этому переход
на MAX не затрагивает ни один сценарий.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models import BotAccount, Recommendation, SchoolClass, TaskAttempt
from app.services.ai_recommender import explain_mistake
from app.services.error_classifier import classify
from app.services.gamification import progress_summary, register_answer
from app.services.task_bank import build_pack, get_task
from app.services.test_scoring import load_questions

LINK_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "01OIL")
LINK_CODE_LENGTH = 6


@dataclass
class BotEvent:
    """Входящее событие, приведённое к общему виду."""

    platform: str
    external_id: str
    chat_id: str
    text: str = ""
    # нажатие кнопки: у Telegram callback_data, у MAX payload кнопки
    payload: str | None = None
    first_name: str = ""
    # MAX ждёт подтверждение нажатия кнопки — POST /answers с этим id,
    # иначе у пользователя крутится индикатор загрузки до таймаута.
    # У Telegram такого шага нет, поле остаётся пустым.
    callback_id: str | None = None


@dataclass
class BotReply:
    """Ответ бота: текст и подписи кнопок (по строкам)."""

    text: str
    buttons: list[list[str]] = field(default_factory=list)
    # ссылка на мини-приложение, если её нужно показать кнопкой
    app_url: str | None = None


BTN_TASK = "Дай задачу"
BTN_PROGRESS = "Мой прогресс"
BTN_CAREERS = "Мои профессии"
BTN_HELP = "Что ты умеешь"

MAIN_KEYBOARD = [[BTN_TASK, BTN_PROGRESS], [BTN_CAREERS, BTN_HELP]]

HELP_TEXT = (
    "Вот что я умею:\n\n"
    f"• «{BTN_TASK}» — пришлю задачу по предметам, которые тебе стоит подтянуть. "
    "Ответ пиши прямо в чат, я проверю и разберу ошибку.\n"
    f"• «{BTN_PROGRESS}» — уровень, опыт и серия дней.\n"
    f"• «{BTN_CAREERS}» — профессии, которые подошли тебе по тесту.\n\n"
    "Сам тест из 74 вопросов проходится в приложении — там же тренажёр и разбор."
)


async def _account(event: BotEvent) -> BotAccount:
    """Найти или завести собеседника бота.

    select_related: в async-коде обращение к account.user «по требованию»
    падает — пользователь должен прийти вместе с самой записью.
    """
    account = await (
        BotAccount.objects.select_related("user")
        .filter(platform=event.platform, external_id=event.external_id)
        .afirst()
    )
    if account is None:
        account = await BotAccount.objects.acreate(
            platform=event.platform, external_id=event.external_id, chat_id=event.chat_id
        )
    elif account.chat_id != event.chat_id:
        account.chat_id = event.chat_id
        await account.asave(update_fields=["chat_id"])
    return account


async def _ensure_link_code(account: BotAccount) -> str:
    if account.link_code:
        return account.link_code
    for _ in range(20):
        code = "".join(secrets.choice(LINK_CODE_ALPHABET) for _ in range(LINK_CODE_LENGTH))
        if not await BotAccount.objects.filter(link_code=code).aexists():
            account.link_code = code
            await account.asave(update_fields=["link_code"])
            return code
    raise RuntimeError("Не удалось выдать код привязки")


def _need_link(code: str, app_url: str | None) -> BotReply:
    return BotReply(
        text=(
            "Привет! Это «Компас» — помогу понять, какие профессии тебе подходят, "
            "и подтянуть предметы, которых для них не хватает.\n\n"
            "Нажми кнопку ниже, чтобы открыть приложение — аккаунт создастся сам, "
            "регистрироваться не нужно.\n\n"
            f"Если открываешь на компьютере, введи в приложении код: <b>{code}</b>"
        ),
        app_url=app_url,
    )


def _looks_like_class_code(text: str) -> bool:
    """Код класса — шесть символов из того же алфавита, без пробелов."""
    candidate = text.strip().upper()
    return len(candidate) == LINK_CODE_LENGTH and all(c in LINK_CODE_ALPHABET for c in candidate)


async def _join_class_by_code(account: BotAccount, code: str) -> BotReply:
    school_class = await SchoolClass.objects.filter(join_code=code.strip().upper()).afirst()
    if school_class is None:
        return BotReply(
            text="Такого кода класса нет — проверь у учителя.", buttons=MAIN_KEYBOARD
        )

    account.user.class_ref_id = school_class.id
    account.user.school_class = school_class.name
    await account.user.asave(update_fields=["class_ref", "school_class"])
    return BotReply(
        text=f"Готово, ты в классе {school_class.name}. Учитель увидит тебя в сводке.",
        buttons=MAIN_KEYBOARD,
    )


async def _greeting(account: BotAccount, name: str) -> BotReply:
    who = f", {name}" if name else ""
    progress = await progress_summary(account.user_id)
    return BotReply(
        text=(
            f"Привет{who}! Это «Компас» — помогаю понять, какие профессии тебе подходят, "
            "и подтянуть предметы, которых для них не хватает.\n\n"
            f"Сейчас у тебя {progress['level']} уровень и {progress['xp']} опыта."
        ),
        buttons=MAIN_KEYBOARD,
    )


async def _progress_reply(account: BotAccount) -> BotReply:
    p = await progress_summary(account.user_id)
    lines = [
        f"Уровень {p['level']} · {p['xp']} XP",
        f"До следующего уровня: {p['xp_to_next']}",
    ]
    if p["streak_days"]:
        lines.append(f"Серия: {p['streak_days']} дн. (рекорд {p['best_streak']})")
    if p["total_tasks"]:
        lines.append(
            f"Решено задач: {p['total_tasks']}, верно {p['correct_tasks']} "
            f"({round(p['accuracy'] * 100)}%)"
        )
    else:
        lines.append("Задач пока не решал — попроси у меня первую.")
    lines.append(f"Достижения: {p['earned_count']} из {p['total_achievements']}")
    return BotReply(text="\n".join(lines), buttons=MAIN_KEYBOARD)


async def _careers_reply(account: BotAccount) -> BotReply:
    recommendation = await _last_recommendation(account.user_id)
    if recommendation is None or not recommendation.professions:
        return BotReply(
            text="Ты ещё не проходил тест — пройди его в приложении, и я покажу подходящие профессии.",
            buttons=MAIN_KEYBOARD,
        )

    lines = ["Профессии, которые тебе подошли:\n"]
    for index, profession in enumerate(recommendation.professions[:5], start=1):
        lines.append(f"{index}. <b>{profession.get('name', '—')}</b>")
        subjects = profession.get("subjects_to_improve") or []
        if subjects:
            lines.append(f"   подтянуть: {', '.join(subjects)}")
    return BotReply(text="\n".join(lines), buttons=MAIN_KEYBOARD)


async def _next_task(account: BotAccount) -> BotReply:
    """Выдать задачу — по слабым предметам ученика, без уже решённых верно."""
    solved = {
        task_id
        async for task_id in TaskAttempt.objects.filter(
            user_id=account.user_id, is_correct=True
        ).values_list("task_id", flat=True)
    }
    subjects = await _weak_subjects(account.user_id)
    tasks = build_pack(subjects=subjects, size=1, exclude_ids=solved)
    if not tasks:
        tasks = build_pack(subjects=subjects, size=1)

    task = tasks[0]
    account.current_task_id = task["id"]
    await account.asave(update_fields=["current_task_id"])

    titles = load_questions()["subject_titles"]
    hint = f"\n\nПодсказка: {task['hint']}" if task.get("hint") else ""
    return BotReply(
        text=(
            f"<b>{titles.get(task['subject'], task['subject'])}</b> · {task['topic']}\n\n"
            f"{task['question']}{hint}\n\n"
            "Напиши ответ сообщением."
        )
    )


async def _last_recommendation(user_id) -> Recommendation | None:
    return await (
        Recommendation.objects.filter(test_result__user_id=user_id)
        .order_by("-created_at")
        .afirst()
    )


async def _weak_subjects(user_id) -> list[str]:
    recommendation = await _last_recommendation(user_id)
    if recommendation is None:
        return []
    mapping = {t.casefold(): c for c, t in load_questions()["subject_titles"].items()}
    subjects: list[str] = []
    for profession in recommendation.professions or []:
        for title in profession.get("subjects_to_improve") or []:
            code = mapping.get(str(title).casefold())
            if code and code not in subjects:
                subjects.append(code)
    return subjects


async def _check_answer(account: BotAccount, answer: str) -> BotReply:
    task = get_task(account.current_task_id)
    account.current_task_id = None
    await account.asave(update_fields=["current_task_id"])
    if task is None:
        return BotReply(text="Задача потерялась — попроси новую.", buttons=MAIN_KEYBOARD)

    verdict = classify(answer, task["answer"], task["subject"])
    await TaskAttempt.objects.acreate(
        user_id=account.user_id,
        task_id=task["id"],
        subject=task["subject"],
        difficulty=task["difficulty"],
        user_answer=answer[:500],
        is_correct=verdict["is_correct"],
        error_type=verdict["error_type"],
        confidence=verdict["confidence"],
    )
    reward = await register_answer(
        account.user_id, verdict["is_correct"], datetime.now(UTC).astimezone()
    )

    if verdict["is_correct"]:
        lines = [f"Верно! +{reward['xp_earned']} XP"]
    else:
        lines = [
            f"<b>{verdict['error_label']}</b>",
            f"Твой ответ: {answer} · правильный: {task['answer']}",
            verdict["recommendation"],
        ]
        explanation = await explain_mistake(
            question=task["question"],
            correct_answer=task["answer"],
            user_answer=answer,
            error_label=verdict["error_label"],
            explanation=task["explanation"],
        )
        if explanation:
            lines.append(f"\n{explanation}")
        lines.append(f"\n+{reward['xp_earned']} XP")

    if reward["level_up"]:
        lines.append(f"Новый уровень: {reward['level']}!")
    for achievement in reward["new_achievements"]:
        lines.append(f"Достижение: {achievement['icon']} {achievement['title']}")

    return BotReply(text="\n".join(lines), buttons=MAIN_KEYBOARD)


async def handle(event: BotEvent, app_url: str | None = None) -> BotReply:
    """Главная точка входа: событие → ответ. Адаптеры зовут только её."""
    account = await _account(event)
    command = (event.payload or event.text or "").strip()

    if account.user_id is None:
        # Обычный путь: ученик открывает мини-приложение кнопкой, оно входит по
        # подписи мессенджера и само привязывает этот чат. Код нужен только там,
        # где мини-приложение недоступно — например, в браузере на компьютере.
        code = await _ensure_link_code(account)
        return _need_link(code, app_url)

    # уже привязан, но класс не указан — спросим код класса прямо в чате
    if account.user.class_ref_id is None and _looks_like_class_code(command):
        return await _join_class_by_code(account, command)

    lowered = command.casefold()
    if lowered in ("/start", "start", "начать"):
        return await _greeting(account, event.first_name)
    if lowered in ("/help", BTN_HELP.casefold()):
        return BotReply(text=HELP_TEXT, buttons=MAIN_KEYBOARD)
    if lowered in ("/task", BTN_TASK.casefold()):
        return await _next_task(account)
    if lowered in ("/progress", BTN_PROGRESS.casefold()):
        return await _progress_reply(account)
    if lowered in ("/careers", BTN_CAREERS.casefold()):
        return await _careers_reply(account)

    if account.current_task_id:
        return await _check_answer(account, command)

    return BotReply(
        text="Не понял. Выбери, что сделать:",
        buttons=MAIN_KEYBOARD,
    )
