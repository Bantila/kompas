"""Поднять Django для консольных скриптов: import app.django_setup  # noqa: F401"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()
