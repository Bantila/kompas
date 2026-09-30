"""Админка открывается: главная с метриками, списки и карточка прохождения.

Шаблоны админки проверяются только при рендере — опечатка в поле list_display
или в дашборде роняет страницу с 500, и тесты API этого не видят.
"""

from __future__ import annotations

from asgiref.sync import sync_to_async
from django.contrib.auth.models import User as StaffUser
from django.test import Client

from app.models import TestResult

СПИСКИ = (
    "user", "schoolclass", "classassignment", "teacherinvite", "testresult", "recommendation",
    "taskattempt", "userstats", "userachievement", "botaccount", "consent",
)


def _обойти_админку(result_id) -> dict[str, int]:
    браузер = Client()
    браузер.force_login(StaffUser.objects.create_superuser("root", "root@example.com", "pw"))
    адреса = ["/admin/", f"/admin/app/testresult/{result_id}/change/"]
    адреса += [f"/admin/app/{модель}/" for модель in СПИСКИ]
    return {адрес: браузер.get(адрес).status_code for адрес in адреса}


async def test_admin_pages_render(client, согласившийся, full_answers) -> None:
    await согласившийся("admin_demo_1", full_name="Ученик")
    ответ = await client.post(
        "/api/tests/submit", json={"max_user_id": "admin_demo_1", "answers": full_answers}
    )
    assert ответ.status_code == 201

    результат = await TestResult.objects.afirst()
    коды = await sync_to_async(_обойти_админку)(результат.id)

    assert коды == {адрес: 200 for адрес in коды}


async def test_admin_requires_staff_login(client) -> None:
    ответ = await client.get("/admin/")

    assert ответ.status_code == 302
    assert "/admin/login/" in ответ.headers["location"]
