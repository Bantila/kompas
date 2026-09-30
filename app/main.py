"""ASGI-точка входа «Компаса» (Django + Django Ninja): uvicorn app.main:app."""

from __future__ import annotations

import logging
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

app = get_asgi_application()

from app.config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)

_settings = get_settings()
# Печатаем модель того провайдера, который выбран: иначе по логу не понять,
# применились ли настройки.
_провайдер = _settings.ai_provider.strip().lower()
_модель = (
    _settings.gigachat_model if _провайдер == "gigachat" else "запасной алгоритм без модели"
)
logger.info("«Компас» запускается, подбор профессий: %s (%s)", _провайдер, _модель)
if not os.getenv("JWT_SECRET"):
    logger.warning(
        "JWT_SECRET не задан — подставлен случайный на время работы процесса. "
        "Подделать токен нельзя, но при каждом рестарте все входы слетают. "
        "Задайте постоянный JWT_SECRET в .env."
    )
