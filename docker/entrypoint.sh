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

exec "$@"
