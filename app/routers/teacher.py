"""Сводка по классу для педагога — только агрегаты, без персональных данных."""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict

from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from app.models import SchoolClass, TestResult, UserRole
from app.routers.auth import jwt_auth
from app.schemas.user import ClassSummaryResponse
from app.services.test_scoring import load_questions

logger = logging.getLogger(__name__)

router = Router(tags=["teacher"], auth=jwt_auth)

MIN_STUDENTS_FOR_SUMMARY = 3


@router.get("/class-summary", response=ClassSummaryResponse)
async def class_summary(
    request: HttpRequest,
    class_id: uuid.UUID = Query(..., description="id класса из /api/teacher/classes"),
) -> ClassSummaryResponse:
    """Агрегированная картина по классу: куда тянет ребят и где проседают знания.

    Имена, id учеников и индивидуальные рекомендации сюда не попадают.
    Класс определяется по class_id, а не по свободному вводу названия —
    это исключает просмотр чужого класса по угаданному номеру.
    """
    teacher = request.auth
    if teacher.role != UserRole.teacher:
        raise HttpError(403, "Сводка доступна только пользователю с ролью teacher")

    school_class = await SchoolClass.objects.filter(id=class_id, teacher=teacher).afirst()
    if school_class is None:
        raise HttpError(404, "Класс не найден среди ваших классов")

    results = [
        result
        async for result in TestResult.objects.filter(
            user__class_ref_id=class_id, user__role=UserRole.student
        ).select_related("recommendation")
    ]

    students = {result.user_id for result in results}
    if len(students) < MIN_STUDENTS_FOR_SUMMARY:
        # k-анонимность: на двух учениках «агрегат» — это персональные данные
        raise HttpError(
            409,
            f"В классе {school_class.name} тест прошли {len(students)} чел. — "
            f"сводка формируется от {MIN_STUDENTS_FOR_SUMMARY}",
        )

    categories: Counter[str] = Counter()
    professions: Counter[str] = Counter()
    interests: defaultdict[str, list[float]] = defaultdict(list)
    softskills: defaultdict[str, list[float]] = defaultdict(list)
    knowledge: defaultdict[str, list[float]] = defaultdict(list)

    for result in results:
        scores = result.computed_scores or {}
        for key, values in (scores.get("interests") or {}).items():
            interests[key].append(float(values))
        for key, values in (scores.get("softskills") or {}).items():
            softskills[key].append(float(values))
        for subject, data in (scores.get("subjects") or {}).items():
            if isinstance(data, dict) and data.get("knowledge_score") is not None:
                knowledge[subject].append(float(data["knowledge_score"]))

        recommendation = getattr(result, "recommendation", None)
        if recommendation:
            for profession in recommendation.professions or []:
                categories[profession.get("category", "не указана")] += 1
                professions[profession.get("name", "—")] += 1

    titles = load_questions()["subject_titles"]
    weakest = sorted(
        (
            {
                "subject": subject,
                "title": titles.get(subject, subject),
                "average_knowledge": round(sum(v) / len(v), 2),
            }
            for subject, v in knowledge.items()
        ),
        key=lambda item: item["average_knowledge"],
    )[:5]

    return ClassSummaryResponse(
        school_class=school_class.name,
        students_tested=len(students),
        tests_completed=len(results),
        category_distribution=dict(categories.most_common()),
        top_professions=[{"name": name, "count": count} for name, count in professions.most_common(5)],
        average_interests={k: round(sum(v) / len(v), 2) for k, v in interests.items()},
        average_softskills={k: round(sum(v) / len(v), 2) for k, v in softskills.items()},
        weakest_subjects=weakest,
    )
