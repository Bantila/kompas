"""Настройки Django. Всё прикладное по-прежнему читается из app.config (.env)."""

from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import get_settings

cfg = get_settings()

BASE_DIR = Path(__file__).resolve().parent.parent

# Секрет сессий админки — тот же, что подписывает JWT: один секрет на стенд,
# и он уже обязателен (без него при рестарте слетают все входы).
SECRET_KEY = cfg.jwt_secret
DEBUG = cfg.debug
# Снаружи стоит Caddy, backend в сеть не публикуется — Host проверяет прокси.
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = [cfg.app_public_url] if cfg.app_public_url else []
# HTTPS заканчивается на Caddy, он же выставляет X-Forwarded-Proto. Без этого
# форма входа в админку падает на CSRF: Origin https, а запрос виден как http.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    # тема админки — до django.contrib.admin, иначе её шаблоны не перекроют стандартные
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "app",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "app.urls"
# /api/consent и /health без слеша — так их зовут фронт и docker healthcheck
APPEND_SLASH = False

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # свои шаблоны раньше шаблонов Unfold: главная страница админки — наша
        "DIRS": [BASE_DIR / "app" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


def _database(url: str) -> dict:
    """DATABASE_URL в формате SQLAlchemy (postgresql+asyncpg://…, sqlite+aiosqlite:///…).

    Формат оставлен прежним, чтобы .env и docker-compose не менялись при
    переезде: драйвер после «+» отбрасываем, Django выбирает свой.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.split("+", 1)[0]
    if scheme == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": unquote(parsed.path.lstrip("/")) or ":memory:"}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }


DATABASES = {"default": _database(cfg.database_url)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "ru"
# у темы Unfold нет русского перевода — свой лежит в app/locale
LOCALE_PATHS = [BASE_DIR / "app" / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# /static/ занят фронтендом мини-приложения, поэтому файлы админки живут отдельно
STATIC_URL = "/django-static/"

# Мини-приложение MAX открывается в вебвью со своего origin. По умолчанию
# открыт всем ("*") — сузить через CORS_ALLOWED_ORIGINS в .env.
if cfg.cors_origins == ["*"]:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = cfg.cors_origins
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)-8s %(name)s | %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": cfg.log_level},
}

# Админка: тема Unfold в цветах мини-приложения — красная стрелка компаса
# (#D4442A, --north в styles.css) и бумажно-зелёные нейтральные тона.
from app.admin_ui import UNFOLD  # noqa: E402,F401
