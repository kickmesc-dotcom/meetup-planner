"""Письма: сброс пароля и приглашения (B2B_PLATFORM_PLAN, шаг 2.1).

Зачем свой тонкий слой, а не SDK. Писем у нас единицы и все системные
(сброс пароля, приглашение). Провайдер при этом — выбор клиента: у российской
компании это может быть Яндекс 360 по SMTP, у другой — Resend по HTTP. Поэтому
транспорт выбирается по настройкам, а не импортом библиотеки:

* `RESEND_API_KEY` — HTTP API Resend (письма через httpx, уже в зависимостях);
* `SMTP_HOST` — любой SMTP (Яндекс 360, Unisender, корпоративный релей);
* ничего не задано — режим «лог»: письмо не уходит, в журнал пишется факт
  отправки БЕЗ ссылки и токена. Это позволяет поднять вход по почте до того,
  как заведён домен отправителя, и не светит одноразовые ссылки в логах.

Текст письма — обычный текст, не HTML: меньше поводов попасть в спам и нечего
экранировать.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger()

RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class MailMessage:
    to: str
    subject: str
    text: str


class MailError(Exception):
    """Письмо не ушло. Вызывающий решает, показать ли это человеку."""


def transport() -> str:
    """Какой транспорт настроен: `resend`, `smtp` или `log`."""
    settings = get_settings()
    if getattr(settings, "resend_api_key", ""):
        return "resend"
    if getattr(settings, "smtp_host", ""):
        return "smtp"
    return "log"


async def send(message: MailMessage) -> str:
    """Отправить письмо. Возвращает имя использованного транспорта.

    Ошибки транспорта не пробрасываются в API в виде 500: для сброса пароля
    это выдало бы существование адреса. Ручка решает сама, что показать.
    """
    kind = transport()
    settings = get_settings()

    if kind == "resend":
        await _send_resend(message, settings)
    elif kind == "smtp":
        await asyncio.to_thread(_send_smtp, message, settings)
    else:
        # Без домена отправителя письмо всё равно не дойдёт, а ссылку в логах
        # видеть не должен никто, кроме владельца машины в разработке.
        log.warning("mail.skipped_no_transport", to=message.to, subject=message.subject)
    return kind


async def _send_resend(message: MailMessage, settings) -> None:  # noqa: ANN001
    payload = {
        "from": settings.mail_from,
        "to": [message.to],
        "subject": message.subject,
        "text": message.text,
    }
    headers = {"Authorization": f"Bearer {settings.resend_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(RESEND_URL, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("mail.resend_failed", error=exc.__class__.__name__)
        raise MailError("resend_transport") from exc
    if response.status_code >= 300:
        log.warning("mail.resend_rejected", status=response.status_code)
        raise MailError(f"resend_status_{response.status_code}")


def _send_smtp(message: MailMessage, settings) -> None:  # noqa: ANN001
    email = EmailMessage()
    email["From"] = settings.mail_from
    email["To"] = message.to
    email["Subject"] = message.subject
    email.set_content(message.text)

    port = int(settings.smtp_port or 465)
    # 465 — неявный TLS с первого байта, 587 — STARTTLS. Перепутать их значит
    # получить «зависло на подключении» вместо понятной ошибки.
    try:
        if port == 465:
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                port,
                timeout=20,
                context=ssl.create_default_context(),
            ) as smtp:
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(email)
        else:
            with smtplib.SMTP(settings.smtp_host, port, timeout=20) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(email)
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("mail.smtp_failed", error=exc.__class__.__name__)
        raise MailError("smtp_transport") from exc


def reset_email(*, to: str, link: str, minutes: int) -> MailMessage:
    """Письмо со ссылкой сброса. Ссылка одноразовая и живёт час."""
    return MailMessage(
        to=to,
        subject="Сброс пароля SemiTaskBot",
        text=(
            "Здравствуйте!\n\n"
            "Мы получили запрос на сброс пароля. Перейдите по ссылке:\n\n"
            f"{link}\n\n"
            f"Ссылка действует {minutes} минут и работает один раз. "
            "Если вы не запрашивали сброс, просто проигнорируйте письмо — "
            "пароль останется прежним.\n\n"
            "SemiTaskBot"
        ),
    )


def notification_email(
    *, to: str, subject: str, text: str, link: str
) -> MailMessage:
    """Важное событие смены без Telegram (шаг 2.4): срок, просрочка, эскалация.

    Письмо уходит только тем, у кого нет push-подписки: дублировать одно и то
    же в два канала — верный способ научить человека отключать оба.
    """
    return MailMessage(
        to=to,
        subject=subject,
        text=(
            f"{text}\n\n"
            "Открыть приложение:\n"
            f"{link}\n\n"
            "Уведомления в браузере включаются в профиле — тогда письма не нужны.\n\n"
            "SemiTaskBot"
        ),
    )


def invite_email(*, to: str, org_name: str, link: str) -> MailMessage:
    """Приглашение в организацию (шаг 2.2)."""
    return MailMessage(
        to=to,
        subject=f"Приглашение в {org_name}",
        text=(
            f"Вас пригласили в {org_name} — рабочее приложение для команды.\n\n"
            "Откройте ссылку, чтобы присоединиться:\n\n"
            f"{link}\n\n"
            "Если вы не ждали приглашения, письмо можно проигнорировать.\n\n"
            "SemiTaskBot"
        ),
    )
