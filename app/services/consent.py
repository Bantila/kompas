"""Реестр согласий на обработку персональных данных.

152-ФЗ требует не галочку, а подтверждаемый факт: кто, когда и на какую
редакцию документа согласился — и возможность согласие отозвать, после чего
обработка прекращается.

Отзыв здесь не помечает данные, а удаляет их. Пометка «не обрабатывать» при
сохранённых прохождениях — это по-прежнему хранение данных ребёнка, то есть
обработка. Аккаунт остаётся: по нему и удерживается сам факт отзыва.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import F

from app.models import Consent, Recommendation, TaskAttempt, TestProgress, TestResult

logger = logging.getLogger(__name__)

# Редакция документа. Меняется вместе с текстом согласия — иначе неизвестно,
# с чем именно соглашался человек.
CURRENT_VERSION = "2026-08-25"

# Кто дал согласие. До 14 лет это законный представитель, и в реестре это
# должно быть видно, а не подразумеваться.
КТО_ДАЁТ = ("self", "parent")

# С 14 лет подросток вправе распоряжаться своими данными сам, до 14 — только
# законный представитель. Сервис для 12–16 лет, так что граница проходит прямо
# посреди аудитории и молча предполагать «сам» нельзя.
ВОЗРАСТ_САМОСТОЯТЕЛЬНОСТИ = 14


class ConsentError(ValueError):
    """Согласие не может быть принято в таком виде."""


# Свежие записи сверху. Второй ключ обязателен: SQLite ставит одинаковый
# granted_at записям, созданным в одну секунду, а сортировать по id нельзя —
# это случайный UUID, и отозванная запись перевешивала бы только что данное
# согласие. Действующая запись при равной дате считается более поздней.
_ПОРЯДОК_ЖУРНАЛА = ("-granted_at", F("revoked_at").asc(nulls_first=True))


def _действующее(user_id: uuid.UUID) -> Consent | None:
    """Действующее согласие: последняя запись журнала, если она не отозвана."""
    последняя = Consent.objects.filter(user_id=user_id).order_by(*_ПОРЯДОК_ЖУРНАЛА).first()
    if последняя is None or последняя.revoked_at is not None:
        return None
    return последняя


active_for = sync_to_async(_действующее)


async def journal(user_id: uuid.UUID) -> list[Consent]:
    """Все записи по человеку, свежие сверху.

    При проверке спрашивают не «согласен ли сейчас», а «когда и на что
    соглашался, когда отзывал» — на это и отвечает журнал.
    """
    return [
        запись
        async for запись in Consent.objects.filter(user_id=user_id).order_by(*_ПОРЯДОК_ЖУРНАЛА)
    ]


@sync_to_async
@transaction.atomic
def grant(
    user_id: uuid.UUID,
    *,
    version: str = CURRENT_VERSION,
    granted_by: str = "self",
    age: int | None = None,
) -> Consent:
    """Записать согласие. Повторный вызов обновляет редакцию и снимает отзыв."""
    if granted_by not in КТО_ДАЁТ:
        granted_by = "self"

    # Возраст назван самим учеником и ничем не подтверждён — проверить его
    # нечем. Но раз он назван, противоречить ему согласие не должно: «мне 12,
    # согласие даю сам» — это не согласие.
    if age is not None and age < ВОЗРАСТ_САМОСТОЯТЕЛЬНОСТИ and granted_by != "parent":
        raise ConsentError(
            f"До {ВОЗРАСТ_САМОСТОЯТЕЛЬНОСТИ} лет согласие даёт родитель "
            "или другой законный представитель"
        )

    # Новая запись, а не перезапись прежней: иначе история «дал, отозвал, дал
    # снова» стирается, а с ней и доказательство законности обработки.
    действующее = _действующее(user_id)
    if действующее is not None:
        if (
            действующее.document_version == version
            and действующее.granted_by == granted_by
            and действующее.age_at_consent == age
        ):
            # то же согласие на ту же редакцию — записывать нечего
            return действующее
        # согласие на новую редакцию закрывает предыдущее
        действующее.revoked_at = datetime.now(timezone.utc)
        действующее.save(update_fields=["revoked_at"])

    return Consent.objects.create(
        user_id=user_id,
        document_version=version,
        granted_by=granted_by,
        age_at_consent=age,
        granted_at=datetime.now(timezone.utc),
    )


@sync_to_async
@transaction.atomic
def revoke(user_id: uuid.UUID) -> int:
    """Отозвать согласие и удалить обработанные данные. Возвращает число записей.

    Всё в одной транзакции: удалённая наполовину история при оборванном
    запросе — худший исход, данные уже не целы, а согласие ещё не отозвано.
    Таблицы перечислены явно, а не отданы каскаду: так видно, что именно
    удаляется, и счётчик совпадает с числом записей.
    """
    удалено = Recommendation.objects.filter(test_result__user_id=user_id).delete()[0]
    for модель in (TestResult, TestProgress, TaskAttempt):
        удалено += модель.objects.filter(user_id=user_id).delete()[0]

    сейчас = datetime.now(timezone.utc)
    действующее = _действующее(user_id)
    if действующее is not None:
        действующее.revoked_at = сейчас
        действующее.save(update_fields=["revoked_at"])
    else:
        # действующего согласия не было, но отзыв всё равно фиксируем: иначе
        # следующая сдача теста запишет данные как ни в чём не бывало
        Consent.objects.create(
            user_id=user_id, document_version=CURRENT_VERSION, granted_at=сейчас, revoked_at=сейчас
        )

    logger.info("Согласие отозвано, удалено записей: %s", удалено)
    return удалено
