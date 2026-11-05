// @vitest-environment jsdom
/**
 * Очередь отметок чек-листа.
 *
 * Проверяем обещания, из-за которых очередь вообще существует:
 *  - отметка переживает отсутствие связи и не дублируется при повторном тапе;
 *  - повторяем только сетевые ошибки, отказ сервера по существу снимаем;
 *  - при обрыве проход останавливается, а не молотит остальные записи;
 *  - снимок чек-листа читается без сети.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import {
  MAX_QUEUE,
  enqueueCompletion,
  flushCompletions,
  isRetryable,
  loadChecklistSnapshot,
  pendingCompletions,
  pendingCount,
  saveChecklistSnapshot,
  type QueuedCompletion,
} from "./checklistQueue";
import type { HrChecklist } from "@/api/hr";

const entry = (patch: Partial<QueuedCompletion> = {}): Omit<QueuedCompletion, "queued_at"> => ({
  item_id: 10,
  kind: "shift",
  shift_date: "2026-11-05",
  note: null,
  media_id: null,
  photo_file_id: null,
  ...patch,
});

beforeEach(() => {
  localStorage.clear();
});

describe("isRetryable", () => {
  it("повторяет обрыв и 5xx, не повторяет 4xx", () => {
    expect(isRetryable(new TypeError("Failed to fetch"))).toBe(true);
    expect(isRetryable(new ApiError(503, "unavailable"))).toBe(true);
    expect(isRetryable(new ApiError(429, "rate_limited:10"))).toBe(true);
    expect(isRetryable(new ApiError(400, "photo_required"))).toBe(false);
    expect(isRetryable(new ApiError(403, "forbidden"))).toBe(false);
  });
});

describe("очередь", () => {
  it("не дублирует повторный тап по тому же пункту", () => {
    enqueueCompletion(entry());
    enqueueCompletion(entry({ note: "поправил" }));

    expect(pendingCount()).toBe(1);
    expect(pendingCompletions()[0].note).toBe("поправил");
  });

  it("различает пункты и даты смены", () => {
    enqueueCompletion(entry());
    enqueueCompletion(entry({ item_id: 11 }));
    enqueueCompletion(entry({ shift_date: "2026-11-04" }));

    expect(pendingCount()).toBe(3);
  });

  it("отправляет всё и чистит очередь", async () => {
    enqueueCompletion(entry());
    enqueueCompletion(entry({ item_id: 11 }));
    const send = vi.fn().mockResolvedValue(undefined);

    const result = await flushCompletions(send);

    expect(result).toEqual({ sent: 2, left: 0, dropped: 0 });
    expect(send).toHaveBeenCalledTimes(2);
    expect(pendingCount()).toBe(0);
  });

  it("при обрыве оставляет запись и не трогает следующие", async () => {
    enqueueCompletion(entry());
    enqueueCompletion(entry({ item_id: 11 }));
    const send = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const result = await flushCompletions(send);

    expect(result).toEqual({ sent: 0, left: 2, dropped: 0 });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("снимает запись, которую сервер отклонил по существу", async () => {
    enqueueCompletion(entry());
    const send = vi
      .fn()
      .mockRejectedValue(new ApiError(400, "already_done"));

    const result = await flushCompletions(send);

    expect(result).toEqual({ sent: 0, left: 0, dropped: 1 });
  });

  it("не даёт очереди расти бесконечно", () => {
    for (let i = 0; i < MAX_QUEUE + 5; i += 1) {
      enqueueCompletion(entry({ item_id: i }));
    }
    expect(pendingCount()).toBe(MAX_QUEUE);
    // Держим свежие: старые отметки уже вряд ли актуальны.
    expect(pendingCompletions().at(-1)?.item_id).toBe(MAX_QUEUE + 4);
  });
});

describe("снимок чек-листа", () => {
  it("сохраняется и читается без сети", () => {
    const view: HrChecklist = {
      run_id: 1,
      template_id: 2,
      template_title: "Открытие",
      kind: "shift",
      shift_date: "2026-11-05",
      status: "in_progress",
      done: 1,
      total: 2,
      progress_text: "Выполнено 1 из 2",
      items: [],
    };
    saveChecklistSnapshot("shift", view);

    expect(loadChecklistSnapshot("shift")).toEqual(view);
    expect(loadChecklistSnapshot("close")).toBeNull();
  });
});
