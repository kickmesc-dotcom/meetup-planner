"""Инварианты доступа: админ-ручки и список публичных маршрутов (S-9).

Зачем тест такого рода. Права у нас проверяются двумя способами: зависимостью
FastAPI (`AdminDep`, `AupDep`) и вызовом внутри тела (`hr_access.is_aup`,
`_ensure_admin`). Второе — дисциплина, а дисциплина ломается на 145 маршрутах:
одна забытая строка в новом обработчике, и ручка открыта всему интернету, причём
ни один существующий тест этого не заметит, если он про другое.

Тест держит два инварианта:

1. **Каждый** маршрут под `/api/admin` имеет зависимость авторизации и в своём
   коде видимую проверку прав (или явно перечислен ниже — тогда причина
   written down рядом).
2. Список маршрутов, доступных БЕЗ авторизации, зафиксирован. Новая публичная
   ручка не «тихо появится», а сломает тест — и человек решит осознанно: это
   действительно публичная ручка (телефонный вход, подписанная ссылка) или
   забытая проверка.
"""

from __future__ import annotations

import inspect
import os
import re

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_invariants.db")

import pytest  # noqa: E402

from app.main import create_app  # noqa: E402
from app.routing import iter_route_objects  # noqa: E402

# Зависимости, которыми пользуется код для авторизации.
AUTH_DEPENDENCIES = {
    "current_user",
    "current_employee",
    "require_aup",
    "require_admin",
    "current_org",
}

# Маршруты без авторизации. Каждый — осознанное решение, а не «так получилось».
PUBLIC_ROUTES: dict[str, str] = {
    "POST /api/auth/register": "регистрация по почте: иначе войти неоткуда",
    "POST /api/auth/login": "вход по почте",
    "POST /api/auth/logout": "выход по своему токену: токен и есть доказательство",
    "POST /api/auth/password/reset/request": "сброс пароля: письмо уходит на почту",
    "POST /api/auth/password/reset/confirm": "сброс пароля по ссылке из письма",
    "POST /api/auth/email/verify/confirm": "подтверждение адреса по ссылке из письма",
    "GET /api/invitations/{token}": "превью приглашения: ссылка и есть пропуск",
    "GET /api/meetings/ical/{user_id}.ics": "iCal-подписка: почтовые клиенты не умеют заголовки",
    "GET /api/avatar/{user_id}": "аватарка вставляется тегом <img>, заголовков он не умеет",
    "GET /api/media/{blob_id}": "байты фото по HMAC-подписи в URL (для <img>)",
    "GET /api/media/tg/{photo_id}": "то же для фото из чата, ещё не снятого в блоб",
    "GET /api/media/checklist/{completion_id}": "то же для фото пункта чек-листа",
    "GET /api/texts": "подписи интерфейса, не данные",
    "GET /api/meta": "паспорт контейнера: отпечаток кода и возможности, без секретов",
    "GET /api/meta/net": "диагностика сети, доступ по секрету вебхука в заголовке",
    "POST /tg/webhook": "Telegram: организация определяется по секрету в заголовке",
}

# Проверки прав внутри тела. Список намеренно широкий: важно, чтобы проверка
# вообще была видна в исходнике обработчика.
RIGHTS_MARKERS = re.compile(
    "|".join(
        [
            "AdminDep",
            "AupDep",
            "RealEmployeeDep",
            "require_admin",
            "require_aup",
            "_ensure_admin",
            "ensure_admin",
            r"is_admin\(",
            r"is_aup\(",
            r"is_staff\(",
            "_diag_token_ok",
            "_game_gate",
        ]
    )
)

# Маршруты админки, где проверка живёт в сервисе, а не в обработчике.
# Формат: "МЕТОД путь" -> где именно проверяют.
ADMIN_CHECK_IN_SERVICE: dict[str, str] = {
    "POST /api/admin/standards": (
        "обработчик отдаёт работу в _create_standard, там hr_access.is_aup"
    ),
    "POST /api/admin/simulation": "hr_simulation.start проверяет право на проверку",
    "POST /api/admin/simulation/{session_id}/exit": "hr_simulation.finish сверяет владельца сеанса",
    "GET /api/admin/simulation/active": "сеанс виден только своему владельцу",
}


# Приложение собирается один раз на файл: `create_app()` поднимает все роутеры
# (больше трёхсот маршрутов), и вызов на каждый проверяемый маршрут превращал
# тест в минуты ожидания.
_APP = None


def _app():  # noqa: ANN202 - объект FastAPI
    global _APP
    if _APP is None:
        _APP = create_app()
    return _APP


def _routes() -> list[tuple[str, str, set[str], object]]:
    """(метод, путь, зависимости авторизации, endpoint) для всех маршрутов api/tg.

    Обход — через `app.routing.iter_route_objects`, а не по `app.routes`: в
    Starlette 1.x включённые роутеры больше не разворачиваются в плоский список,
    и прямой обход давал бы пустой набор — тест-инвариант «зеленел» бы ни на чём
    (аудит 26.10.2026, S-18).
    """
    out: list[tuple[str, str, set[str], object]] = []
    for route in iter_route_objects(_app()):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or not path.startswith(("/api", "/tg")):
            continue
        deps = _dependencies(route)
        for method in sorted(methods - {"HEAD"}):
            out.append((method, path, deps, getattr(route, "endpoint", None)))
    return out


def _dependencies(route) -> set[str]:  # noqa: ANN001 - объект Starlette
    dep = getattr(route, "dependant", None)
    return {
        getattr(d.call, "__name__", "") for d in (dep.dependencies if dep else [])
    } & AUTH_DEPENDENCIES


def test_every_admin_route_requires_authorization():
    """Под `/api/admin` нет ни одного маршрута без зависимости авторизации."""
    offenders: list[str] = sorted(
        {path for _, path, deps, _ in _routes() if path.startswith("/api/admin") and not deps}
    )
    assert offenders == [], ("админ-маршруты без авторизации: " + ", ".join(offenders))


def test_every_admin_route_shows_a_rights_check():
    """У каждого админ-обработчика проверка прав видна в коде или в сервисе."""
    unjustified: list[str] = []
    for method, path, _deps, endpoint in _routes():
        if not path.startswith("/api/admin") or endpoint is None:
            continue
        key = f"{method} {path}"
        try:
            source = inspect.getsource(endpoint)
        except (OSError, TypeError):  # pragma: no cover - экзотика сборки
            continue
        if RIGHTS_MARKERS.search(source):
            continue
        if key in ADMIN_CHECK_IN_SERVICE:
            continue
        unjustified.append(key)
    assert unjustified == [], (
        "эти админ-ручки без видимой проверки прав — либо добавь проверку, либо "
        "запиши в ADMIN_CHECK_IN_SERVICE, где она живёт: " + ", ".join(unjustified)
    )


def test_public_routes_are_exactly_the_frozen_list():
    """Новая публичная ручка обязана пройти через осознанное решение."""
    actual = {
        f"{method} {path}" for method, path, deps, _ in _routes() if not deps
    }
    known = set(PUBLIC_ROUTES)
    added = sorted(actual - known)
    removed = sorted(known - actual)
    assert added == [], (
        "появились маршруты без авторизации: "
        + ", ".join(added)
        + " — если это осознанно, опиши причину в PUBLIC_ROUTES этого теста"
    )
    assert removed == [], (
        "эти маршруты перестали быть публичными: " + ", ".join(removed)
    )


def test_public_routes_have_a_written_reason():
    """У каждой публичной ручки причина записана, а не оставлена пустой."""
    assert all(
        reason.strip() for reason in PUBLIC_ROUTES.values()
    ), "у публичной ручки должна быть причина"


def test_admin_routes_are_actually_present():
    """Страховка от «тест зелёный, потому что маршрутов не нашлось»."""
    admin = {p for _, p, _, _ in _routes() if p.startswith("/api/admin")}
    assert len(admin) > 100, f"админ-маршрутов подозрительно мало: {len(admin)}"


# --- адрес push-подписки (S-8) ---------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc123",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/QABC",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
    ],
)
def test_real_push_endpoints_are_allowed(endpoint: str):
    from app.services import web_push

    assert web_push.endpoint_is_allowed(endpoint) is True


@pytest.mark.parametrize(
    "endpoint",
    [
        # Внутренние адреса и метаданные облака — главная цель SSRF.
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/api/admin/dashboard",
        "https://10.111.85.131/",
        "https://[::1]/push",
        "https://evil.example/push",
        # Схема не https, порт не 443, логин в URL.
        "http://fcm.googleapis.com/send/abc",
        "https://fcm.googleapis.com:8443/send/abc",
        "https://user:pass@fcm.googleapis.com/send/abc",
        "",
        "fcm.googleapis.com/send/abc",
    ],
)
def test_dangerous_push_endpoints_are_rejected(endpoint: str):
    from app.services import web_push

    assert web_push.endpoint_is_allowed(endpoint) is False


def test_subscription_and_send_use_the_same_rule():
    """Правило одно на запись и на отправку: строки в базе могли быть старые."""
    from app.services import web_push

    source = inspect.getsource(web_push.send)
    assert "endpoint_is_allowed" in source


def _patch_routes(app, path: str) -> list:
    """Все объявления `PATCH <path>` — в порядке подключения роутеров."""
    return [
        route
        for route in iter_route_objects(app)
        if route.path == path and "PATCH" in (route.methods or ())
    ]


def test_no_route_is_declared_twice():
    """Один путь + один метод = один обработчик.

    Зачем это отдельный инвариант (аудит 27.10, S-21; закрыто 30.10). Starlette
    берёт первый обработчик по порядку подключения, а второй остаётся жить в
    коде и в схеме OpenAPI: он виден в документации, по нему пишут тесты, но
    запросы к нему не приходят. Так `PATCH /api/admin/employees/{id}` работал в
    админском варианте, а фронт ждал ответ и поля от ops-варианта —
    переименование сотрудника молча не применялось.

    Проверяем весь список маршрутов, а не конкретный путь: следующая такая пара
    появится не там, где её ждут.
    """
    import collections

    app = create_app()
    seen: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for route in iter_route_objects(app):
        for method in route.methods or ():
            seen[(method, route.path)].append(
                f"{route.endpoint.__module__}.{route.endpoint.__name__}"
            )

    duplicates = {key: names for key, names in seen.items() if len(names) > 1}
    assert duplicates == {}


def test_employee_patch_is_the_ops_handler_and_admin_only():
    """Правка сотрудника — один обработчик, карточка в ответе, права админа.

    Три свойства вместе, потому что порознь каждое уже было выполнено, пока
    баг жил: обработчик существовал, ответ был, права были — только у другого
    обработчика. Проверяем ровно тот набор, который видит фронт.
    """
    app = create_app()
    routes = _patch_routes(app, "/api/admin/employees/{employee_id}")

    assert len(routes) == 1, "на путь должен остаться ровно один обработчик"
    route = routes[0]
    assert route.endpoint.__module__ == "app.api.routes_hr_ops_admin"
    assert route.response_model is not None
    assert route.response_model.__name__ == "EmployeeCardOut"

    # Права не расширились при слиянии: путь и раньше фактически был админским.
    names = set()

    def collect(dependant) -> None:
        for dep in getattr(dependant, "dependencies", ()) or ():
            call = getattr(dep, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            collect(dep)

    collect(route.dependant)
    assert "require_admin" in names


def test_employee_patch_accepts_the_name_the_ui_sends():
    """Поле `display_name` — то самое, которое старый обработчик молча терял.

    Pydantic по умолчанию игнорирует лишние поля, поэтому несовпадение схемы с
    телом от фронта не даёт ни 422, ни 500 — только «сохранил, а имя прежнее».
    """
    from app.api import routes_hr_ops_admin

    body = routes_hr_ops_admin.EmployeePatchIn(display_name="Tasya", role="employee")
    assert body.display_name == "Tasya"
    assert body.role == "employee"


def test_every_endpoint_annotation_resolves():
    """Имена в аннотациях ручек обязаны существовать в модуле.

    Зачем (найдено 30.10 при подъёме pydantic, S-19). `routes_admin` объявлял
    поле `immunity_mode: Literal["announce", "silent"]`, не импортировав
    `Literal`. Со старым pydantic это проходило: модель строилась лениво и
    ошибка не всплывала. На 2.13 импорт приложения падал на сборке OpenAPI, а
    вместе с ним `/api/meta` терял список ручек — и проверки прав на этом списке
    переставали что-либо охранять.

    Тест не зависит от версии библиотеки: он спрашивает у Python, разрешаются
    ли аннотации, — то есть сработает и на следующем подъёме.
    """
    import typing

    app = create_app()
    broken: dict[str, str] = {}
    for route in iter_route_objects(app):
        try:
            typing.get_type_hints(route.endpoint)
        except NameError as exc:  # имя в аннотации не определено
            methods = ",".join(sorted(route.methods or ()))
            broken[f"{methods} {route.path}"] = str(exc)

    assert broken == {}
