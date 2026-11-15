// @vitest-environment jsdom
/**
 * Очередь отметок вне сети (13.11.2026).
 *
 * Три правила, которые нельзя менять молча: последнее действие по объекту
 * выигрывает, 4xx снимает запись, сеть и 5xx её сохраняют.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import {
  MAX_QUEUE,
  clearActionQueue,
  enqueueAction,
  flushActions,
  isRetryable,
  pendingActions,
  pendingActionsCount,
} from "./actionQueue";

beforeEach(() => {
  clearActionQueue();
});

describe("actionQueue", () => {
  it("заменяет прежнее действие по тому же поручению", () => {
    enqueueAction({ kind: "task", id: 5, action: "accept" });
    enqueueAction({ kind: "task", id: 5, action: "done" });
    enqueueAction({ kind: "task", id: 6, action: "start" });

    const queue = pendingActions();
    expect(queue).toHaveLength(2);
    expect(queue[0]).toMatchObject({ kind: "task", id: 5, action: "done" });
    expect(queue[1]).toMatchObject({ kind: "task", id: 6, action: "start" });
  });

  it("не смешивает задачи и проблемы с одинаковым id", () => {
    enqueueAction({ kind: "task", id: 1, action: "done" });
    enqueueAction({ kind: "issue", id: 1, status: "in_progress" });
    expect(pendingActionsCount()).toBe(2);
    expect(pendingActionsCount("issue")).toBe(1);
  });

  it("сохраняет сеть и 5xx, снимает 4xx", async () => {
    enqueueAction({ kind: "task", id: 1, action: "done" });
    enqueueAction({ kind: "task", id: 2, action: "done" });
    enqueueAction({ kind: "issue", id: 3, status: "resolved" });

    const send = vi
      .fn()
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new ApiError(403, "forbidden"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const result = await flushActions(send);

    expect(result.sent).toBe(1);
    expect(result.dropped).toBe(1);
    // Сеть остановила проход: третья запись осталась, а не потерялась.
    expect(result.left).toBe(1);
    expect(pendingActions()[0]).toMatchObject({ kind: "issue", id: 3 });
  });

  it("останавливается на сетевой ошибке, а не долбит остаток", async () => {
    enqueueAction({ kind: "task", id: 1, action: "done" });
    enqueueAction({ kind: "task", id: 2, action: "done" });
    const send = vi.fn().mockRejectedValue(new TypeError("Load failed"));

    const result = await flushActions(send);

    expect(send).toHaveBeenCalledTimes(1);
    expect(result.left).toBe(2);
  });

  it("классифицирует повторы", () => {
    expect(isRetryable(new TypeError("Failed to fetch"))).toBe(true);
    expect(isRetryable(new ApiError(503, "unavailable"))).toBe(true);
    expect(isRetryable(new ApiError(429, "rate_limited:5"))).toBe(true);
    expect(isRetryable(new ApiError(400, "task_status_conflict"))).toBe(false);
  });

  it("не растёт бесконечно", () => {
    for (let i = 0; i < MAX_QUEUE + 5; i += 1) {
      enqueueAction({ kind: "task", id: i, action: "done" });
    }
    expect(pendingActionsCount()).toBe(MAX_QUEUE);
    // Обрезаются самые старые, свежие отметки остаются.
    expect(pendingActions().at(-1)?.id).toBe(MAX_QUEUE + 4);
  });
});
