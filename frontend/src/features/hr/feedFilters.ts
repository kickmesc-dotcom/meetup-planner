import type { FeedKind } from "@/api/hr";

/**
 * Фильтры ленты, которые переживают перезапуск.
 *
 * Зачем: руководитель каждый день смотрит одни и те же срезы — свой отдел,
 * «статус поручения + проблема». Выставлять это заново каждое утро — четыре
 * тапа, и половину времени человек смотрит на всю ленту, потому что забыл.
 *
 * Почему на сотрудника, а не на устройство: за одним телефоном могут заходить
 * разные люди, и чужие фильтры (по отделу, которого новый человек не видит)
 * привели бы к 403 на входе в ленту. Ключ поэтому тот же приём, что у отметки
 * «прочитано» (`feedSeen`).
 *
 * Поиск по имени не сохраняем: он разовый, и восстановленный запрос сузил бы
 * список людей до одного, выглядев как «пропали сотрудники».
 */

const STORAGE_PREFIX = "semitask.feed.filters.v1";

/** Известные типы событий: всё остальное из хранилища — мусор. */
const KINDS: readonly FeedKind[] = [
  "checklist_done",
  "checklist_item",
  "task_created",
  "task_status",
  "task_photo",
  "task_issue",
  "kudos",
];

const KIND_SET = new Set<string>(KINDS);

export interface FeedFilterState {
  employeeId: number | null;
  departmentId: number | null;
  kinds: FeedKind[];
}

const EMPTY: FeedFilterState = { employeeId: null, departmentId: null, kinds: [] };

function keyFor(employeeId: number): string {
  return `${STORAGE_PREFIX}:${employeeId}`;
}

/** Положительный целый id или null: отрицательные и строки — не адрес человека. */
function asId(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : null;
}

/** Список типов без дублей и без неизвестных значений. */
function asKinds(value: unknown): FeedKind[] {
  if (!Array.isArray(value)) return [];
  const out: FeedKind[] = [];
  for (const raw of value) {
    if (typeof raw !== "string" || !KIND_SET.has(raw)) continue;
    const kind = raw as FeedKind;
    if (!out.includes(kind)) out.push(kind);
  }
  return out;
}

/**
 * Сохранённый срез или пустой фильтр.
 *
 * Кривое хранилище — не повод падать: приватный режим, чужой формат,
 * устаревшая версия ключа дают пустой фильтр, то есть обычную ленту.
 */
export function readFeedFilters(employeeId: number): FeedFilterState {
  try {
    const raw = window.localStorage.getItem(keyFor(employeeId));
    if (!raw) return EMPTY;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return EMPTY;
    const data = parsed as Record<string, unknown>;
    return {
      employeeId: asId(data.employeeId),
      departmentId: asId(data.departmentId),
      kinds: asKinds(data.kinds),
    };
  } catch {
    return EMPTY;
  }
}

/**
 * Записать текущий срез. Пустой тоже пишем: после «Сбросить фильтры» старый
 * срез не должен воскреснуть при следующем открытии.
 */
export function saveFeedFilters(
  employeeId: number,
  state: FeedFilterState,
): void {
  try {
    window.localStorage.setItem(
      keyFor(employeeId),
      JSON.stringify({
        employeeId: asId(state.employeeId),
        departmentId: asId(state.departmentId),
        kinds: asKinds(state.kinds),
      }),
    );
  } catch {
    // Приватный режим/переполнение: фильтры просто не переживут перезапуск.
  }
}
