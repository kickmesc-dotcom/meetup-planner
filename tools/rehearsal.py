"""Репетиция первого запуска: повторяемый прогон без боевой базы.

Зачем отдельная утилита. Пройти первый запуск один раз — легко, а найти в нём
проблемы можно только если проходить его снова и снова от лица разных людей:
новичка, который впервые видит приложение, и руководителя, который хочет
«видеть всё». Вручную это каждый раз означает «заведи новый аккаунт, создай
организацию, пригласи человека» — пять минут на прогон и постоянный риск
задеть настоящие данные.

Здесь этого риска нет: утилита работает с **отдельным файлом SQLite**, который
сама создаёт. Боевая база (`backend/.env`, Neon) не открывается вообще, а
`BOT_TOKEN` принудительно подменяется пустышкой: локальный прогон физически не
может отправить сообщение в Telegram.

Что делает (см. `--help`):

* `fresh` — новая база, руководитель с организацией, готовый к мастеру настройки;
* `new-staff` — ещё один «только что нанятый» аккаунт без организации
  (первый запуск сотрудника: вход → код компании → знакомство);
* `rerun` — вернуть человека в начало знакомства, не создавая новый аккаунт;
* `status` — что сейчас в базе: организация, участники, состояние онбординга.

Как этим пользоваться (два терминала):

    cd meetup-planner-main/backend
    DATABASE_URL=sqlite+aiosqlite:///./.rehearsal.db \\
      ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8010

    cd meetup-planner-main/frontend
    VITE_DEV_API_PROXY=http://127.0.0.1:8010 npm run dev

Перед запуском сервера — `python tools/rehearsal.py fresh`: он печатает логин,
пароль и код компании. Сценарий прогона и что именно проверять — в
`docs/FIRST_RUN_REHEARSAL.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
DEFAULT_DB = BACKEND / ".rehearsal.db"
DEFAULT_PASSWORD = "rehearsal-pass"
DEFAULT_ORG = "Кофейня «Репетиция»"


def _bootstrap(db: Path) -> None:
    """Окружение до импорта приложения: своя база и никакого Telegram.

    Переменные выставляются до `import app.*`, потому что настройки кешируются
    при первом чтении. `BOT_TOKEN` и `PUBLIC_BASE_URL` перекрываются осознанно:
    иначе локальный запуск взял бы токен из `.env` и попытался зарегистрировать
    вебхук на боевой бот.
    """
    db.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.resolve().as_posix()}"
    os.environ["BOT_TOKEN"] = "0:rehearsal-local"
    os.environ["TG_WEBHOOK_SECRET"] = "rehearsal-local"
    os.environ["PUBLIC_BASE_URL"] = ""
    os.environ["MINI_APP_URL"] = "http://localhost:5173"
    os.environ.setdefault("APP_PUBLIC_URL", "http://localhost:5173")
    # Письма в локальном прогоне никуда не уходят: транспорт «лог».
    os.environ["RESEND_API_KEY"] = ""
    os.environ["SMTP_HOST"] = ""
    sys.path.insert(0, str(BACKEND))


async def _sessionmaker(db: Path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"], future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _sqlite_jsonb_shim() -> None:
    """Научить SQLite рисовать `JSONB` как `JSON`.

    Модели используют `JSONB` (у него есть GIN-индексы на Postgres), а диалект
    SQLite такого типа не знает и падает на `create_all` с `CompileError`.
    Для репетиции достаточно колонки `JSON`: чтение и запись идут через тот же
    сериализатор, а специфичных для Postgres операторов (`->>`, `@>`) в коде
    нет. Шим ставится только здесь, в приложении его нет.
    """
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _jsonb_as_json(element, compiler, **kw) -> str:  # noqa: ANN001
        del element, compiler, kw
        return "JSON"


async def _ensure_schema(db: Path) -> None:
    """Схема из моделей + отметка head.

    `alembic upgrade head` на SQLite не проходит (миграция 0001 создаёт
    `JSONB`), а тесты собирают схему ровно так же — `create_all`. Отметку
    head ставим сами, чтобы `/api/meta` и `alembic current` не расходились.
    """
    from sqlalchemy import text

    import app.db.models  # noqa: F401  — регистрирует все таблицы
    from app.db.base import Base

    _sqlite_jsonb_shim()
    engine, _ = await _sessionmaker(db)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "create table if not exists alembic_version "
                "(version_num varchar(32) not null primary key)"
            )
        )
        head = _alembic_head()
        await conn.execute(text("delete from alembic_version"))
        if head is not None:
            await conn.execute(
                text("insert into alembic_version (version_num) values (:v)"),
                {"v": head},
            )
    await engine.dispose()


def _alembic_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _verified(user) -> None:
    """Почта подтверждена: иначе реальный человек ищет письмо, которого нет."""
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)


async def _create_person(session, *, email: str, name: str, password: str):
    from app.services import accounts

    user = await accounts.by_email(session, email)
    if user is None:
        user = await accounts.register(
            session, email=email, password=password, display_name=name
        )
    _verified(user)
    await session.commit()
    return user


async def fresh(db: Path, *, org_name: str, industry: str, keep: bool) -> dict[str, str]:
    """Новая база: руководитель уже с организацией, сотрудников ещё нет."""
    if not keep:
        for path in (db, Path(f"{db}-wal"), Path(f"{db}-shm")):
            path.unlink(missing_ok=True)
    await _ensure_schema(db)

    from app.services import accounts, orgs

    engine, make = await _sessionmaker(db)
    async with make() as session:
        # Организация по умолчанию нужна сиду бота при старте сервера: без неё
        # `seed_hr` пишет предупреждение. На репетицию она не влияет.
        await orgs.ensure_default(session)
        manager = await _create_person(
            session,
            email="manager@rehearsal.local",
            name="Руководитель Репетиция",
            password=DEFAULT_PASSWORD,
        )
        org = await orgs.by_slug(session, "rehearsal")
        if org is None:
            org = await orgs.create_with_owner(
                session,
                user=manager,
                name=org_name,
                industry=industry,
                slug="rehearsal",
            )
        # Мастер настройки — часть первого запуска, поэтому «чистый» прогон
        # начинается с него, а не с готовой организации.
        from app.db.org_models import set_org
        from app.services import org_setup

        set_org(org.id)
        await org_setup.save(
            session, org_setup.OrgSetup(done=False, industry=industry)
        )
    await engine.dispose()
    return {
        "db": str(db),
        "url": "http://localhost:5173",
        "org": f"{org.name} ({org.slug})",
        "code": org.slug,
        "manager": f"manager@rehearsal.local / {DEFAULT_PASSWORD}",
    }


async def new_staff(db: Path, *, alias: str) -> dict[str, str]:
    """Ещё один новый сотрудник: без организации, как после регистрации."""
    from app.services import accounts

    email = f"staff-{alias}@rehearsal.local"
    engine, make = await _sessionmaker(db)
    async with make() as session:
        await _create_person(session, email=email, name=f"Новичок {alias}", password=DEFAULT_PASSWORD)
    await engine.dispose()
    return {"staff": f"{email} / {DEFAULT_PASSWORD}"}


async def rerun(db: Path, *, email: str, cold: bool, org_setup_too: bool) -> dict[str, str]:
    """Вернуть человека к первому запуску, не создавая новый аккаунт."""
    from sqlalchemy import delete, select

    from app.db.auth_models import AuthSession
    from app.db.hr_models import ONBOARDING_NEW, Employee
    from app.db.org_models import OrgInvitation, OrganizationMember, set_org
    from app.db.tenancy import all_orgs
    from app.services import accounts, org_setup

    engine, make = await _sessionmaker(db)
    async with make() as session:
        user = await accounts.by_email(session, email)
        if user is None:
            raise SystemExit(f"нет такого аккаунта: {email}")

        with all_orgs():
            employee = await session.scalar(
                select(Employee).where(Employee.user_id == user.id)
            )
            if employee is not None:
                employee.onboarding_state = ONBOARDING_NEW
                employee.department_id = None
                employee.experience = None
                employee.learning_mode = True
                if org_setup_too:
                    # Настройка организации живёт под ключом текущего тенанта:
                    # без `set_org` сбросился бы мастер организации по умолчанию.
                    set_org(int(employee.org_id))
                    await org_setup.save(
                        session, org_setup.OrgSetup(done=False), commit=False
                    )
            if cold:
                # «Холодный» старт — как у человека без организации: экран
                # выбора роли, потом вход по коду. Рабочая история этого
                # человека остаётся: для полностью чистой базы есть `fresh`.
                await session.execute(
                    delete(OrganizationMember).where(
                        OrganizationMember.user_id == user.id
                    )
                )
                await session.execute(
                    delete(AuthSession).where(AuthSession.user_id == user.id)
                )
                await session.execute(
                    delete(OrgInvitation).where(
                        OrgInvitation.accepted_by_user_id == user.id
                    )
                )
            await session.commit()
    await engine.dispose()
    return {"rerun": email, "cold": "да" if cold else "нет"}


async def set_onboarding(db: Path, *, email: str, state: str) -> str:
    """Поставить состояние знакомства — чтобы проверить конкретный экран.

    Нужно для повторных проверок: не проходить три шага заново каждый раз,
    когда смотришь, например, только `training`.
    """
    from sqlalchemy import select

    from app.db.hr_models import ONBOARDING_STATES, Employee
    from app.db.tenancy import all_orgs
    from app.services import accounts

    if state not in ONBOARDING_STATES:
        raise SystemExit(f"неизвестное состояние: {state} (есть {ONBOARDING_STATES})")
    engine, make = await _sessionmaker(db)
    async with make() as session:
        user = await accounts.by_email(session, email)
        if user is None:
            raise SystemExit(f"нет такого аккаунта: {email}")
        with all_orgs():
            employee = await session.scalar(
                select(Employee).where(Employee.user_id == user.id)
            )
            if employee is None:
                raise SystemExit(f"у {email} ещё нет профиля: сначала открой приложение")
            employee.onboarding_state = state
            await session.commit()
    await engine.dispose()
    return f"{email}: {state}"


async def status(db: Path) -> str:
    from sqlalchemy import select

    from app.db.hr_models import Employee
    from app.db.org_models import Organization, OrganizationMember
    from app.db.tenancy import all_orgs
    from app.db.models import User

    if not db.exists():
        return f"базы нет: {db} — запусти `fresh`"
    engine, make = await _sessionmaker(db)
    lines: list[str] = []
    async with make() as session:
        with all_orgs():
            orgs_rows = (await session.scalars(select(Organization))).all()
            for org in orgs_rows:
                lines.append(f"организация #{org.id} {org.name} · код `{org.slug}`")
                members = (
                    await session.scalars(
                        select(OrganizationMember).where(
                            OrganizationMember.org_id == org.id
                        )
                    )
                ).all()
                for member in members:
                    user = await session.get(User, member.user_id)
                    email = user.email if user and user.email else "—"
                    emp = await session.scalar(
                        select(Employee).where(
                            Employee.user_id == member.user_id
                        )
                    )
                    state = (
                        f"онбординг: {emp.onboarding_state}"
                        if emp is not None
                        else "профиля нет"
                    )
                    lines.append(f"  · {email} — {member.role}, {state}")
            people = (
                await session.scalars(select(User).where(User.email.like("%rehearsal%")))
            ).all()
            if people:
                lines.append("аккаунты репетиции:")
                for user in people:
                    lines.append(f"  · {user.email}")
    await engine.dispose()
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Повторяемая репетиция первого запуска (отдельная SQLite-база).",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="файл базы")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fresh = sub.add_parser("fresh", help="новая база: руководитель с организацией")
    p_fresh.add_argument("--org", default=DEFAULT_ORG)
    p_fresh.add_argument("--industry", default="cafe")
    p_fresh.add_argument(
        "--keep",
        action="store_true",
        help="не удалять существующий файл (оставить историю прошлого прогона)",
    )

    p_staff = sub.add_parser("new-staff", help="ещё один новый сотрудник")
    p_staff.add_argument("--alias", default="1", help="номер прогона: staff-<alias>")

    p_rerun = sub.add_parser("rerun", help="вернуть человека к первому запуску")
    p_rerun.add_argument("email")
    p_rerun.add_argument(
        "--cold", action="store_true", help="ещё и выйти из организации (экран выбора роли)"
    )
    p_rerun.add_argument(
        "--org-setup",
        dest="org_setup_too",
        action="store_true",
        help="заодно сбросить мастер настройки организации (для руководителя)",
    )

    p_state = sub.add_parser("onboarding", help="поставить состояние знакомства")
    p_state.add_argument("email")
    p_state.add_argument("state")

    sub.add_parser("status", help="что сейчас в базе")

    args = parser.parse_args(argv)
    _bootstrap(args.db)

    if args.cmd == "fresh":
        result = asyncio.run(
            fresh(
                args.db,
                org_name=args.org,
                industry=args.industry,
                keep=args.keep,
            )
        )
        print("База готова:", result["db"])
        print("Приложение:  ", result["url"])
        print("Организация: ", result["org"])
        print("Код компании:", result["code"])
        print("Руководитель:", result["manager"])
        print()
        print("Дальше: добавь сотрудника —  python tools/rehearsal.py new-staff")
        print("Сценарий прогона — docs/FIRST_RUN_REHEARSAL.md")
        return 0
    if args.cmd == "new-staff":
        print(asyncio.run(new_staff(args.db, alias=args.alias))["staff"])
        return 0
    if args.cmd == "rerun":
        print(
            asyncio.run(
                rerun(
                    args.db,
                    email=args.email,
                    cold=args.cold,
                    org_setup_too=args.org_setup_too,
                )
            )
        )
        return 0
    if args.cmd == "onboarding":
        print(
            asyncio.run(
                set_onboarding(args.db, email=args.email, state=args.state)
            )
        )
        return 0
    if args.cmd == "status":
        print(asyncio.run(status(args.db)))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
