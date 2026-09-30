"""Регистрация, вход и профиль.

У ученика ровно один путь входа — подпись мессенджера (/miniapp). Ни почты,
ни гостевого режима у него нет: раньше один человек мог завести аккаунт на
сайте и второй через Telegram, и это были разные записи с разным прогрессом.

Регистрация и вход по почте остались только для педагогов: кабинет с
классами открывается в обычном браузере, где подписи мессенджера нет.
"""

from __future__ import annotations

import logging
import secrets

from asgiref.sync import sync_to_async
from django.db import transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.security import HttpBearer

from app.models import BotAccount, User, UserRole
from app.schemas.auth import (
    InviteCreateRequest,
    InviteOut,
    LoginRequest,
    MiniAppLoginRequest,
    ProfileOut,
    RegisterRequest,
    TokenResponse,
)
from app.services import invites
from app.services.miniapp_auth import full_name_from, verify_max, verify_telegram
from app.services.rate_limit import limit
from app.services.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)

router = Router(tags=["auth"])

# регистрация педагогов штучная: пять аккаунтов в час с адреса — с запасом
_лимит_регистрации = limit("register", times=5, seconds=3600)
# десять попыток в минуту: человек с забытым паролем уложится, перебор — нет
_лимит_входа = limit("login", times=10, seconds=60)
# Класс сидит за одним NAT и открывает приложение одновременно — лимит
# должен вмещать весь кабинет разом, иначе половина урока не войдёт.
_лимит_мини_приложения = limit("miniapp", times=60, seconds=60)


class JWTAuth(HttpBearer):
    """Пользователь из заголовка Authorization: Bearer <token>.

    Нет заголовка — Ninja отвечает 401 (текст задан в app/api.py). Токен есть,
    но плохой — 401 со своей причиной, чтобы фронт показал, что делать.
    """

    is_async = True

    async def authenticate(self, request: HttpRequest, token: str) -> User:
        user_id = decode_access_token(token.strip())
        if user_id is None:
            raise HttpError(401, "Токен недействителен — войдите заново")
        user = await User.objects.filter(id=user_id).afirst()
        if user is None or not user.is_active:
            raise HttpError(401, "Аккаунт не найден или отключён")
        return user


jwt_auth = JWTAuth()


async def optional_user(request: HttpRequest) -> User | None:
    """Пользователь, если он вошёл, иначе None.

    Для эндпоинтов, которые обязаны работать и анонимно: демо-страница и первый
    заход в мини-приложение идут без токена, и падать там нельзя.
    """
    ожидание = jwt_auth(request)
    if ожидание is None:
        return None
    try:
        return await ожидание
    except HttpError:
        return None


def _profile(user: User) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        max_user_id=user.max_user_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        grade=user.grade,
        class_id=user.class_ref_id,
        school_class=user.school_class,
    )


@sync_to_async
@transaction.atomic
def _register_teacher(payload: RegisterRequest, email: str) -> User | None:
    """Аккаунт и погашение кода — одной транзакцией.

    Код гасим уже за созданным пользователем. Не подошёл — откатываем всё,
    недорегистрированный аккаунт с занятой почтой не остаётся.
    """
    user = User.objects.create(
        max_user_id=f"web_{secrets.token_hex(6)}",
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        # роль жёстко задана здесь, а не приходит из запроса: иначе через эту
        # ручку снова можно было бы завести ученика в обход мессенджера
        role=UserRole.teacher,
        is_active=True,
    )
    if not invites.redeem(payload.invite_code, user.id):
        transaction.set_rollback(True)
        return None
    return user


@router.post("/register", response={201: TokenResponse})
async def register(request: HttpRequest, payload: RegisterRequest):
    """Регистрация педагога. Ученику этот путь закрыт — он входит через мессенджер."""
    _лимит_регистрации(request)
    email = payload.email.strip().lower()
    if await User.objects.filter(email__iexact=email).aexists():
        raise HttpError(409, "Аккаунт с такой почтой уже есть — войдите")

    user = await _register_teacher(payload, email)
    if user is None:
        raise HttpError(403, "Код приглашения недействителен, истёк или уже использован")

    logger.info("Регистрация педагога: %s", email)
    return 201, TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.post("/invites", response={201: InviteOut}, auth=jwt_auth)
async def create_invite(request: HttpRequest, payload: InviteCreateRequest):
    """Выписать код приглашения коллеге.

    Приглашать может только тот, кто сам уже подтверждён: иначе цепочка доверия
    рвётся на первом же звене и код перестаёт что-либо значить.
    """
    user: User = request.auth
    if user.role != UserRole.teacher:
        raise HttpError(403, "Приглашать коллег может только педагог")

    invite = await invites.create(created_by=user, note=payload.note)
    logger.info("Код приглашения выписан педагогом %s", user.email)
    return 201, InviteOut(
        code=invite.code, note=invite.note, expires_at=invite.expires_at, used_at=None
    )


@router.post("/login", response=TokenResponse)
async def login(request: HttpRequest, payload: LoginRequest) -> TokenResponse:
    _лимит_входа(request)
    email = payload.email.strip().lower()
    user = await User.objects.filter(email__iexact=email).afirst()

    # одинаковый ответ на «нет такого email» и «неверный пароль» —
    # иначе форма входа превращается в проверялку существующих аккаунтов
    if user is None or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HttpError(401, "Неверная почта или пароль")
    if not user.is_active:
        raise HttpError(401, "Аккаунт отключён")

    return TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.post("/miniapp", response=TokenResponse)
async def miniapp_login(request: HttpRequest, payload: MiniAppLoginRequest) -> TokenResponse:
    """Вход из мини-приложения мессенджера.

    Подпись initData доказывает, кто открыл приложение, поэтому регистрация
    не нужна: аккаунт заводится сам при первом открытии. Если этот же человек
    уже писал боту, используется его существующая учётная запись — прогресс из
    чата и из приложения общий.
    """
    _лимит_мини_приложения(request)
    verify = verify_telegram if payload.platform == "telegram" else verify_max
    profile = verify(payload.init_data)
    if profile is None:
        raise HttpError(401, "Не удалось подтвердить, что запрос пришёл из мессенджера")

    account = await BotAccount.objects.filter(
        platform=profile["platform"], external_id=profile["external_id"]
    ).afirst()

    user = None
    if account and account.user_id:
        user = await User.objects.filter(id=account.user_id).afirst()
    if user is None:
        user = await User.objects.acreate(
            max_user_id=f"{profile['platform']}_{profile['external_id']}",
            role=UserRole.student,
            full_name=full_name_from(profile),
        )
        logger.info("Мини-приложение: заведён аккаунт для %s", user.max_user_id)

    # связываем чат и аккаунт, чтобы бот сразу знал, чей это прогресс
    if account is None:
        await BotAccount.objects.acreate(
            platform=profile["platform"],
            external_id=profile["external_id"],
            chat_id=profile["external_id"],
            user_id=user.id,
        )
    else:
        account.user_id = user.id
        account.link_code = None
        await account.asave(update_fields=["user", "link_code"])

    return TokenResponse(access_token=create_access_token(user.id), user=_profile(user))


@router.get("/me", response=ProfileOut, auth=jwt_auth)
async def me(request: HttpRequest) -> ProfileOut:
    return _profile(request.auth)
