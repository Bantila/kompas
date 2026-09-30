"""Выдача сохранённых рекомендаций и истории прохождений."""

from __future__ import annotations

import logging
import uuid

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from app.models import Recommendation, TestResult, User
from app.routers.auth import jwt_auth
from app.schemas.recommendation import RecommendationOut
from app.schemas.user import HistoryItem, UserHistoryResponse, UserOut
from app.services.ai_recommender import FALLBACK_MODEL_NAME
from app.services.test_planner import asked_difficulties

logger = logging.getLogger(__name__)

router = Router(tags=["recommendations"], auth=jwt_auth)


def _top_interests(scores: dict, limit: int = 3) -> list[str]:
    interests = (scores or {}).get("interests") or {}
    return sorted(interests, key=lambda k: interests[k], reverse=True)[:limit]


@router.get("/recommendations/{test_result_id}", response=RecommendationOut)
async def get_recommendation(request: HttpRequest, test_result_id: uuid.UUID) -> RecommendationOut:
    """Подбор профессий по результату теста — только своему.

    Индивидуальные рекомендации не видит и педагог: ему полагается
    обезличенная сводка по классу, а не разбор конкретного ребёнка.
    """
    recommendation = await (
        Recommendation.objects.select_related("test_result")
        .filter(test_result_id=test_result_id)
        .afirst()
    )
    # Тот же 404, что и при отсутствии записи: разные ответы позволили бы
    # перебором выяснять, какие результаты существуют.
    if recommendation is None or recommendation.test_result.user_id != request.auth.id:
        raise HttpError(404, f"Рекомендации для результата {test_result_id} не найдены")
    return RecommendationOut(
        id=recommendation.id,
        test_result_id=recommendation.test_result_id,
        professions=recommendation.professions,
        model_used=recommendation.model_used,
        fallback=recommendation.model_used == FALLBACK_MODEL_NAME,
        created_at=recommendation.created_at,
        computed_scores=recommendation.test_result.computed_scores,
    )


@router.get("/users/{max_user_id}/history", response=UserHistoryResponse)
async def get_user_history(request: HttpRequest, max_user_id: str) -> UserHistoryResponse:
    """История прохождений — по ней видно, как меняются интересы со временем.

    Только своя. max_user_id — это id пользователя в мессенджере, его несложно
    подобрать перебором, и без проверки история любого ребёнка читалась бы по
    одному угаданному числу.
    """
    user = await User.objects.filter(max_user_id=max_user_id).afirst()
    if user is None or user.id != request.auth.id:
        # одинаковый ответ на «нет такого» и «не ваш»: иначе перебором
        # выясняется, кто вообще пользуется сервисом
        raise HttpError(404, f"Пользователь {max_user_id!r} не найден")

    history = []
    async for result in (
        TestResult.objects.filter(user=user)
        .select_related("recommendation")
        .order_by("-completed_at")
    ):
        recommendation = getattr(result, "recommendation", None)
        history.append(
            HistoryItem(
                test_result_id=result.id,
                completed_at=result.completed_at,
                top_interests=_top_interests(result.computed_scores),
                professions=recommendation.professions if recommendation else [],
                difficulties=asked_difficulties(result.raw_answers),
                fallback=bool(recommendation and recommendation.model_used == FALLBACK_MODEL_NAME),
            )
        )

    return UserHistoryResponse(
        user=UserOut(
            id=user.id,
            max_user_id=user.max_user_id,
            role=user.role,
            full_name=user.full_name,
            school_class=user.school_class,
            created_at=user.created_at,
        ),
        attempts=len(history),
        history=history,
    )
