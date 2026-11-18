/**
 * Очередь отметок, переживающая потерю связи: задачи и проблемы.
 *
 * Зачем. Чек-лист уже умеет ждать сеть (`offline/checklistQueue`), но самая
 * частая отметка смены — «сделал поручение» — терялась: в подвале запрос падал,
 * карточка оставалась в работе, и человек либо бросал её, либо жал повторно.
 * То же со статусом проблемы: «в работе» не сохранялось.
 *
 * Политика конфликтов — три правила, и все они про доверие к серверу:
 *
 * 1. **Последнее действие по объекту выигрывает.** Ключ — `task:{id}` или
 *    `issue:{id}`. Нажал «принял», потом «готово» без сети — уйдёт только
 *    «готово»: промежуточный статус никому не нужен.
 * 2. **Сервер — источник истины.** Если он ответил 4xx (задачу уже закрыли,
 *    фото обязательно, нет прав), запись снимается с очереди. Держать её
 *    значит вечно показывать «не отправлено» там, где повтор не поможет.
 *    Такие записи считаются и показываются одним сообщением.
 * 3. **Сеть и 5xx — ждём.** Запись остаётся, отправка повторяется по событию
 *    `online` и при открытии экрана, без таймера: опрос будил бы радио зря.
 *
 * Почему `localStorage`, а не IndexedDB. Записей десятки, формат плоский, а
 * чтение синхронное — экран не мигает «загрузкой очереди». IndexedDB здесь
 * дала бы асинхронность без выгоды.
 */
import { ApiError } from "@/api/client";
import type { TaskAction } from "@/api/hr";
import type { IssueStatus } from "@/api/issues";

const QUEUE_KEY = "semitask.actions.queue.v1";

/** Больше 200 отметок не бывает: это значит, что связи нет неделю. */
export const MAX_QUEUE = 200;

export type QueuedAction =
  | {
      kind: "task";
      id: number;
      action: TaskAction;
      /** Подпись для сообщений: «Сдать работу» и т. п. */
      label?: string;
      queued_at: string;
    }
  | {
      kind: "issue";
      id: number;
      status: IssueStatus;
      comment?: string;
      label?: string;
      queued_at: string;
    }
  | {
      kind: "supply";
      id: number;
      /** Приход/списание; пересчёт офлайн не ставим — он требует точного факта. */
      movement: "in" | "out";
      quantity: number;
      comment?: string | null;
      queued_at: string;
    };

type NewAction = QueuedAction extends infer T
  ? T extends QueuedAction
    ? Omit<T, "queued_at">
    : never
  : never;

function actionKey(action: { kind: string; id: number }): string {
  return `${action.kind}:${action.id}`;
}

/**
 * Повторять ли запрос.
 *
 * Сеть, таймаут, 429 и 5xx — да. Прочие 4xx — нет: то же тело получит тот же
 * отказ, и очередь превратится в вечное «не отправлено». Логика совпадает с
 * очередью чек-листа намеренно: два разных правила в одном приложении путают.
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
  return true;
}

function readQueue(): QueuedAction[] {
  try {
    const raw = localStorage.getItem(QUEUE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is QueuedAction => {
      if (typeof item !== "object" || item === null) return false;
      const entry = item as Partial<QueuedAction>;
      return (
        (entry.kind === "task" ||
          entry.kind === "issue" ||
          entry.kind === "supply") &&
        typeof entry.id === "number"
      );
    });
  } catch {
    // Приватный режим или испорченный JSON: очередь — удобство, не данные.
    return [];
  }
}

function writeQueue(items: QueuedAction[]): void {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(items.slice(-MAX_QUEUE)));
  } catch {
    // Нет места/запрет storage — отметка не сохранится, но экран живёт.
  }
}

export function pendingActions(): QueuedAction[] {
  return readQueue();
}

export function pendingActionsCount(kind?: "task" | "issue" | "supply"): number {
  const queue = readQueue();
  return kind ? queue.filter((item) => item.kind === kind).length : queue.length;
}

/** Поставить отметку в очередь; повтор по тому же объекту заменяет прежнюю. */
export function enqueueAction(entry: NewAction): number {
  const queue = readQueue().filter((item) => actionKey(item) !== actionKey(entry));
  queue.push({ ...entry, queued_at: new Date().toISOString() } as QueuedAction);
  writeQueue(queue);
  return pendingActionsCount();
}

export function clearActionQueue(): void {
  try {
    localStorage.removeItem(QUEUE_KEY);
  } catch {
    // storage недоступен — чистить нечего.
  }
}

let running = false;

export interface FlushResult {
  sent: number;
  left: number;
  /** Сервер отказал по существу — записи сняты с очереди. */
  dropped: number;
}

/**
 * Отправить очередь по порядку.
 *
 * Порядок — время постановки: если человек принял задачу, а потом сдал, важна
 * именно эта последовательность. Сетевой обрыв останавливает проход: долбить
 * остальные записи тем же обрывом бессмысленно.
 */
export async function flushActions(
  send: (action: QueuedAction) => Promise<unknown>,
): Promise<FlushResult> {
  if (running) return { sent: 0, left: pendingActionsCount(), dropped: 0 };
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
      // Удаляем именно отправленную запись: за время запроса могли добавить
      // новую, и срез «первых N» её бы потерял.
      writeQueue(readQueue().filter((item) => actionKey(item) !== actionKey(entry)));
    }
    return { sent, left: pendingActionsCount(), dropped };
  } finally {
    running = false;
  }
}
