"""Разбор настроек, которые сами не тривиальны — CORS-список origin."""

from __future__ import annotations

import pytest

from app.config import get_settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch):
    return get_settings()


def test_cors_wildcard_by_default(settings) -> None:
    assert settings.cors_allowed_origins == "*"
    assert settings.cors_origins == ["*"]


def test_cors_single_origin(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "cors_allowed_origins", "https://web.max.ru")

    assert settings.cors_origins == ["https://web.max.ru"]


def test_cors_multiple_origins_split_and_trimmed(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "cors_allowed_origins", "https://web.max.ru, https://max.ru ,  "
    )

    assert settings.cors_origins == ["https://web.max.ru", "https://max.ru"]


def test_cors_wildcard_is_not_split_as_a_pattern(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """"*" — особый случай Starlette (разрешает любой origin), а не текст,
    который можно смешать с обычными доменами через запятую."""
    monkeypatch.setattr(settings, "cors_allowed_origins", " * ")

    assert settings.cors_origins == ["*"]


def test_layero_database_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Layero кладёт адрес базы в LAYERO_DATABASE_URL — он главнее DATABASE_URL."""
    from app.config import Settings

    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")
    monkeypatch.setenv("LAYERO_DATABASE_URL", "postgresql://r:p@db.layero.ru:5432/k?sslmode=verify-full")

    assert Settings().database_url.startswith("postgresql://r:p@db.layero.ru")


def test_verify_full_gets_root_certificate() -> None:
    """Без корневого сертификата verify-full падает на подключении."""
    from app.settings import _database

    база = _database("postgresql://r:p%40ss@db.layero.ru:5432/kompas?sslmode=verify-full")

    assert база["PASSWORD"] == "p@ss"
    assert база["OPTIONS"]["sslmode"] == "verify-full"
    assert база["OPTIONS"]["sslrootcert"].endswith(".pem")
