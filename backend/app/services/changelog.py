"""История изменений для чат-команды `/changelog`.

Что делает. Забирает последние коммиты из GitHub и показывает их так, чтобы
человек без контекста разработки понял, что поменялось.

Главное правило (раунд 5): технический текст коммита не показывается никогда.
Каждое сообщение проходит адаптацию в два шага:

1. **Редакторская запись** (`app/content/changelog.py`): человек один раз
   переписал изменение обычными словами и указал хеши. Это лучший вариант —
   рядом с фактом есть объяснение «как это работает».
2. **Автоматическая расшифровка** этой функции: убираем тип и scope
   (`fix(ui):` → ничего), меняем жаргон на бытовые слова, собираем короткую
   фразу. Такая строка честно помечена как автоматическая.

Коммиты про тесты, документацию и обслуживание в историю не попадают вовсе:
они не меняют то, чем пользуется сотрудник. Вместо них — одна нейтральная
строка «внутренние улучшения».

Сеть не обязательна: если GitHub недоступен (а он в России бывает недоступен),
берём только редакторские записи и говорим об этом прямо, а не показываем
пустой экран.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import httpx
import structlog

from app.config import get_settings
from app.content import changelog as editorial

log = structlog.get_logger()

DEFAULT_REPO = "kickmesc-dotcom/meetup-planner"
CACHE_TTL_SECONDS = 600
FETCH_TIMEOUT_SECONDS = 6.0
MAX_ENTRIES = 6
MAX_AUTO_ITEMS = 4
# Насколько назад смотрим за автоматическими расшифровками (дни от последней
# редакторской записи). Всё, что старше, — либо уже описано, либо не новость.
AUTO_WINDOW_DAYS = 3

# Виды коммитов, которые не меняют продукт для сотрудника.
INTERNAL_TYPES = {
    "docs",
    "doc",
    "test",
    "tests",
    "chore",
    "ci",
    "build",
    "merge",
    "revert",
}

TYPE_VERB: dict[str, str] = {
    "feat": "Добавили",
    "feature": "Добавили",
    "fix": "Исправили",
    "hotfix": "Срочно исправили",
    "perf": "Ускорили",
    "refactor": "Переделали внутри",
    "style": "Поправили внешний вид",
    "ux": "Упростили работу с экраном",
}

# Scope коммита → «где именно». Формулировка подставляется в начало фразы,
# поэтому она уже стоит в нужном падеже: «В табеле: шаблоны недели».
AREA_LABEL: dict[str, str] = {
    "ui": "В интерфейсе",
    "hr": "В смене и задачах",
    "shifts": "В табеле",
    "feed": "В ленте событий",
    "admin": "В админке",
    "nav": "В навигации",
    "media": "В работе с фото",
    "auth": "Во входе в приложение",
    "db": "В хранении данных",
    "deploy": "На сервере",
    "changelog": "В истории изменений",
    "bot": "В боте",
}

# Пометка в конце строки: сотрудник сразу видит, это новая возможность или
# исправление уже знакомого экрана.
KIND_SUFFIX: dict[str, str] = {
    "fix": " (исправление)",
    "hotfix": " (срочное исправление)",
    "perf": " (работает быстрее)",
    "refactor": " (снаружи без изменений)",
    "style": " (внешний вид)",
}

# Технические слова → бытовые. Порядок важен: длинные раньше коротких.
JARGON: tuple[tuple[str, str], ...] = (
    (r"\bUI\b", "интерфейс"),
    (r"\bUX\b", "удобство"),
    (r"\bAPI\b", "сервер"),
    (r"\bCI\b", "автосборка"),
    (r"\bCDN\b", "быстрый кэш"),
    (r"\bURL\b", "адрес"),
    (r"\bJSON\b", "данные"),
    (r"\bSQL\b", "база данных"),
    (r"\bMVP\b", "первая версия"),
    (r"\bQS\b", "проверка"),
    (r"рефакторинг\w*", "внутренняя чистка кода"),
    (r"миграци\w*", "обновление базы"),
    (r"деплой\w*", "публикация"),
    (r"эндпоинт\w*", "серверная ручка"),
    (r"бэкенд\w*", "сервер"),
    (r"фронтенд\w*", "интерфейс"),
    (r"баг\w*", "ошибка"),
    (r"фикс\w*", "исправление"),
    (r"локаль\w*", "язык интерфейса"),
    (r"хардкод\w*", "жёстко прописанное значение"),
    (r"регрес\w*", "повторная ошибка"),
)

_PREFIX_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?!?:\s*")

# Внутренние коды работ («P3», «аудит», «ТЗ») сотруднику ничего не говорят.
# Такие коммиты считаем обслуживанием: они попадают в строку «внутренние
# улучшения», а не в историю продукта.
PROCESS_JARGON = re.compile(
    r"\b[PР][0-3](?:\.\d+)?\b|аудит|\bТЗ\b|\bMVP\b|P1\.[0-9]|паритет|легаси|"
    r"\btailwind\b|\bvite\b|\breact\b|\btypescript\b|\beslint\b|бандл",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Commit:
    """Коммит как его отдаёт GitHub (плюс разобранная первая строка)."""

    sha: str
    at: datetime | None
    raw: str
    url: str

    @property
    def short(self) -> str:
        return self.sha[:7]

    @property
    def day(self) -> date | None:
        return self.at.date() if self.at is not None else None


@dataclass(frozen=True)
class EntryView:
    """Готовая строка истории: заголовок + объяснение."""

    day: date
    title: str
    body: str
    # `True` — текст собран автоматически, `False` — редакторская запись.
    automatic: bool = False


@dataclass
class Changelog:
    entries: list[EntryView] = field(default_factory=list)
    internal_count: int = 0
    repo_url: str = f"https://github.com/{DEFAULT_REPO}/commits/main"
    source_ok: bool = False


def repo_slug() -> str:
    """Репозиторий из настроек (можно переопределить без правки кода)."""
    raw = getattr(get_settings(), "github_repo", "") or DEFAULT_REPO
    return raw.strip().strip("/") or DEFAULT_REPO


def _jargon(text: str) -> str:
    out = text
    for pattern, replacement in JARGON:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    # Код в обратных кавычках и пути файлов в историю не пускаем: это шум.
    out = re.sub(r"`([^`]*)`", r"\1", out)
    out = re.sub(r"\b[\w./-]+\.(py|tsx?|js|md|json|ya?ml)\b", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" .:-—")


def adapt_message(raw: str) -> str | None:
    """Первая строка коммита → человеческая фраза (None — не для сотрудника).

    Возвращает готовое предложение без markdown и кода. Технический текст не
    просачивается: тип и scope срезаются, жаргон переводится, пути файлов
    выкидываются.
    """
    first = (raw or "").strip().splitlines()[0].strip() if raw else ""
    if not first:
        return None

    match = _PREFIX_RE.match(first)
    kind = ""
    scope = ""
    rest = first
    if match is not None:
        kind = match.group("type").lower()
        scope = (match.group("scope") or "").lower()
        rest = first[match.end() :].strip()
        if kind in INTERNAL_TYPES:
            return None
    # «Закрыть P3 визуального аудита» — это внутренняя кухня, а не новость.
    if PROCESS_JARGON.search(rest):
        return None

    body = _jargon(rest)
    if not body:
        return None
    if len(body) > 160:
        body = body[:157].rstrip(" ,;:") + "…"

    verb = TYPE_VERB.get(kind, "")
    area = AREA_LABEL.get(scope, "")
    suffix = KIND_SUFFIX.get(kind, "")
    sentence = body[0].upper() + body[1:] if body else ""
    if area:
        # «В табеле: шаблоны недели (исправление)» — так фраза читается без
        # знания того, что такое commit type.
        return f"{area}: {sentence}{suffix}"
    if verb:
        phrase = f"{verb} {sentence[0].lower() + sentence[1:]}" if sentence else verb
        return f"{phrase}{suffix}"
    return f"{sentence}{suffix}"


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------

_cache: tuple[float, list[Commit]] | None = None


def parse_commits(payload: list[dict[str, object]], repo: str) -> list[Commit]:
    """Ответ GitHub API → список коммитов (чистая функция, без сети)."""
    out: list[Commit] = []
    for item in payload:
        sha = str(item.get("sha") or "")
        if not sha:
            continue
        commit = item.get("commit") or {}
        message = str(commit.get("message") or "")  # type: ignore[union-attr]
        when_raw = str(commit.get("committer", {}).get("date") or "")  # type: ignore[union-attr]
        when: datetime | None = None
        if when_raw:
            try:
                when = datetime.fromisoformat(when_raw.replace("Z", "+00:00"))
            except ValueError:
                when = None
        out.append(
            Commit(
                sha=sha,
                at=when,
                raw=message,
                url=f"https://github.com/{repo}/commit/{sha}",
            )
        )
    return out


async def fetch_commits(limit: int = 20, *, use_cache: bool = True) -> list[Commit]:
    """Последние коммиты из GitHub. Любая ошибка — пустой список, без падения."""
    global _cache
    now = time.monotonic()
    if use_cache and _cache is not None and now - _cache[0] < CACHE_TTL_SECONDS:
        return _cache[1][:limit]

    repo = repo_slug()
    token = getattr(get_settings(), "github_token", "") or ""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "SemiWorkBot-changelog",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"https://api.github.com/repos/{repo}/commits",
                params={"per_page": max(1, min(limit, 50))},
                headers=headers,
            )
        if response.status_code >= 400:
            log.warning("changelog.github_status", status=response.status_code)
            return _cache[1][:limit] if _cache is not None else []
        commits = parse_commits(response.json(), repo)
    except Exception as exc:  # сеть, DNS, таймаут — история не должна падать
        log.warning("changelog.github_failed", error=str(exc))
        return _cache[1][:limit] if _cache is not None else []

    _cache = (now, commits)
    return commits[:limit]


# --------------------------------------------------------------------------
# Сборка и рендер
# --------------------------------------------------------------------------


def build_view(
    commits: list[Commit], *, source_ok: bool, today: date | None = None
) -> Changelog:
    """Складывает редакторские записи и автоматические расшифровки.

    Редакторские записи показываем всегда (они живут в коде), даже если GitHub
    недоступен: история не должна зависеть от доступности api.github.com.
    """
    repo = repo_slug()
    result = Changelog(
        repo_url=f"https://github.com/{repo}/commits/main",
        source_ok=source_ok,
    )

    covered = editorial.covered_shas()
    seen: set[str] = set()
    for entry in editorial.ENTRIES:
        if entry.commits:
            key = entry.commits[0][:7]
            if key in seen:
                continue
            seen.add(key)
        result.entries.append(
            EntryView(day=entry.day, title=entry.title, body=entry.body)
        )
        if len(result.entries) >= MAX_ENTRIES:
            break

    # Автоматические строки — только про текущий релиз. Старые коммиты без
    # редакторской записи в историю не лезут: иначе хвост списка снова
    # превращается в «git log», от которого мы уходили.
    newest_editorial = max((entry.day for entry in editorial.ENTRIES), default=None)
    window_start = (
        newest_editorial - timedelta(days=AUTO_WINDOW_DAYS)
        if newest_editorial is not None
        else None
    )

    auto: list[EntryView] = []
    for commit in commits:
        if commit.short in covered:
            continue
        text = adapt_message(commit.raw)
        if text is None:
            result.internal_count += 1
            continue
        day = commit.day or today or date.today()
        if window_start is not None and day < window_start:
            result.internal_count += 1
            continue
        auto.append(EntryView(day=day, title=text, body="", automatic=True))

    # Автоматических строк — не больше четырёх: история не должна превращаться
    # в список коммитов, ради этого всё и затевалось.
    result.entries.extend(auto[:MAX_AUTO_ITEMS])
    result.internal_count += max(0, len(auto) - MAX_AUTO_ITEMS)
    result.entries.sort(key=lambda item: item.day, reverse=True)
    return result


async def build_changelog(limit_commits: int = 20) -> Changelog:
    commits = await fetch_commits(limit_commits)
    return build_view(commits, source_ok=bool(commits))


MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def human_day(day: date) -> str:
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"


def render_changelog(view: Changelog, *, max_chars: int = 3600) -> str:
    """Готовый HTML для Telegram. Ничего технического, только бытовые слова."""
    lines: list[str] = ["🧩 <b>Что нового</b>", ""]
    if not view.entries:
        lines.append("Пока без изменений — только сели за работу.")
        return "\n".join(lines)

    current_day: date | None = None
    for item in view.entries:
        if item.day != current_day:
            if current_day is not None:
                lines.append("")
            lines.append(f"🗓 <b>{human_day(item.day)}</b>")
            current_day = item.day
        title = html.escape(item.title)
        if item.automatic:
            lines.append(f"• {title} <i>(сводка из коммита)</i>")
        else:
            lines.append(f"• <b>{title}</b>")
            if item.body:
                lines.append(f"  {html.escape(item.body)}")

        if len("\n".join(lines)) > max_chars:
            lines.append("")
            lines.append("…и ещё немного — всё в истории на GitHub.")
            break

    if view.internal_count:
        lines.append("")
        lines.append(
            "🛠 Плюс внутренние улучшения: "
            f"{view.internal_count} — тесты, документация и обслуживание. "
            "На работу сотрудника они не влияют."
        )

    lines.append("")
    lines.append(f'🔗 <a href="{view.repo_url}">История коммитов на GitHub</a>')
    if not view.source_ok:
        lines.append(
            "<i>GitHub сейчас недоступен — показали то, что уже описано вручную.</i>"
        )
    return "\n".join(lines)
