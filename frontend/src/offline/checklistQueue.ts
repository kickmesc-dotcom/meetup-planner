/**
 * Очередь отметок чек-листа, переживающая потерю связи.
 *
 * Зачем. На кухне и в подвале связи нет, а отметки — это работа смены: человек
 * нажимает «готово», видит галочку и идёт дальше. Сейчас без сети запрос падал,
 * галочка не появлялась, и к вечеру чек-лист был пустым — при том что работа
 * сделана. Хуже того, человек начинал тыкать повторно и не понимал, почему
 * ничего не происходит.
 *
 * Правила, которые здесь зафиксированы:
 *
 * 1. **Отметка не теряется.** Нет связи — запись уходит в `localStorage` и
 *    живёт там до успешной отправки или до отказа сервера по существу.
 * 2. **Повтор не плодит дублей.** Ключ — `(дата смены, пункт)`: повторное
 *    нажатие заменяет запись, а не добавляет вторую.
 * 3. **Отправка — по событию `online`, не по таймеру.** Опрос в фоне будил бы
 *    радио каждые N секунд без пользы, а событие приходит ровно тогда, когда
 *    связь появилась.
 * 4. **Дата смены едет с отметкой.** Утренняя отправка вечерней отметки должна
 *    попасть в свою смену, а не в сегодняшнюю (сервер это тоже проверяет).
 * 5. **Снимок для чтения.** Без сети экран показывает последний чек-лист —
 *    иначе человек не помнит, что там было, и не может отметить.
 */
import { ApiError } from "@/api/client";
import type { ChecklistKind, HrChecklist } from "@/api/hr";

const QUEUE_KEY = "semitask.checklist.queue.v1";
const SNAPSHOT_PREFIX = "semitask.checklist.snapshot.v1";

/** Больше 200 отметок в очереди не бывает: это значит, что связи нет неделю. */
export const MAX_QUEUE = 200;

export interface QueuedCompletion {
  item_id: number;
  kind: ChecklistKind;
  /** Дата смены в ISO (`2026-11-05`) — сервер по ней выберет прогон. */
  shift_date: string;
  note?: string | null;
  media_id?: number | null;
  photo_file_id?: string | null;
  queued_at: string;
}

/**
 * Имеет ли смысл повторять запрос.
 *
 * Сеть и 5xx — да: сервер или канал временно недоступны. 4xx — нет: повтор
 * того же тела получит тот же отказ (пункт уже закрыт, нет прав, шаблон
 * удалён), и держать такую запись в очереди значит показывать человеку
 * «не отправлено» вечно.
 */
export function isRetryable(error: unknown): boolean {
  if (error instanceof ApiError) {
    return (
      error.status === 0 ||
      error.status === 408 ||
      error.status === 429 ||
      error.status >= 500
    );
  }
  // TypeError от fetch («Failed to fetch»), обрыв, таймаут — это и есть
  // отсутствие связи.
  return true;
}

function readQueue(): QueuedCompletion[] {
  try {
    const raw = localStorage.getItem(QUEUE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is QueuedCompletion =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as QueuedCompletion).item_id === "number" &&
        typeof (item as QueuedCompletion).shift_date === "string",
    );
  } catch {
    // Приватный режим или испорченный JSON: очередь — удобство, а не данные.
    return [];
  }
}

function writeQueue(items: QueuedCompletion[]): void {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(items.slice(-MAX_QUEUE)));
  } catch {
    // Нет места/запрет storage — отметка уже не сохранится, но экран живёт.
  }
}

function entryKey(entry: QueuedCompletion): string {
  return `${entry.shift_date}:${entry.item_id}`;
}

export function pendingCompletions(): QueuedCompletion[] {
  return readQueue();
}

export function pendingCount(): number {
  return readQueue().length;
}

/**
 * Поставить отметку в очередь. Возвращает новую длину очереди.
 *
 * `queued_at` пишется здесь, а не вызывающим: по нему видно, сколько человек
 * ждал отправки, и это единственное поле, которое клиент не должен забыть.
 */
export function enqueueCompletion(
  entry: Omit<QueuedCompletion, "queued_at">,
): number {
  const queue = readQueue().filter((item) => entryKey(item) !== entryKey({ ...entry, queued_at: "" }));
  queue.push({ ...entry, queued_at: new Date().toISOString() });
  writeQueue(queue);
  return Math.min(queue.length, MAX_QUEUE);
}

// Одновременный flush из двух мест (открытие экрана и событие `online`)
// отправил бы одну и ту же отметку дважды.
let running = false;

export interface FlushResult {
  sent: number;
  left: number;
  /** Сервер отказал по существу — такие записи сняты с очереди. */
  dropped: number;
}

/**
 * Отправить очередь по порядку.
 *
 * Порядок важен: пункты чек-листа отмечаются последовательно, и сервер считает
 * прогресс по каждому. Первая сетевая ошибка останавливает проход — нет смысла
 * долбить остальные записи тем же обрывом.
 */
export async function flushCompletions(
  send: (entry: QueuedCompletion) => Promise<unknown>,
): Promise<FlushResult> {
  if (running) return { sent: 0, left: pendingCount(), dropped: 0 };
  running = true;
  let sent = 0;
  let dropped = 0;
  try {
    for (;;) {
      const queue = readQueue();
      const entry = queue[0];
      if (!entry) break;
      try {
        await send(entry);
        sent += 1;
      } catch (error) {
        if (isRetryable(error)) break;
        dropped += 1;
      }
      // Удаляем именно ту запись, которую отправили: за время запроса могли
      // добавить другую, и срез «первых N» её бы потерял.
      writeQueue(readQueue().filter((item) => entryKey(item) !== entryKey(entry)));
    }
    return { sent, left: pendingCount(), dropped };
  } finally {
    running = false;
  }
}

/** Сохранить последний чек-лист для чтения без сети. */
export function saveChecklistSnapshot(kind: ChecklistKind, data: HrChecklist): void {
  try {
    localStorage.setItem(`${SNAPSHOT_PREFIX}.${kind}`, JSON.stringify(data));
  } catch {
    // Размер или запрет storage: без снимка экран просто покажет ошибку сети.
  }
}

export function loadChecklistSnapshot(kind: ChecklistKind): HrChecklist | null {
  try {
    const raw = localStorage.getItem(`${SNAPSHOT_PREFIX}.${kind}`);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    return parsed as HrChecklist;
  } catch {
    return null;
  }
}
