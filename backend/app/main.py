from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    MenuButtonWebApp,
    WebAppInfo,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_admin,
    routes_app_access,
    routes_auth,
    routes_availability,
    routes_birthdays,
    routes_calendar,
    routes_handovers,
    routes_hr,
    routes_hr_admin,
    routes_hr_ops_admin,
    routes_hr_training_plan,
    routes_issues,
    routes_materials,
    routes_media,
    routes_meetings,
    routes_meta,
    routes_orgs,
    routes_polls,
    routes_push,
    routes_reports,
    routes_reset,
    routes_shifts,
    routes_simulation,
    routes_standards,
    routes_texts,
    routes_users,
)
from app.bot import webhook as bot_webhook
from app.bot.dispatcher import get_bot
from app.bot.scheduler import (
    arm_leader_gate,
    release_scheduler_leadership,
    run_scheduler_leadership,
    shutdown_scheduler,
)
from app.api.guards import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.hr_seed import seed_hr
from app.log_redaction import log_processors
from app.api.deps import session_auth
from app.db.org_models import DEFAULT_ORG_ID, reset_org, set_org
from app.db.seed import seed_users


def _configure_logging(level: str) -> None:
    """Одна цепочка логов на все процессы: см. `app/log_redaction.py`."""
    logging.basicConfig(level=level.upper())
    structlog.configure(processors=log_processors())


# Срок проверки базы в `/readyz`. Две секунды — это уже плохо (нормальный
# `SELECT 1` на Neon — единицы миллисекунд), но ещₑ не «база лежит».
READY_DB_TIMEOUT_SECONDS = 2.0


async def _db_ping() -> None:
    """Самый дешёвый запрос к базе: ответила — контейнер готов к трафику."""
    from sqlalchemy import text

    sm = get_sessionmaker()
    async with sm() as session:
        await session.execute(text("SELECT 1"))

async def _register_bot_metadata() -> bool:
    """Команды и кнопка меню. Возвращает `True`, если команды встали.

    Результат важен вызывающему: раньше исключение проглатывалось, попытка
    считалась успешной, и при живом вебхуке цикл выходил из первой итерации —
    из-за этого в меню Telegram неделями висел старый список команд, хотя в
    каталоге уже были новые.
    """
    settings = get_settings()
    bot = get_bot()
    commands_ok = True
    # GHG6 K2-bis: список команд берём из единого каталога commands_catalog.py.
    # Описания в Telegram-menu и в /help теперь не расходятся.
    from app.bot.commands_catalog import bot_commands_for_scope

    private_cmds = [
        BotCommand(command=c.cmd, description=c.desc_ru)
        for c in bot_commands_for_scope("private")
    ]
    group_cmds = [
        BotCommand(command=c.cmd, description=c.desc_ru)
        for c in bot_commands_for_scope("group")
    ]
    try:
        # Устанавливаем команды с коротким таймаутом
        await bot.set_my_commands(
            private_cmds,
            scope=BotCommandScopeAllPrivateChats(),
            request_timeout=10,
        )
        await bot.set_my_commands(
            group_cmds,
            scope=BotCommandScopeAllGroupChats(),
            request_timeout=10,
        )
        # GHG7 P1.3: чтобы в нашем основном чате Telegram не дописывал
        # `@gunghogunsbot` к каждой команде в autocomplete, ставим
        # команды дополнительно прицельно на `group_chat_id` через
        # BotCommandScopeChat. У TG приоритет scope'ов: специфический
        # (Chat) перекрывает общий (AllGroupChats), и в этом конкретном
        # чате TG считает команды «однозначно нашими» — не клеит суффикс.
        # Для других group chat'ов (если бот когда-нибудь окажется в
        # ещё одной группе) остаётся AllGroupChats-fallback.
        if settings.group_chat_id:
            await bot.set_my_commands(
                group_cmds,
                scope=BotCommandScopeChat(chat_id=settings.group_chat_id),
                request_timeout=10,
            )
    except Exception as exc:  # noqa: BLE001
        commands_ok = False
        structlog.get_logger().warning("bot.set_commands_failed", error=str(exc))

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📋 Рабочий бот",
                web_app=WebAppInfo(url=settings.mini_app_url),
            ),
            request_timeout=10
        )
    except Exception as exc:  # noqa: BLE001
        structlog.get_logger().warning("bot.set_menu_button_failed", error=str(exc))

    return commands_ok


async def _set_webhook() -> None:
    """Поставить вебхук каждому боту, который мы обслуживаем.

    До шага 1.6 бот был один, и здесь стоял один вызов. Теперь у организации
    может быть свой токен: у каждого бота свой вебхук и СВОЙ секрет, по
    которому входящий апдейт находит организацию. Если секрет не задан, бот
    остаётся без вебхука и пишет предупреждение — иначе два бота делили бы
    один секрет, и апдейт уходил бы «первому совпавшему».
    """
    settings = get_settings()
    log = structlog.get_logger()
    if not settings.public_base_url:
        log.warning("webhook.skip_no_public_base_url")
        return
    url = f"{settings.public_base_url.rstrip('/')}/tg/webhook"

    from app.bot.dispatcher import bot_for_org
    from app.db.org_models import DEFAULT_ORG_ID
    from app.services import org_bots

    targets: list[tuple[int, str]] = []
    for cfg in org_bots.all_configs():
        if cfg.org_id == DEFAULT_ORG_ID:
            targets.append((cfg.org_id, cfg.webhook_secret or settings.tg_webhook_secret))
        elif cfg.own_bot:
            if not cfg.webhook_secret:
                log.warning("webhook.skip_no_secret", org=cfg.slug)
                continue
            targets.append((cfg.org_id, cfg.webhook_secret))
    if not targets:
        targets = [(DEFAULT_ORG_ID, settings.tg_webhook_secret)]

    failed: list[str] = []
    for org_id, secret in targets:
        try:
            await bot_for_org(org_id).set_webhook(
                url=url,
                secret_token=secret,
                # GHG7 P5: "message_reaction" нужен, чтобы детектировать живую
                # реакцию человека на медиа (режим wait_then_chance). Telegram
                # НЕ шлёт апдейтов, которых нет в списке — добавляем, не
                # заменяя существующие.
                allowed_updates=[
                    "message",
                    "callback_query",
                    "poll_answer",
                    "message_reaction",
                ],
                drop_pending_updates=False,
                request_timeout=20,
            )
        except Exception as exc:  # noqa: BLE001 — один бот не должен ронять остальных
            failed.append(f"{org_id}: {exc}")
            log.warning("webhook.set_failed", org_id=org_id, error=str(exc))
        else:
            log.info("webhook.set", url=url, org_id=org_id)
    if failed:
        # Пусть внешний retry повторит: чаще всего это сеть, а не токен.
        raise RuntimeError("webhook.set_failed: " + "; ".join(failed))


async def _register_telegram_metadata_with_retry() -> None:
    """Background task: set webhook + commands + menu button, retrying on
    transient network failures so a flaky HF egress doesn't permanently
    leave the bot unconfigured. Each attempt is wrapped in its own
    try/except so a single failure never bubbles up.
    """
    log = structlog.get_logger()
    backoff = 5
    for attempt in range(1, 7):  # ~5+10+20+40+80+160s ≈ 5min total
        webhook_ok = False
        metadata_ok = False
        try:
            await _set_webhook()
            webhook_ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("webhook.set_failed", attempt=attempt, error=str(exc))

        try:
            metadata_ok = await _register_bot_metadata()
        except Exception as exc:  # noqa: BLE001
            log.warning("bot.metadata_failed", attempt=attempt, error=str(exc))

        # Выходим, только когда получилось и то, и другое: иначе старый список
        # команд останется в меню до следующего перезапуска.
        if webhook_ok and metadata_ok:
            return
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 160)
    log.error("tg.registration_gave_up")

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)

    # 0. Проверка сертификата базы (аудит 26.10.2026, S-4). До первого обращения к
    # базе: если сертификат действительно невалиден, движок пересоздастся без
    # проверки и в логе будет громкая ошибка. Иначе — работаем с проверкой.
    try:
        from app.db.base import probe_ssl_verification

        await probe_ssl_verification()
    except Exception as exc:  # noqa: BLE001 — старт важнее диагностики
        structlog.get_logger().warning("db.ssl_probe_failed", error=str(exc))

    # 1. Сидинг пользователей (Локальная операция с БД)
    sm = get_sessionmaker()
    async with sm() as session:
        await seed_users(session)
        # SemiTaskBot: начальные подразделения/чек-листы/ссылки/вопросы ОС.
        # Идемпотентно (см. app/db/hr_seed.py): на боевой базе ничего не
        # перезапишет, только снимает «пустой экран» у нового ресторана.
        try:
            await seed_hr(session)
        except Exception as exc:  # noqa: BLE001 — сид не должен ронять старт
            structlog.get_logger().warning("hr.seed_failed", error=str(exc))
        # P2: bootstrap proxy pool из env (PROXIES_BOOTSTRAP_JSON), если задан.
        try:
            from app.services.proxies import bootstrap_from_env
            await bootstrap_from_env(session)
        except Exception as exc:  # noqa: BLE001
            structlog.get_logger().warning("proxy.bootstrap_failed", error=str(exc))

        # B2B_PLATFORM_PLAN, шаг 1.6: чей бот и чей чат. Реестр наполняется до
        # сетевых шагов — иначе первый вебхук или планировщик успел бы взять
        # env-бота организации по умолчанию.
        try:
            from app.services import org_bots

            count = await org_bots.reload(session)
            structlog.get_logger().info("orgs.bots_loaded", organizations=count)
        except Exception as exc:  # noqa: BLE001 — реестр не должен ронять старт
            structlog.get_logger().warning("orgs.bots_failed", error=str(exc))
        
        # РЕЗЕРВНЫЙ ШАГ: Синхронизация аватарок отключена для ускорения запуска
        # try:
        #     await sync_all_avatars(session, get_bot())
        # except Exception as exc:
        #     structlog.get_logger().warning("avatars.startup_sync_failed", error=str(exc))

    # 2. Сетевые операции (Telegram) уходят в фон с ретраями, чтобы лагающая
    # сеть HF не блокировала FastAPI startup и первый входящий webhook.
    tg_task = asyncio.create_task(_register_telegram_metadata_with_retry())

    # 3. GHG11(5): планировщик стартует НЕ безусловно, а через цикл лидерства.
    # Amvera и HF Space делят одну Neon, поэтому активный писатель ровно один:
    # job'ы поднимает только владелец лиза (`services/scheduler_leader.py`).
    # При `SCHEDULER_LEADER_DISABLED=true` поведение прежнее (каждый сам себе).
    arm_leader_gate()
    # ВАЖНО: `get_bot()` может бросить (невалидный/отсутствующий BOT_TOKEN на
    # вторичном хосте — так и есть на HF Space). Раньше это глоталось и хост
    # всё равно поднимал API; не даём тривиальной ошибке бота уронить lifespan
    # (смоук-инцидент 2026-10-05: HF Space ушёл в RUNTIME_ERROR/code 3).
    try:
        scheduler_task: asyncio.Task | None = asyncio.create_task(
            run_scheduler_leadership(get_bot())
        )
    except Exception as exc:  # noqa: BLE001
        scheduler_task = None
        structlog.get_logger().warning("scheduler.start_failed", error=str(exc))

    yield

    # Завершение: гасим фоновые задачи, если они ещё бегут.
    for _task in (tg_task,):
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    # Отпускаем лиз лидерства до общего shutdown — второй инстанс подхватит сразу.
    await release_scheduler_leadership()
    await shutdown_scheduler()
    # Апдейты, которые после ответа Telegram докручиваются в фоне (см.
    # `bot/webhook.py`), добираем до конца: мы уже сказали Telegram «ок», и
    # повторной доставки не будет — потерять работу на середине нельзя.
    try:
        from app.bot.webhook import wait_pending_tasks

        await wait_pending_tasks()
    except Exception:  # noqa: BLE001 — остановка не должна падать из-за дренажа
        structlog.get_logger().warning("webhook.drain_failed")
    try:
        from app.bot.dispatcher import all_bots

        # Ботов теперь столько, сколько организаций со своим токеном: закрыть
        # один значило бы оставить висящие соединения у остальных.
        for bot in all_bots():
            try:
                await bot.session.close()
            except Exception as exc:  # noqa: BLE001
                structlog.get_logger().warning("bot.close_failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — невалидный токен не должен ломать выход
        structlog.get_logger().warning("bot.close_failed", error=str(exc))

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SemiTaskBot", version="0.1.0", lifespan=lifespan)
    @app.middleware("http")
    async def tenant_scope(request, call_next):  # noqa: ANN001, ANN202 - FastAPI
        """Сбросить тенантский контекст после ответа.

        `current_employee` ставит организацию на время запроса. Без сброса
        значение утекло бы в следующий запрос, выполненный в той же задаче
        (в тестах это один и тот же event loop) — и человек из второй
        организации увидел бы данные первой.
        """
        token = set_org(DEFAULT_ORG_ID)
        auth_token = session_auth.set(False)
        try:
            return await call_next(request)
        finally:
            session_auth.reset(auth_token)
            reset_org(token)

    # Предохранители периметра (аудит 26.10.2026, находки S-1…S-3).
    #
    # Порядок важен и не случаен: `add_middleware` в Starlette вставляет каждое
    # следующее middleware НАРУЖУ, поэтому пишем их от внутреннего к внешнему.
    # Цепочка получается такая:
    #
    #   security headers → CORS → лимит частоты → лимит размера → маршруты
    #
    # Почему так: CORS должен быть снаружи лимитов, иначе браузер не прочтёт
    # `429` (ответ без CORS-заголовков выглядит для страницы сетевой ошибкой, и
    # человек вместо «слишком много попыток» увидит «что-то пошло не так»).
    # Лимит размера тела — внутри лимита частоты: отказанному запросу незачем
    # читать тело вообще.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Белый список, а не `*`: прод-проба 26.10.2026 показала, что с `*` и
        # `allow_credentials=True` Starlette отражает в ответ ЛЮБОЙ Origin
        # запроса (`access-control-allow-origin: https://evil.example`).
        allow_origins=settings.cors_allowed_origins,
        allow_origin_regex=settings.cors_origin_regex_or_none,
        allow_credentials=settings.cors_credentials_allowed,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.cors_allow_all and settings.cors_credentials_allowed:  # pragma: no cover - защита
        structlog.get_logger().warning("cors.wide_open_with_credentials")
    structlog.get_logger().info(
        "cors.configured",
        origins=settings.cors_allowed_origins,
        regex=bool(settings.cors_origin_regex_or_none),
        credentials=settings.cors_credentials_allowed,
    )
    app.include_router(bot_webhook.router)
    # Вход по почте: регистрация, вход, сессии, сброс (B2B_PLATFORM_PLAN, 2.1).
    app.include_router(routes_auth.router, prefix="/api")
    # Приглашения в организацию: ссылка с ролью и сроком (B2B_PLATFORM_PLAN, 2.2).
    app.include_router(routes_orgs.router, prefix="/api")
    # Push вне Telegram: подписка браузера и тестовое уведомление (2.4).
    app.include_router(routes_push.router, prefix="/api")
    app.include_router(routes_users.router, prefix="/api")
    # Вход в веб-версию по ссылке (вне Telegram, где нет initData).
    app.include_router(routes_app_access.router, prefix="/api")
    app.include_router(routes_availability.router, prefix="/api")
    app.include_router(routes_meetings.router, prefix="/api")
    app.include_router(routes_polls.router, prefix="/api")
    app.include_router(routes_birthdays.router, prefix="/api")
    app.include_router(routes_calendar.router, prefix="/api")
    # SemiTaskBot HR-ядро: ручки сотрудника и управляющий контур (АУП/админ).
    app.include_router(routes_hr.router, prefix="/api")
    # Фотоотчёты: загрузка снимка из мини-аппа и публичная выдача по подписи.
    # Отдельный роутер, потому что выдача работает без tma-заголовка (`<img>`).
    app.include_router(routes_media.router, prefix="/api")
    # Материалы смены: снимок Google Sheets из БД (устойчиво к блокировкам).
    app.include_router(routes_materials.router, prefix="/api")
    # Тексты интерфейса: правятся из админки, читаются без токена (это подписи).
    app.include_router(routes_texts.router, prefix="/api")
    # Журнал операционных проблем — отдельная сущность со своими правами.
    app.include_router(routes_issues.router, prefix="/api")
    # База стандартов и проверка знаний (сотрудник + наполнение АУП/админом).
    app.include_router(routes_standards.router, prefix="/api")
    app.include_router(routes_handovers.router, prefix="/api")
    # Табель смен: сотруднику — своё подразделение, управляющему — все.
    app.include_router(routes_shifts.router, prefix="/api")
    # Отчёты смены и стандартов для руководителя (+CSV).
    app.include_router(routes_reports.router, prefix="/api/admin")
    # Сброс текущей работы: предпросмотр + подтверждение словом.
    app.include_router(routes_reset.router, prefix="/api/admin")
    # Режим проверки: теневой профиль, вход/выход, чистая история.
    app.include_router(routes_simulation.router, prefix="/api/admin")
    app.include_router(routes_hr_admin.router, prefix="/api/admin")
    # Журнал событий, центр уведомлений и пул сотрудников (увольнение/корзина).
    app.include_router(routes_hr_ops_admin.router, prefix="/api/admin")
    # Расписание обучения новичков: учебные/обычные смены и ставка.
    app.include_router(routes_hr_training_plan.router, prefix="/api/admin")
    app.include_router(routes_admin.router, prefix="/api")
    # GHG10-ops: `/api/meta` — паспорт контейнера (отпечаток кода, БД, какие
    # возможности есть). Регистрируется последним, поэтому его собственный
    # роут уже попал в отпечаток — хеш получается устойчивым.
    app.include_router(routes_meta.router, prefix="/api")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Живой ли процесс. Ничего не проверяет — для этого есть `/readyz`.

        Разделение намеренное: оркестратор по `/healthz` решает, перезапускать
        ли контейнер (упавший процесс — да, упавшая база — нет), а по `/readyz`
        — пускать ли в него трафик.
        """
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Готов ли контейнер работать: отвечает ли база.

        Зачем (аудит 26.10.2026, S-5): `/healthz` возвращал `ok` без единого
        обращения к БД, поэтому оркестратор и наши скрипты выкладки считали
        контейнер здоровым, пока все ручки отдавали 500. Здесь один дешёвый
        `SELECT 1` с коротким сроком: недоступная база — честный `503` с
        причиной, а не «ок».
        """
        started = time.monotonic()
        try:
            await asyncio.wait_for(_db_ping(), timeout=READY_DB_TIMEOUT_SECONDS)
        except (TimeoutError, asyncio.TimeoutError):
            structlog.get_logger().warning("readyz.db_timeout")
            return JSONResponse(
                {"status": "degraded", "db": "timeout"}, status_code=503
            )
        except Exception as exc:  # noqa: BLE001 — любая причина недоступности
            structlog.get_logger().warning("readyz.db_failed", error=str(exc))
            return JSONResponse(
                {
                    "status": "degraded",
                    "db": "error",
                    "reason": type(exc).__name__,
                },
                status_code=503,
            )
        return JSONResponse(
            {
                "status": "ok",
                "db": "ok",
                "ms": round((time.monotonic() - started) * 1000, 1),
            }
        )

    return app

app = create_app()