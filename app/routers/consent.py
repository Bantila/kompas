"""Согласие на обработку персональных данных: посмотреть, дать, отозвать."""

from __future__ import annotations

import logging

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from app.routers.auth import jwt_auth
from app.schemas.consent import (
    ConsentGrantRequest,
    ConsentJournalOut,
    ConsentRecordOut,
    ConsentRevokedOut,
    ConsentStatusOut,
)
from app.services import consent as service

logger = logging.getLogger(__name__)

router = Router(tags=["consent"], auth=jwt_auth)


@router.get("", response=ConsentStatusOut)
async def consent_status(request: HttpRequest) -> ConsentStatusOut:
    """Есть ли действующее согласие и на какую редакцию документа."""
    согласие = await service.active_for(request.auth.id)
    if согласие is None:
        return ConsentStatusOut(granted=False, current_version=service.CURRENT_VERSION)
    return ConsentStatusOut(
        granted=True,
        current_version=service.CURRENT_VERSION,
        document_version=согласие.document_version,
        granted_by=согласие.granted_by,
        granted_at=согласие.granted_at,
        # текст мог смениться после того, как человек согласился
        outdated=согласие.document_version != service.CURRENT_VERSION,
    )


@router.get("/journal", response=ConsentJournalOut)
async def consent_journal(request: HttpRequest) -> ConsentJournalOut:
    """Все согласия и отзывы по человеку, свежие сверху.

    При проверке спрашивают не «согласен ли сейчас», а «когда и на что
    соглашался, когда отзывал» — текущее состояние на это не отвечает.
    """
    записи = await service.journal(request.auth.id)
    return ConsentJournalOut(
        records=[
            ConsentRecordOut(
                document_version=з.document_version,
                granted_by=з.granted_by,
                age_at_consent=з.age_at_consent,
                granted_at=з.granted_at,
                revoked_at=з.revoked_at,
            )
            for з in записи
        ]
    )


@router.post("", response={201: ConsentStatusOut})
async def grant_consent(request: HttpRequest, payload: ConsentGrantRequest):
    """Дать согласие. Повторный вызов обновляет редакцию и снимает прежний отзыв."""
    user = request.auth
    try:
        согласие = await service.grant(
            user.id,
            version=service.CURRENT_VERSION,
            granted_by=payload.granted_by,
            age=payload.age,
        )
    except service.ConsentError as exc:
        raise HttpError(422, str(exc)) from exc
    logger.info("Согласие получено: пользователь %s, кем дано %s", user.id, согласие.granted_by)
    return 201, ConsentStatusOut(
        granted=True,
        current_version=service.CURRENT_VERSION,
        document_version=согласие.document_version,
        granted_by=согласие.granted_by,
        granted_at=согласие.granted_at,
        outdated=False,
    )


@router.delete("", response=ConsentRevokedOut)
async def revoke_consent(request: HttpRequest) -> ConsentRevokedOut:
    """Отозвать согласие и удалить обработанные данные.

    Именно удалить, а не пометить: сохранённые прохождения при отозванном
    согласии — это по-прежнему хранение данных ребёнка.
    """
    удалено = await service.revoke(request.auth.id)
    return ConsentRevokedOut(revoked=True, deleted_records=удалено)
