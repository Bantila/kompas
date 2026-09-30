#!/bin/sh
# Миграции накатываются при старте контейнера: на демо один шаг «docker compose up»
# надёжнее, чем инструкция «не забудьте выполнить migrate».
set -e

echo "Ждём PostgreSQL…"
python - <<'PY'
import sys, time
import app.django_setup  # noqa: F401
from django.db import connection

for attempt in range(30):
    try:
        connection.ensure_connection()
        break
    except Exception as exc:
        print(f"  попытка {attempt + 1}/30: {exc.__class__.__name__}")
        time.sleep(2)
else:
    sys.exit("PostgreSQL не поднялся за 60 секунд")
PY

echo "Накатываем миграции…"
python manage.py migrate --noinput

# Хостинги без консоли (Layero): администратор и демо-класс заводятся при
# старте по переменным окружения. Обе команды безопасно повторять.
if [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py createsuperuser --noinput >/dev/null 2>&1 \
        && echo "Администратор $DJANGO_SUPERUSER_USERNAME создан" \
        || echo "Администратор уже есть"
fi
if [ "$SEED_DEMO" = "1" ]; then
    # демо-рекомендации — запасным алгоритмом: восемь запросов к модели на
    # старте не уложились бы в проверку запуска контейнера
    AI_PROVIDER=none python -m app.seed
fi

exec "$@"
