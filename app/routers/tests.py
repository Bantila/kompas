"""Эндпоинты тестирования: выдача вопросов, проверка ответа, приём результатов."""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.db import transaction
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from app.models import Recommendation, TestProgress, TestResult, User
from app.routers.auth import jwt_auth, optional_user
from app.schemas.test import (
    CheckAnswerRequest,
    CheckAnswerResponse,
    PlannedSubject,
    PlanRequest,
    PlanResponse,
    ProgressResponse,
    ProgressSaveRequest,
    QuestionsResponse,
    TestSubmitRequest,
    TestSubmitResponse,
)
from app.services import consent as consent_service
from app.services.ai_recommender import FALLBACK_MODEL_NAME, recommend_professions
from app.services.integrity import check as check_answers
from app.services.rate_limit import limit
from app.services.test_planner import (
    asked_difficulties,
    difficulties_for_attempt,
    plan_subjects,
    questions_for_plan,
)
from app.services.test_scoring import (
    ScoringError,
    calculate_scores,
    completion_progress,
    get_question,
    load_questions,
    public_questions,
)

logger = logging.getLogger(__name__)

router = Router(tags=["tests"])

# Класс из тридцати человек сдаёт тест за урок и укладывается; скрипт,
# генерирующий прохождения тысячами, упирается в потолок.
_лимит_сдачи = limit("submit", times=40, seconds=3600)


@router.get("/questions", response=QuestionsResponse)
async def get_questions(
    request: HttpRequest,
    block: str | None = Query(None, description="a | b | c"),
    subject_group: str | None = Query(None, description="exact | natural | humanities | creative"),
) -> QuestionsResponse:
    """Вопросы для показа ученику.

    correct_index сюда не попадает никогда — иначе правильный ответ виден в
    теле ответа API ещё до того, как ученик выберет вариант.
    Параметры block и subject_group позволяют дробить тест из 74 вопросов
    на короткие сессии («сегодня — точные науки»).
    """
    try:
        return QuestionsResponse(**public_questions(block=block, subject_group=subject_group))
    except ScoringError as exc:
        raise HttpError(400, str(exc)) from exc


def _progress_out(progress: TestProgress) -> ProgressResponse:
    return ProgressResponse(
        answers=progress.answers or {},
        plan=progress.plan or None,
        updated_at=progress.updated_at,
        answered=len(progress.answers or {}),
    )


@router.get("/progress", response=ProgressResponse, auth=jwt_auth)
async def get_progress(request: HttpRequest) -> ProgressResponse:
    """Незавершённый тест ученика.

    Черновик привязан к аккаунту, а не к браузеру: очистил данные, открыл
    приложение на другом телефоне или зашёл из бота — ответы на месте.
    """
    progress = await TestProgress.objects.filter(user_id=request.auth.id).afirst()
    if progress is None:
        return ProgressResponse()
    return _progress_out(progress)


@router.put("/progress", response=ProgressResponse, auth=jwt_auth)
async def save_progress(request: HttpRequest, payload: ProgressSaveRequest) -> ProgressResponse:
    """Сохранить черновик. Ответы приходят целиком и заменяют прежние.

    Слияние здесь было бы вредным: удалить ответ (вернуться назад и
    переотвечать) стало бы невозможно, а два устройства всё равно
    разъезжаются — выигрывает то, где отвечали последним.
    """
    progress, _ = await TestProgress.objects.aget_or_create(user_id=request.auth.id)
    progress.answers = payload.answers
    if payload.plan is not None:
        progress.plan = payload.plan
    await progress.asave()
    return _progress_out(progress)


@router.delete("/progress", response={204: None}, auth=jwt_auth)
async def reset_progress(request: HttpRequest):
    """Начать тест заново."""
    await TestProgress.objects.filter(user_id=request.auth.id).adelete()
    return 204, None


@router.post("/plan", response=PlanResponse)
async def plan_test(request: HttpRequest, payload: PlanRequest) -> PlanResponse:
    """Подобрать предметы для блока B по ответам блока A.

    Спрашивать все 13 предметов — 52 вопроса, до конца доходят не все. Модель
    смотрит профиль интересов и называет пять предметов, которые стоит
    проверить задачами: блок B сокращается до 15 вопросов, весь тест — до 37.

    Вошедшему ученику задачи подбираются по номеру попытки: во второй раз тест
    состоит из других задач, иначе замер повторяет первый по памяти. Без входа
    (демо-страница) попытка считается первой.

    Правильные ответы, как и в /questions, сюда не попадают.
    """
    try:
        scores = calculate_scores(payload.answers)
    except ScoringError as exc:
        raise HttpError(422, str(exc)) from exc

    user = await optional_user(request)
    attempt = await TestResult.objects.filter(user_id=user.id).acount() if user else 0

    plan = await plan_subjects(scores.get("interests") or {})
    titles = load_questions()["subject_titles"]
    сложности = difficulties_for_attempt(attempt)

    logger.info(
        "План теста: %s (%s), попытка %s, сложности %s",
        ", ".join(plan["subjects"]), plan["source"], attempt + 1, "+".join(сложности),
    )

    return PlanResponse(
        subjects=[PlannedSubject(subject=c, title=titles.get(c, c)) for c in plan["subjects"]],
        questions=questions_for_plan(plan["subjects"], attempt=attempt),
        source=plan["source"],
        planned_by_model=plan["planned_by_model"],
        optional_subjects=[
            PlannedSubject(subject=code, title=title)
            for code, title in titles.items()
            if code not in plan["subjects"]
        ],
        attempt=attempt,
        difficulties=list(сложности),
    )


@router.post("/check-answer", response=CheckAnswerResponse)
async def check_answer(request: HttpRequest, payload: CheckAnswerRequest) -> CheckAnswerResponse:
    """Проверка одного знаниевого вопроса — сравнение происходит на бэкенде."""
    question = get_question(payload.question_id)
    if question is None or question.get("type") != "knowledge":
        raise HttpError(404, f"Знаниевый вопрос {payload.question_id!r} не найден")
    correct_index = question["correct_index"]
    return CheckAnswerResponse(
        question_id=payload.question_id,
        is_correct=payload.selected_index == correct_index,
        correct_index=correct_index,
    )


@sync_to_async
@transaction.atomic
def _save_result(user: User, payload: TestSubmitRequest, scores: dict, ai_result: dict) -> TestResult:
    """Профиль, результат, рекомендация и удаление черновика — одной транзакцией."""
    # данные профиля могли уточниться между прохождениями
    if payload.full_name:
        user.full_name = payload.full_name
    if payload.school_class:
        user.school_class = payload.school_class
    user.save(update_fields=["full_name", "school_class"])

    test_result = TestResult.objects.create(
        user=user,
        raw_answers=payload.answers,
        computed_scores=scores,
        integrity=check_answers(payload.answers),
    )
    Recommendation.objects.create(
        test_result=test_result,
        ai_response=ai_result.get("raw_response") or {},
        professions=ai_result["professions"],
        model_used=ai_result["model_used"],
    )
    # черновик больше не нужен: тест сдан, иначе приложение предложит
    # «продолжить» уже завершённое прохождение
    TestProgress.objects.filter(user=user).delete()
    return test_result


@router.post("/submit", response={201: TestSubmitResponse})
async def submit_test(request: HttpRequest, payload: TestSubmitRequest):
    """Приём ответов: считает баллы, зовёт ИИ и сохраняет всё одной транзакцией."""
    _лимит_сдачи(request)
    try:
        scores = calculate_scores(payload.answers)
    except ScoringError as exc:
        raise HttpError(422, str(exc)) from exc

    # Без записанного согласия прохождение не сохраняем: это данные ребёнка.
    # Согласие привязано к аккаунту, поэтому без аккаунта его нет тоже.
    user = await User.objects.filter(max_user_id=payload.max_user_id).afirst()
    if user is None or await consent_service.active_for(user.id) is None:
        raise HttpError(403, "Нужно согласие на обработку данных — без него результат не сохраняется")

    # Модель спрашиваем до транзакции: ответ идёт секундами, и держать всё это
    # время открытую транзакцию незачем. recommend_professions не падает никогда.
    ai_result = await recommend_professions(scores)
    test_result = await _save_result(user, payload, scores, ai_result)

    logger.info(
        "Тест %s сохранён для пользователя %s (fallback=%s)",
        test_result.id,
        payload.max_user_id,
        ai_result["model_used"] == FALLBACK_MODEL_NAME,
    )

    return 201, TestSubmitResponse(
        test_result_id=test_result.id,
        completed_at=test_result.completed_at,
        progress=completion_progress(payload.answers),
        computed_scores=scores,
        recommendations=ai_result["professions"],
        fallback=ai_result["model_used"] == FALLBACK_MODEL_NAME,
        model_used=ai_result["model_used"],
        difficulties=asked_difficulties(payload.answers),
    )
