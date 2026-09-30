"""Оформление админки (тема Unfold): меню, цвета и главная страница с метриками.

Импортируется из settings, поэтому модели здесь грузятся только внутри
функций — на момент чтения настроек приложения Django ещё не готовы.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta

from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils import timezone


def _link(model: str):
    return reverse_lazy(f"admin:app_{model}_changelist")


def _superuser(request) -> bool:
    return request.user.is_superuser


UNFOLD = {
    "SITE_TITLE": "Компас",
    "SITE_HEADER": "Компас",
    "SITE_SUBHEADER": "Данные сервиса",
    "SITE_URL": "/",
    "SITE_ICON": lambda request: static("icon.png"),
    "SITE_FAVICONS": [
        {"rel": "icon", "type": "image/png", "href": lambda request: static("icon.png")},
    ],
    "SITE_DROPDOWN": [
        {"icon": "smartphone", "title": "Мини-приложение ученика", "link": "/"},
        {"icon": "co_present", "title": "Кабинет педагога", "link": "/static/teacher.html"},
        {"icon": "api", "title": "API · Swagger", "link": "/api/docs"},
    ],
    # без этого вход без ?next= уводит на /accounts/profile/ — такой страницы нет
    "LOGIN": {"redirect_after": lambda request: reverse_lazy("admin:index")},
    "ENVIRONMENT": "app.admin_ui.environment_callback",
    "DASHBOARD_CALLBACK": "app.admin_ui.dashboard_callback",
    "STYLES": [lambda request: static("admin/kompas.css")],
    "SHOW_HISTORY": True,
    "BORDER_RADIUS": "8px",
    "COLORS": {
        # тёплые серо-зелёные тона бумаги и туши, как в styles.css
        "base": {
            "50": "oklch(98.5% .004 120)",
            "100": "oklch(95.5% .01 120)",
            "200": "oklch(91% .013 125)",
            "300": "oklch(85% .015 130)",
            "400": "oklch(70% .017 150)",
            "500": "oklch(55% .018 165)",
            "600": "oklch(45% .019 172)",
            "700": "oklch(37% .019 176)",
            "800": "oklch(29% .019 178)",
            "900": "oklch(23.5% .019 179)",
            "950": "oklch(16% .015 180)",
        },
        # красная стрелка компаса: 500 — это #D4442A
        "primary": {
            "50": "oklch(97.5% .012 33)",
            "100": "oklch(94.5% .03 33)",
            "200": "oklch(89% .06 33)",
            "300": "oklch(80% .11 33)",
            "400": "oklch(69% .16 33)",
            "500": "oklch(59% .185 32.5)",
            "600": "oklch(53% .175 32.5)",
            "700": "oklch(49.5% .155 32)",
            "800": "oklch(40% .13 32)",
            "900": "oklch(33% .1 32)",
            "950": "oklch(23% .07 32)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Обзор",
                "items": [
                    {"title": "Главная", "icon": "dashboard", "link": reverse_lazy("admin:index")},
                ],
            },
            {
                "title": "Ученики и классы",
                "collapsible": False,
                "items": [
                    {"title": "Ученики и педагоги", "icon": "group", "link": _link("user")},
                    {"title": "Классы", "icon": "school", "link": _link("schoolclass")},
                    {"title": "Задания классам", "icon": "assignment", "link": _link("classassignment")},
                    {"title": "Приглашения педагогов", "icon": "mail", "link": _link("teacherinvite")},
                ],
            },
            {
                "title": "Тест и профессии",
                "items": [
                    {"title": "Результаты тестов", "icon": "quiz", "link": _link("testresult")},
                    {"title": "Рекомендации", "icon": "work", "link": _link("recommendation")},
                ],
            },
            {
                "title": "Тренажёр",
                "items": [
                    {"title": "Попытки решения", "icon": "edit_note", "link": _link("taskattempt")},
                    {"title": "Опыт и серии", "icon": "trending_up", "link": _link("userstats")},
                    {"title": "Достижения", "icon": "emoji_events", "link": _link("userachievement")},
                ],
            },
            {
                "title": "Бот и данные",
                "items": [
                    {"title": "Собеседники бота", "icon": "smart_toy", "link": _link("botaccount")},
                    {"title": "Согласия (152-ФЗ)", "icon": "verified_user", "link": _link("consent")},
                ],
            },
            {
                "title": "Доступ к админке",
                "items": [
                    {
                        "title": "Администраторы",
                        "icon": "admin_panel_settings",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                        "permission": "app.admin_ui._superuser",
                    },
                    {
                        "title": "Группы",
                        "icon": "shield_person",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                        "permission": "app.admin_ui._superuser",
                    },
                ],
            },
        ],
    },
}


def environment_callback(request):
    """Плашка в шапке: сразу видно, что это прототип, а не боевые данные школы."""
    from django.conf import settings

    return ["Отладка", "warning"] if settings.DEBUG else ["Прототип · хакатон", "info"]


def dashboard_callback(request, context):
    """Метрики для главной страницы админки (templates/admin/index.html)."""
    from django.db.models import Count, Q

    from app.models import (
        Recommendation,
        SchoolClass,
        TaskAttempt,
        TestResult,
        User,
        UserRole,
    )
    from app.services.ai_recommender import FALLBACK_MODEL_NAME

    сегодня = timezone.localdate()
    начало = сегодня - timedelta(days=13)

    по_дням = Counter(
        timezone.localtime(момент).date()
        for момент in TestResult.objects.filter(completed_at__date__gte=начало).values_list(
            "completed_at", flat=True
        )
    )
    дни = [начало + timedelta(days=i) for i in range(14)]

    попытки = TaskAttempt.objects.aggregate(
        всего=Count("id"), верно=Count("id", filter=Q(is_correct=True))
    )
    рекомендаций = Recommendation.objects.count()
    от_модели = Recommendation.objects.exclude(model_used=FALLBACK_MODEL_NAME).count()

    профессии: Counter[str] = Counter()
    категории: Counter[str] = Counter()
    for список in Recommendation.objects.values_list("professions", flat=True):
        for профессия in список or []:
            профессии[профессия.get("name", "—")] += 1
            категории[профессия.get("category", "не указана")] += 1

    доверие = Counter(
        (integrity or {}).get("trust", "unknown")
        for integrity in TestResult.objects.values_list("integrity", flat=True)
    )
    тестов = TestResult.objects.count()

    context.update(
        {
            "kpis": [
                {
                    "title": "Учеников",
                    "value": User.objects.filter(role=UserRole.student).count(),
                    "footer": f"педагогов — {User.objects.filter(role=UserRole.teacher).count()}",
                    "icon": "group",
                    "href": reverse_lazy("admin:app_user_changelist"),
                },
                {
                    "title": "Прохождений теста",
                    "value": тестов,
                    "footer": f"за 14 дней — {sum(по_дням.values())}",
                    "icon": "quiz",
                    "href": reverse_lazy("admin:app_testresult_changelist"),
                },
                {
                    "title": "Классов",
                    "value": SchoolClass.objects.count(),
                    "footer": "с кодом для вступления",
                    "icon": "school",
                    "href": reverse_lazy("admin:app_schoolclass_changelist"),
                },
                {
                    "title": "Решено задач",
                    "value": попытки["всего"],
                    "footer": (
                        f"верно — {round(попытки['верно'] * 100 / попытки['всего'])}%"
                        if попытки["всего"]
                        else "тренажёром ещё не пользовались"
                    ),
                    "icon": "edit_note",
                    "href": reverse_lazy("admin:app_taskattempt_changelist"),
                },
            ],
            "tests_chart": json.dumps(
                {
                    "labels": [д.strftime("%d.%m") for д in дни],
                    "datasets": [
                        {
                            "label": "Прохождений",
                            "data": [по_дням.get(д, 0) for д in дни],
                            "backgroundColor": "var(--color-primary-500)",
                            "maxBarThickness": 36,
                            "borderRadius": 6,
                        }
                    ],
                }
            ),
            "model_share": round(от_модели * 100 / рекомендаций) if рекомендаций else 0,
            "recommendations_total": рекомендаций,
            "sources": [
                {"title": "Модель (GigaChat)", "count": от_модели, "variant": "success"},
                {"title": "Запасной алгоритм", "count": рекомендаций - от_модели, "variant": "warning"},
            ],
            "trust": [
                {"title": "Можно доверять", "count": доверие.get("high", 0), "variant": "success"},
                {"title": "Есть сомнения", "count": доверие.get("medium", 0), "variant": "warning"},
                {"title": "Похоже на прокликивание", "count": доверие.get("low", 0), "variant": "danger"},
            ],
            "trust_total": тестов,
            "top_professions": профессии.most_common(6),
            "top_categories": категории.most_common(5),
            "categories_total": sum(категории.values()),
        }
    )
    return context
