"""Тренажёр задач: пак по слабым предметам, проверка ответа с разбором, статистика.

Замыкает петлю продукта: тест «Компаса» говорит, какие предметы подтянуть под
подходящие профессии — тренажёр сразу даёт задачи именно по ним.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime

from django.db.models import Count, Q
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from app.models import Recommendation, TaskAttempt, User
from app.routers.auth import jwt_auth
from app.schemas.practice import (
    AnswerRequest,
    AnswerResponse,
    PackResponse,
    PracticeStatsResponse,
    ProgressResponse,
    SubjectStat,
    TaskOut,
)
from app.services.ai_recommender import explain_mistake
from app.services.error_classifier import classify
from app.services.gamification import progress_summary, register_answer
from app.services.task_bank import build_pack, get_task, load_tasks, public_task
from app.services.test_scoring import load_questions

logger = logging.getLogger(__name__)

router = Router(tags=["practice"])

MAX_PACK_SIZE = 20


def _title_to_code() -> dict[str, str]:
    """«Математика» → mathematics: рекомендации хранят названия, банк — коды."""
    return {title.casefold(): code for code, title in load_questions()["subject_titles"].items()}


async def _weak_subjects(user: User) -> list[str]:
    """Предметы для подтягивания из последней рекомендации ученика."""
    recommendation = await (
        Recommendation.objects.filter(test_result__user_id=user.id).order_by("-created_at").afirst()
    )
    if recommendation is None:
        return []

    mapping = _title_to_code()
    subjects: list[str] = []
    for profession in recommendation.professions or []:
        for title in profession.get("subjects_to_improve") or []:
            code = mapping.get(str(title).casefold())
            if code and code not in subjects:
                subjects.append(code)
    return subjects


@router.get("/pack", response=PackResponse, auth=jwt_auth)
async def get_pack(
    request: HttpRequest,
    size: int = Query(5, ge=1, le=MAX_PACK_SIZE),
    subject: str | None = Query(None, description="Один предмет вместо автоподбора"),
    difficulty: str | None = Query(None, pattern="^(easy|medium|hard)$"),
) -> PackResponse:
    """Пак задач: по слабым предметам ученика, либо по указанному предмету."""
    user = request.auth
    if subject:
        subjects, reason = [subject], "Ты выбрал этот предмет сам"
    else:
        subjects = await _weak_subjects(user)
        reason = (
            "Эти предметы нужны профессиям, которые тебе подошли по тесту"
            if subjects
            else "Пройди тест — тогда пак соберётся под твои профессии. Пока задачи из всех предметов"
        )

    # уже решённые верно не повторяем: незачем гонять по кругу то, что усвоено
    solved = {
        task_id
        async for task_id in TaskAttempt.objects.filter(user=user, is_correct=True).values_list(
            "task_id", flat=True
        )
    }

    tasks = build_pack(subjects=subjects, size=size, difficulty=difficulty, exclude_ids=solved)
    if not tasks:  # всё решено — даём повтор, чтобы тренажёр не упирался в пустоту
        tasks = build_pack(subjects=subjects, size=size, difficulty=difficulty)

    return PackResponse(
        tasks=[TaskOut(**public_task(task)) for task in tasks],
        subjects=sorted({task["subject"] for task in tasks}),
        reason=reason,
    )


@router.post("/answer", response=AnswerResponse, auth=jwt_auth)
async def submit_answer(request: HttpRequest, payload: AnswerRequest) -> AnswerResponse:
    """Проверить ответ, разобрать ошибку и сохранить попытку."""
    user = request.auth
    task = get_task(payload.task_id)
    if task is None:
        raise HttpError(404, f"Задача {payload.task_id!r} не найдена")

    verdict = classify(payload.answer, task["answer"], task["subject"])

    # достижения считаются по истории попыток, поэтому текущая должна быть уже в ней
    await TaskAttempt.objects.acreate(
        user=user,
        task_id=task["id"],
        subject=task["subject"],
        difficulty=task["difficulty"],
        user_answer=payload.answer[:500],
        is_correct=verdict["is_correct"],
        error_type=verdict["error_type"],
        confidence=verdict["confidence"],
    )
    reward = await register_answer(user.id, verdict["is_correct"], datetime.now(UTC).astimezone())

    # ИИ объясняет только ошибки: на верном ответе объяснять нечего
    ai_explanation = None
    if not verdict["is_correct"]:
        ai_explanation = await explain_mistake(
            question=task["question"],
            correct_answer=task["answer"],
            user_answer=payload.answer,
            error_label=verdict["error_label"],
            explanation=task["explanation"],
        )

    return AnswerResponse(
        is_correct=verdict["is_correct"],
        correct_answer=task["answer"],
        explanation=task["explanation"],
        error_type=verdict["error_type"],
        error_label=verdict["error_label"],
        recommendation=verdict["recommendation"],
        confidence=verdict["confidence"],
        ai_explanation=ai_explanation,
        **reward,
    )


@router.get("/progress", response=ProgressResponse, auth=jwt_auth)
async def progress(request: HttpRequest) -> ProgressResponse:
    """Уровень, опыт, серия дней и достижения — для экрана профиля."""
    return ProgressResponse(**await progress_summary(request.auth.id))


@router.get("/stats", response=PracticeStatsResponse, auth=jwt_auth)
async def practice_stats(request: HttpRequest) -> PracticeStatsResponse:
    """Сводка тренировок: точность по предметам и типы ошибок."""
    user = request.auth
    by_subject = [
        SubjectStat(
            subject=row["subject"],
            total=row["total"],
            correct=row["correct"],
            accuracy=round(row["correct"] / row["total"], 3) if row["total"] else 0.0,
        )
        async for row in TaskAttempt.objects.filter(user=user)
        .values("subject")
        .annotate(total=Count("id"), correct=Count("id", filter=Q(is_correct=True)))
    ]
    total_answered = sum(stat.total for stat in by_subject)
    total_correct = sum(stat.correct for stat in by_subject)

    error_types = [
        error_type
        async for error_type in TaskAttempt.objects.filter(user=user, is_correct=False).values_list(
            "error_type", flat=True
        )
    ]

    return PracticeStatsResponse(
        total_answered=total_answered,
        total_correct=total_correct,
        accuracy=round(total_correct / total_answered, 3) if total_answered else 0.0,
        by_subject=sorted(by_subject, key=lambda s: s.accuracy),
        error_breakdown=dict(Counter(error_types).most_common()),
    )


@router.get("/subjects")
async def subjects(request: HttpRequest) -> dict:
    """Предметы банка задач с названиями и количеством — для выбора в интерфейсе."""
    titles = load_questions()["subject_titles"]
    counter = Counter(task["subject"] for task in load_tasks()["tasks"])
    return {
        "subjects": [
            {"code": code, "title": titles.get(code, code), "tasks": count}
            for code, count in sorted(counter.items(), key=lambda kv: -kv[1])
        ]
    }
