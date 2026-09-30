"""Общие фикстуры.

БД для тестов — SQLite, файл во временной директории. Она нужна только
здесь: боевой стек работает на PostgreSQL. Так тесты не требуют поднятого
postgres-контейнера и проходят быстро в CI. Схема создаётся миграциями
Django один раз на сессию, между тестами таблицы очищаются.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_DB_FILE = Path(tempfile.gettempdir()) / "kompas_pytest.db"
_DB_FILE.unlink(missing_ok=True)

# Переменные окружения выставляются ДО импорта app: настройки Django и
# Settings читаются на импорте и кэшируются.
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.as_posix()}"
os.environ["AI_PROVIDER"] = "openrouter"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["OPENROUTER_MODEL"] = "moonshotai/kimi-k2"
os.environ["MAX_WEBHOOK_SECRET"] = "test-secret"

from asgiref.sync import sync_to_async  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402 — заодно поднимает Django
from django.core.management import call_command  # noqa: E402

call_command("migrate", verbosity=0)


@pytest.fixture(autouse=True)
def _чистый_счётчик_лимитов():
    """Счётчик частоты живёт в памяти процесса — между тестами его надо обнулять.

    Иначе тест, отправивший десяток запросов, оставляет соседям исчерпанный
    лимит, и падает не он, а следующий за ним.
    """
    from app.services import rate_limit

    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture
async def client() -> AsyncClient:
    await sync_to_async(call_command)("flush", interactive=False, verbosity=0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def согласившийся(client):
    """Фабрика: ученик с записанным согласием на обработку данных.

    Без согласия /submit отвечает 403 — это данные ребёнка. В жизни ученик
    входит через мессенджер и принимает документ до теста; тесты сдают его
    напрямую, поэтому пользователя и согласие заводим заранее.
    """
    from app.models import User, UserRole
    from app.services import consent

    async def создать(max_user_id: str, **поля):
        user = await User.objects.acreate(max_user_id=max_user_id, role=UserRole.student, **поля)
        await consent.grant(user.id)
        return user.id

    return создать


@pytest.fixture
async def invite_code(client) -> str:
    """Загрузочный код приглашения — такой же выдаёт `python -m app.invite`.

    Зависит от client: тот пересоздаёт таблицы, и код, выписанный раньше,
    исчез бы вместе с ними.
    """
    from app.services import invites

    return (await invites.create()).code


@pytest.fixture
def full_answers() -> dict:
    """Ответы на весь тест: сильный «исследователь» с хорошей математикой."""
    from app.services.test_scoring import load_questions

    data = load_questions()
    answers: dict = {}
    for question in data["block_a_interests"]:
        answers[question["id"]] = 5 if question["type"] == "investigative" else 2
    for question in data["block_b_subjects"]:
        if question["type"] == "knowledge":
            # на математике отвечаем верно, на остальном — первым вариантом
            answers[question["id"]] = (
                question["correct_index"] if question["subject"] == "mathematics" else 0
            )
        else:
            answers[question["id"]] = 4
    for question in data["block_c_softskills"]:
        answers[question["id"]] = 4
    return answers
