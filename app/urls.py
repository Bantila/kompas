"""Маршруты: мини-приложение, API, админка, статика и health-check."""

from __future__ import annotations

import logging
from pathlib import Path

from asgiref.sync import sync_to_async
from django.contrib import admin
from django.contrib.staticfiles.views import serve as serve_package_static
from django.db import connection
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from app.api import api

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

admin.site.site_header = "Компас — админка"
admin.site.site_title = "Компас"
admin.site.index_title = "Данные сервиса"


def _buffered(response):
    """FileResponse под ASGI отдаётся синхронным итератором, и Django на каждый
    файл пишет в лог предупреждение. Файлы фронта мелкие — читаем целиком."""
    if not isinstance(response, FileResponse):
        return response  # 304 и 404 приходят обычным ответом
    buffered = HttpResponse(b"".join(response.streaming_content), status=response.status_code)
    for header in ("Content-Type", "Last-Modified"):
        if header in response:
            buffered[header] = response[header]
    return buffered


def index(request: HttpRequest) -> HttpResponse:
    """Мини-приложение для ученика. Кабинет педагога — /static/teacher.html."""
    return HttpResponse((STATIC_DIR / "index.html").read_bytes(), content_type="text/html")


def static_no_cache(request: HttpRequest, path: str) -> HttpResponse:
    """Статика мини-приложения меняется часто — браузер не должен кэшировать её
    надолго, иначе версии HTML/JS/CSS расходятся (стучится в старый app.js
    вместе с новым index.html) и фронтенд ломается без явной ошибки."""
    response = _buffered(serve(request, path, document_root=STATIC_DIR))
    response["Cache-Control"] = "no-cache"
    return response


def admin_static(request: HttpRequest, path: str) -> HttpResponse:
    # CSS и JS самой админки берутся прямо из пакета Django — без collectstatic
    # и без отдельного веб-сервера под статику
    return _buffered(serve_package_static(request, path, insecure=True))


def _ping_db() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


async def health(request: HttpRequest) -> JsonResponse:
    """Проверка живости вместе с доступностью БД — для docker healthcheck."""
    try:
        await sync_to_async(_ping_db)()
    except Exception as exc:  # noqa: BLE001 — health-check не должен падать стеком
        logger.error("Health-check: БД недоступна: %s", exc)
        return JsonResponse({"status": "degraded", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


urlpatterns = [
    path("", index),
    path("health", health),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    # Swagger раньше жил на /docs — старые ссылки из README и презентации ведут туда
    path("docs", RedirectView.as_view(url="/api/docs")),
    re_path(r"^static/(?P<path>.*)$", static_no_cache),
    re_path(r"^django-static/(?P<path>.*)$", admin_static),
]
