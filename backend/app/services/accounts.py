"""Аккаунты и входы без Telegram (B2B_PLATFORM_PLAN, шаг 2.1).

Здесь три вещи, каждая из которых легко делается неправильно:

1. **Пароль.** PBKDF2-HMAC-SHA256, своя соль на пользователя, 600 000
   итераций. Без внешних библиотек — в проекте их нет, а тащить `bcrypt`
   ради двух функций значит ломать сборку на хостинге. Формат хеша
   самодостаточен (`алгоритм$итерации$соль$хеш`), поэтому итерации можно
   поднять позже без миграции: старые хеши проверятся своими параметрами.
2. **Сессия.** В базе только SHA-256 от токена. Токен — случайные 32 байта,
   знает его лишь клиент. Сессию можно отозвать (выход), истечь по сроку
   и убить все сразу (смена пароля).
3. **Сброс пароля.** Одинаковый ответ на существующий и несуществующий адрес,
   одноразовая ссылка на час и отзыв всех сессий после смены. Иначе сброс
   превращается в способ узнать, кто у нас зарегистрирован, и в способ
   оставить чужой вход живым.

Тенант здесь не фильтруется: вход происходит до того, как известно, в какую
организацию идёт человек. Организация записывается в сессию при входе и
ставится в контекст в `deps.current_user`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.auth_models import AuthSession, EmailVerification, PasswordReset
from app.db.models import User
from app.db.seed import color_for_user
from app.services import orgs

PBKDF2_ITERATIONS = 600_000
PBKDF2_ALGORITHM = "pbkdf2_sha256"
MIN_PASSWORD = 8
MAX_PASSWORD = 128
RESET_TTL = timedelta(hours=1)
# Сколько сбросов на адрес за час считаем нормой. Больше — молча не отправляем
# письмо (ответ всё равно 200), иначе форма сброса превращается в генератор
# писем на чужой ящик.
RESET_LIMIT_PER_HOUR = 3
# Обновлять `last_seen_at` на каждом запросе — лишняя запись в базу; минуты
# хватает, чтобы список устройств был правдивым.
LAST_SEEN_STEP = timedelta(minutes=5)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class AccountsError(Exception):
    """Ошибка аккаунта: код уходит клиенту, текст — человеку."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """sqlite отдаёт naive datetime: сравнивать с aware нельзя."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def normalize_email(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not EMAIL_RE.match(value) or len(value) > 255:
        raise AccountsError("bad_email")
    return value


def validate_password(password: str) -> str:
    value = password or ""
    if len(value) < MIN_PASSWORD:
        raise AccountsError("password_too_short")
    if len(value) > MAX_PASSWORD:
        raise AccountsError("password_too_long")
    if value.strip() != value:
        raise AccountsError("password_has_spaces")
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PBKDF2_ITERATIONS
    )
    return "$".join(
        (
            PBKDF2_ALGORITHM,
            str(PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        )
    )


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$", 3)
        if algorithm != PBKDF2_ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def register(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
) -> User:
    """Завести аккаунт по почте. Членство в организации появляется отдельно.

    Регистрация не создаёт сотрудника: без приглашения человек не принадлежит
    ни одной организации, иначе он молча оказался бы в первой (шаг 2.2).
    """
    clean_email = normalize_email(email)
    clean_password = validate_password(password)
    if await by_email(session, clean_email) is not None:
        raise AccountsError("email_taken")

    name = (display_name or "").strip() or clean_email.split("@", 1)[0]
    # Цвет — визуальная метка в интерфейсе; берём стабильный от адреса, чтобы
    # у человека он не менялся от входа к входу.
    seed = int.from_bytes(hashlib.sha256(clean_email.encode()).digest()[:6], "big")
    user = User(
        telegram_id=None,
        email=clean_email,
        password_hash=hash_password(clean_password),
        display_name=name[:64],
        color_hex=color_for_user(seed),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Проверить почту и пароль.

    Ошибка одна и та же для «нет такого адреса» и «неверный пароль»: иначе
    форма входа рассказывает, кто у нас зарегистрирован. Для адреса без пароля
    (аккаунт только из Telegram) — отдельный код `password_not_set`, чтобы
    человек понял, что делать, а не искал опечатку.
    """
    clean_email = normalize_email(email)
    user = await by_email(session, clean_email)
    if user is None:
        # Тратим столько же времени, сколько на настоящую проверку.
        verify_password(password, hash_password("dummy-password"))
        raise AccountsError("invalid_credentials")
    if not user.password_hash:
        raise AccountsError("password_not_set")
    if not verify_password(password, user.password_hash):
        raise AccountsError("invalid_credentials")
    return user


async def create_session(
    session: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ttl: timedelta | None = None,
) -> tuple[AuthSession, str]:
    """Выдать токен входа. Возвращает (строка сессии, токен для клиента)."""
    settings = get_settings()
    lifetime = ttl or timedelta(days=settings.auth_session_days)
    # Организация — только из членства: у нового аккаунта его нет, и это
    # нормально (вход есть, данных нет — ждём приглашения).
    memberships = await orgs.orgs_of(session, user.id)
    org_id = memberships[0].id if memberships else None

    token = _new_token()
    row = AuthSession(
        user_id=user.id,
        org_id=org_id,
        token_hash=token_hash(token),
        user_agent=(user_agent or "")[:500] or None,
        expires_at=_now() + lifetime,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row, token


async def resolve_session(
    session: AsyncSession, token: str
) -> tuple[User, int | None] | None:
    """Кто это по токену. None — токена нет, он истёк или отозван."""
    if not token:
        return None
    row = await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash(token))
    )
    if row is None or row.revoked_at is not None:
        return None
    now = _now()
    if _aware(row.expires_at) <= now:
        return None
    user = await session.get(User, row.user_id)
    if user is None:
        return None

    # Отмечаем активность не чаще раза в LAST_SEEN_STEP: иначе каждый запрос
    # мини-аппа писал бы в базу.
    if now - _aware(row.last_seen_at) > LAST_SEEN_STEP:
        row.last_seen_at = now
        await session.commit()
    return user, row.org_id


async def revoke(session: AsyncSession, row: AuthSession) -> None:
    if row.revoked_at is None:
        row.revoked_at = _now()
        await session.commit()


async def revoke_token(session: AsyncSession, token: str) -> bool:
    row = await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash(token))
    )
    if row is None or row.revoked_at is not None:
        return False
    await revoke(session, row)
    return True


async def revoke_all(session: AsyncSession, user_id: int) -> int:
    """Погасить все живые входы человека (выход везде, смена пароля)."""
    rows = list(
        await session.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        )
    )
    now = _now()
    for row in rows:
        row.revoked_at = now
    if rows:
        await session.commit()
    return len(rows)


async def active_sessions(session: AsyncSession, user_id: int) -> list[AuthSession]:
    now = _now()
    rows = list(
        await session.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .order_by(AuthSession.last_seen_at.desc())
        )
    )
    return [row for row in rows if _aware(row.expires_at) > now]


async def request_reset(
    session: AsyncSession, email: str
) -> tuple[User | None, str | None]:
    """Создать ссылку сброса. Возвращает (человек, токен) — или (None, None).

    (None, None) отдаём и для несуществующего адреса, и когда лимит писем
    исчерпан: снаружи все три случая выглядят одинаково.
    """
    try:
        clean_email = normalize_email(email)
    except AccountsError:
        return None, None
    user = await by_email(session, clean_email)
    if user is None or not user.password_hash:
        return None, None

    since = _now() - timedelta(hours=1)
    recent = await session.scalar(
        select(func.count())
        .select_from(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.created_at >= since)
    )
    if (recent or 0) >= RESET_LIMIT_PER_HOUR:
        return None, None

    token = _new_token()
    session.add(
        PasswordReset(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=_now() + RESET_TTL,
        )
    )
    await session.commit()
    return user, token


async def confirm_reset(
    session: AsyncSession, *, token: str, password: str
) -> User:
    """Сменить пароль по ссылке. Ссылка одноразовая, сессии гасятся."""
    clean_password = validate_password(password)
    row = await session.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == token_hash(token))
    )
    if row is None or row.used_at is not None:
        raise AccountsError("reset_invalid")
    if _aware(row.expires_at) <= _now():
        raise AccountsError("reset_expired")
    user = await session.get(User, row.user_id)
    if user is None:
        raise AccountsError("reset_invalid")

    user.password_hash = hash_password(clean_password)
    row.used_at = _now()
    await session.commit()
    # Старые входы могли быть у того, кто получил доступ к ящику: после смены
    # пароля живых сессий не остаётся.
    await revoke_all(session, user.id)
    return user


def reset_link(token: str) -> str:
    return f"{get_settings().link_base}/reset?token={token}"


# --------------------------------------------------------------------------
# Подтверждение адреса (шаг 2.1)
# --------------------------------------------------------------------------

# Двое суток: письмо может попасть в спам или человек откроет его с рабочего
# компьютера через день. Срок не бесконечный — ссылка всё-таки одноразовая.
VERIFY_TTL = timedelta(days=2)
# Больше трёх писем в час на аккаунт — уже похоже на спам чужого ящика.
VERIFY_LIMIT_PER_HOUR = 3


async def request_email_verification(
    session: AsyncSession, user: User
) -> str | None:
    """Выпустить новую ссылку подтверждения. `None` — письмо не нужно.

    `None` возвращаем, если адреса нет (вход только по Telegram) или адрес уже
    подтверждён, и когда исчерпан лимит писем: снаружи это не различить, но
    лишних писем не уходит.
    """
    if not user.email or user.email_verified_at is not None:
        return None
    since = _now() - timedelta(hours=1)
    recent = await session.scalar(
        select(func.count())
        .select_from(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.created_at >= since,
        )
    )
    if (recent or 0) >= VERIFY_LIMIT_PER_HOUR:
        return None

    token = _new_token()
    session.add(
        EmailVerification(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=_now() + VERIFY_TTL,
        )
    )
    await session.commit()
    return token


async def confirm_email(session: AsyncSession, token: str) -> User:
    """Подтвердить адрес по ссылке. Повторный клик по той же ссылке — не ошибка.

    Человек может открыть письмо дважды, и после первого раза адрес уже
    подтверждён: это успех, а не «ссылка не подходит».
    """
    row = await session.scalar(
        select(EmailVerification).where(
            EmailVerification.token_hash == token_hash(token)
        )
    )
    if row is None:
        raise AccountsError("verify_invalid")
    user = await session.get(User, row.user_id)
    if user is None:
        raise AccountsError("verify_invalid")
    if row.used_at is not None:
        if user.email_verified_at is not None:
            return user
        raise AccountsError("verify_invalid")
    if _aware(row.expires_at) <= _now():
        raise AccountsError("verify_expired")

    if user.email_verified_at is None:
        user.email_verified_at = _now()
    # Остальные живые ссылки гасим: подтверждённый адрес не нуждается в них,
    # а в почте не остаётся полудюжины рабочих входов.
    others = await session.scalars(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.used_at.is_(None),
        )
    )
    for other in others.all():
        other.used_at = _now()
    await session.commit()
    return user


def verify_link(token: str) -> str:
    return f"{get_settings().link_base}/verify?token={token}"
