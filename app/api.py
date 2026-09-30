"""Django Ninja: одно API на все роутеры, общие обработчики ошибок."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError

from app.config import get_settings
from app.routers import auth, bot, classes, consent, practice, recommendations, teacher, tests
from app.services.rate_limit import RateLimited

api = NinjaAPI(
    title="Компас — ИИ-навигатор по профессиям",
    description=(
        "Backend прототипа для MAX/Сферум: адаптивный тест, подбор 5 профессий "
        "через GigaChat и агрегированная сводка для педагога. Django Ninja."
    ),
    version="0.2.0",
)


@api.exception_handler(AuthenticationError)
def _no_token(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
    # по умолчанию Ninja отвечает «Unauthorized» — фронт показывает detail как есть
    return api.create_response(request, {"detail": "Нужен вход в аккаунт"}, status=401)


@api.exception_handler(RateLimited)
def _rate_limited(request: HttpRequest, exc: RateLimited) -> HttpResponse:
    response = api.create_response(
        request, {"detail": "Слишком много запросов, попробуйте позже"}, status=429
    )
    response["Retry-After"] = str(exc.retry_after)
    return response


api.add_router("/auth", auth.router)
api.add_router("/consent", consent.router)
api.add_router("/tests", tests.router)
api.add_router("/practice", practice.router)
api.add_router("", recommendations.router)
api.add_router("/teacher", teacher.router)
api.add_router("", classes.router)
api.add_router("/bot", bot.router)


@api.get("/public-config", tags=["service"])
def public_config(request: HttpRequest) -> dict[str, str]:
    """Настройки, нужные приложению до входа. Секретов здесь нет."""
    return {"max_bot_username": get_settings().max_bot_username}
