"""Демо-данные: класс 7Б, педагог и восемь учеников с разными профилями.

Нужен, чтобы кабинет педагога было что показывать сразу после запуска —
сводка по классу не формируется, пока тест не прошли хотя бы три ученика.

    docker compose exec backend python -m app.seed

Скрипт идемпотентный: повторный запуск ничего не дублирует.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta

import app.django_setup  # noqa: F401
from app.models import Recommendation, SchoolClass, TaskAttempt, TestResult, User, UserRole
from app.services.ai_recommender import recommend_professions
from app.services.error_classifier import classify
from app.services.gamification import register_answer
from app.services.integrity import check as check_answers
from app.services.security import hash_password
from app.services.task_bank import build_pack
from app.services.test_scoring import calculate_scores, load_questions

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed")

SCHOOL_CLASS = "7Б"
TEACHER_ID = "teacher_demo"
DEMO_JOIN_CODE = "DEMO7B"
# демо-логин педагога — чтобы кабинет можно было открыть сразу после запуска
TEACHER_EMAIL = "teacher@demo.ru"
TEACHER_PASSWORD = "demo1234"

# Архетипы: выраженные типы Голланда, сильные предметы и черты.
# Из них собирается правдоподобный класс, а не белый шум.
ARCHETYPES = [
    {
        "name": "Технарь",
        "interests": ["investigative", "realistic"],
        "subjects": ["mathematics", "physics", "informatics"],
        "skills": ["analytical", "resilience"],
    },
    {
        "name": "Гуманитарий",
        "interests": ["social", "artistic"],
        "subjects": ["literature", "russian", "history", "foreign_language"],
        "skills": ["teamwork", "creativity"],
    },
    {
        "name": "Естественник",
        "interests": ["investigative", "social"],
        "subjects": ["biology", "chemistry", "geography"],
        "skills": ["analytical", "teamwork"],
    },
    {
        "name": "Организатор",
        "interests": ["enterprising", "conventional"],
        "subjects": ["social_studies", "mathematics"],
        "skills": ["leadership", "teamwork"],
    },
]

STUDENTS = [
    ("Артём К.", 0), ("Мария Л.", 1), ("Никита С.", 0), ("Полина В.", 2),
    ("Данил Р.", 3), ("София М.", 1), ("Егор Т.", 2), ("Алиса Ж.", 3),
]


def build_answers(archetype: dict, rng: random.Random) -> dict:
    """Ответы одного ученика: по архетипу с разбросом, чтобы класс не был клоном."""
    questions = load_questions()
    answers: dict = {}

    for question in questions["block_a_interests"]:
        strong = question["type"] in archetype["interests"]
        answers[question["id"]] = rng.randint(4, 5) if strong else rng.randint(1, 3)

    for question in questions["block_b_subjects"]:
        strong = question["subject"] in archetype["subjects"]
        if question["type"] == "interest":
            answers[question["id"]] = rng.randint(4, 5) if strong else rng.randint(1, 3)
            continue
        # сильный предмет — чаще правильный ответ, слабый — чаще мимо
        correct = question["correct_index"]
        hit = rng.random() < (0.85 if strong else 0.35)
        wrong = [i for i in range(len(question["options"])) if i != correct]
        answers[question["id"]] = {
            "selected_index": correct if hit else rng.choice(wrong),
            "time_spent_seconds": round(rng.uniform(4, 45), 1),
        }

    for question in questions["block_c_softskills"]:
        strong = question["skill"] in archetype["skills"]
        answers[question["id"]] = rng.randint(4, 5) if strong else rng.randint(2, 4)

    return answers


async def _practice(user: User, archetype: dict, после: datetime, rng: random.Random) -> None:
    """Тренажёр после теста: задачи по сильным предметам, где-то с ошибками.

    Идёт через register_answer, как живой ответ, — опыт, серии и достижения
    получаются настоящими, а не нарисованными.
    """
    задачи = build_pack(subjects=archetype["subjects"], size=rng.randint(6, 14))
    for номер, задача in enumerate(задачи):
        верно = rng.random() < 0.72
        ответ = задача["answer"] if верно else "0"
        вердикт = classify(ответ, задача["answer"], задача["subject"])
        когда = min(после + timedelta(hours=10 * (номер + 1)), datetime.now(UTC))
        await TaskAttempt.objects.acreate(
            user=user,
            task_id=задача["id"],
            subject=задача["subject"],
            difficulty=задача["difficulty"],
            user_answer=ответ,
            is_correct=вердикт["is_correct"],
            error_type=вердикт["error_type"],
            confidence=вердикт["confidence"],
            answered_at=когда,
        )
        await register_answer(user.id, вердикт["is_correct"], когда.astimezone())


async def seed() -> None:
    rng = random.Random(42)  # фиксированный seed — демо воспроизводимо

    teacher, _ = await User.objects.aget_or_create(
        max_user_id=TEACHER_ID,
        defaults={"role": UserRole.teacher, "full_name": "Ирина Петровна"},
    )
    # логин проставляем и старому демо-педагогу, созданному до появления auth
    teacher.email = TEACHER_EMAIL
    teacher.hashed_password = hash_password(TEACHER_PASSWORD)
    await teacher.asave(update_fields=["email", "hashed_password"])
    logger.info("Педагог %s: %s / %s", TEACHER_ID, TEACHER_EMAIL, TEACHER_PASSWORD)

    school_class, создан = await SchoolClass.objects.aget_or_create(
        join_code=DEMO_JOIN_CODE, defaults={"name": SCHOOL_CLASS, "teacher": teacher}
    )
    if создан:
        logger.info("Класс %s создан, код присоединения: %s", SCHOOL_CLASS, DEMO_JOIN_CODE)

    created = 0
    for index, (full_name, archetype_index) in enumerate(STUDENTS):
        max_user_id = f"student_demo_{index}"
        existing = await User.objects.filter(max_user_id=max_user_id).afirst()
        if existing is not None:
            # догоняем старые демо-данные, созданные до появления SchoolClass
            if existing.class_ref_id is None:
                existing.class_ref = school_class
                await existing.asave(update_fields=["class_ref"])
            continue

        archetype = ARCHETYPES[archetype_index]
        user = await User.objects.acreate(
            max_user_id=max_user_id,
            role=UserRole.student,
            full_name=full_name,
            school_class=SCHOOL_CLASS,
            class_ref=school_class,
        )

        answers = build_answers(archetype, rng)
        scores = calculate_scores(answers)
        test_result = await TestResult.objects.acreate(
            user=user,
            raw_answers=answers,
            computed_scores=scores,
            integrity=check_answers(answers),
        )
        # прохождения разнесены по двум неделям — иначе графики в админке
        # и кабинете показывают один столбик за сегодня
        пройден = datetime.now(UTC) - timedelta(days=rng.randint(1, 13), hours=rng.randint(0, 6))
        await TestResult.objects.filter(pk=test_result.pk).aupdate(completed_at=пройден)

        ai_result = await recommend_professions(scores)
        await Recommendation.objects.acreate(
            test_result=test_result,
            ai_response=ai_result.get("raw_response") or {},
            professions=ai_result["professions"],
            model_used=ai_result["model_used"],
        )
        await _practice(user, archetype, пройден, rng)
        created += 1
        logger.info(
            "  %s (%s) → %s",
            full_name,
            archetype["name"],
            ai_result["professions"][0]["name"],
        )

    if created:
        logger.info("Готово: добавлено учеников — %s, класс %s", created, SCHOOL_CLASS)
        logger.info(
            "Сводка педагога: /static/teacher.html, ID — %s, код класса — %s",
            TEACHER_ID,
            DEMO_JOIN_CODE,
        )
    else:
        logger.info("Демо-данные уже на месте, ничего не добавлено")


if __name__ == "__main__":
    asyncio.run(seed())
