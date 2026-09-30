"""Вебхуки мессенджеров и привязка бота к аккаунту.

Вебхук всегда отвечает 200: если вернуть ошибку, платформа начнёт повторять
доставку одного и того же события, и ученик получит несколько одинаковых
сообщений. Все сбои уходят в лог.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from app.config import get_settings
from app.models import BotAccount
from app.routers.auth import jwt_auth
from app.schemas.bot import LinkBotRequest, LinkBotResponse
from app.services import bot_transport
from app.services.bot_core import BotReply, handle
from app.services.rate_limit import limit

logger = logging.getLogger(__name__)

router = Router(tags=["bot"])

OK = {"status": "ok"}

# Вебхук зовёт платформа, а не пользователь: лимит здесь только против
# потока с чужого адреса. Ставим высоко — потерянное событие бота
# обходится дороже, чем лишний обработанный запрос.
_лимит_вебхука = limit("webhook", times=600, seconds=60)


async def _process(event, sender) -> dict[str, Any]:
    """Событие → ответ → отправка.

    Любая ошибка гасится здесь: вебхук обязан ответить 200, иначе мессенджер
    сочтёт доставку неудачной и будет слать то же событие снова, а ученик
    получит поток одинаковых сообщений.
    """
    settings = get_settings()
    try:
        reply = await handle(event, app_url=settings.app_public_url or None)
    except Exception:  # noqa: BLE001 — причину пишем в лог, наружу отдаём извинение
        logger.exception("Сбой обработки события бота (%s)", event.platform)
        reply = BotReply(text="Что-то пошло не так на моей стороне. Попробуй ещё раз чуть позже.")

    await sender(event.chat_id, reply)
    return OK


def _check_secret(request: HttpRequest, header: str, expected: str, what: str) -> None:
    if not expected:
        return
    received = request.headers.get(header)
    if not received or not hmac.compare_digest(received, expected):
        logger.warning("%s: неверный секрет, запрос отклонён", what)
        raise HttpError(401, "Неверный секрет")


def _json_body(request: HttpRequest) -> Any:
    try:
        return json.loads(request.body)
    except ValueError:
        return None


@router.post("/telegram")
async def telegram_webhook(request: HttpRequest) -> dict[str, Any]:
    _лимит_вебхука(request)
    _check_secret(
        request,
        "X-Telegram-Bot-Api-Secret-Token",
        get_settings().telegram_webhook_secret,
        "Вебхук Telegram",
    )

    update = _json_body(request)
    if update is None:
        return OK

    event = bot_transport.parse_telegram(update)
    if event is None or not event.external_id:
        return OK
    return await _process(event, bot_transport.send_telegram)


@router.post("/max")
async def max_webhook(request: HttpRequest) -> dict[str, Any]:
    """Вебхук MAX. Логика та же, отличается только разбор и отправка.

    Секрет задаётся при подписке (POST /subscriptions) и приходит обратно как
    есть в заголовке X-Max-Bot-Api-Secret — платформа не подписывает тело, а
    просто возвращает значение, поэтому сверяем строки.
    """
    _лимит_вебхука(request)
    _check_secret(request, "X-Max-Bot-Api-Secret", get_settings().max_webhook_secret, "Вебхук MAX")

    update = _json_body(request)
    if update is None:
        return OK

    event = bot_transport.parse_max(update)
    if event is None or not event.external_id:
        logger.info("Вебхук MAX: событие не распознано: %s", str(update)[:300])
        return OK
    result = await _process(event, bot_transport.send_max)
    if event.callback_id:
        # без этого у нажавшего кнопку крутится индикатор загрузки до таймаута
        await bot_transport.answer_max_callback(event.callback_id)
    return result


@router.post("/link", response=LinkBotResponse, auth=jwt_auth)
async def link_bot(request: HttpRequest, payload: LinkBotRequest) -> LinkBotResponse:
    """Привязать бота к аккаунту по коду, который бот прислал в чат.

    Код вводится в приложении, где пользователь уже вошёл, — поэтому владелец
    аккаунта известен достоверно и подменить его нельзя.
    """
    user = request.auth
    code = payload.code.strip().upper()
    account = await BotAccount.objects.filter(link_code=code).afirst()
    if account is None:
        raise HttpError(404, "Код не найден — попроси бота прислать новый")

    account.user_id = user.id
    account.link_code = None
    await account.asave(update_fields=["user", "link_code"])
    logger.info("Бот %s привязан к пользователю %s", account.platform, user.max_user_id)
    return LinkBotResponse(platform=account.platform, linked=True)


@router.get("/status", response=LinkBotResponse, auth=jwt_auth)
async def link_status(request: HttpRequest) -> LinkBotResponse:
    account = await BotAccount.objects.filter(user_id=request.auth.id).afirst()
    if account is None:
        return LinkBotResponse(platform="", linked=False)
    return LinkBotResponse(platform=account.platform, linked=True)
