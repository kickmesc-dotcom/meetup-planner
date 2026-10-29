// @vitest-environment jsdom
/**
 * Быстрый старт: ответ одной ручки раскладывается по кешу обычных ключей.
 *
 * Проверяем именно раскладку, а не сам запрос: выигрыш появляется только если
 * после bootstrap экраны находят данные под СВОИМИ ключами и не идут в сеть
 * второй раз. Ошибка «положили под `["tasks"]` вместо `["hr-tasks", false]`»
 * выглядит как работающий старт и шесть повторных запросов сразу после него.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({ api: vi.fn() }));

import { api } from "./client";
import { seedBootstrap, useBootstrap, type Bootstrap } from "./bootstrap";

const mockedApi = vi.mocked(api);

function payload(overrides: Partial<Bootstrap> = {}): Bootstrap {
  return {
    me: { id: 1, display_name: "Сергей" },
    users: [{ id: 1, display_name: "Сергей" }],
    employee: { id: 7, role: "admin" },
    tasks: [{ id: 3, title: "Открыть смену" }],
    org_setup: { done: true, uz_pack: true },
    ui_prefs: { hide_greeting: false, welcome_format: "name" },
    ...overrides,
  } as unknown as Bootstrap;
}

function freshClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 60_000 } },
  });
}

describe("seedBootstrap", () => {
  it("клаёт каждый кусок под ключ своей ручки", () => {
    const qc = freshClient();
    seedBootstrap(qc, payload());

    expect(qc.getQueryData(["me"])).toMatchObject({ display_name: "Сергей" });
    expect(qc.getQueryData(["users"])).toHaveLength(1);
    expect(qc.getQueryData(["hr-employee"])).toMatchObject({ id: 7 });
    // Ключ поручений на фронте составной: без `false` он бы не нашёлся.
    expect(qc.getQueryData(["hr-tasks", false])).toHaveLength(1);
    expect(qc.getQueryData(["org-setup"])).toMatchObject({ uz_pack: true });
    expect(qc.getQueryData(["ui-prefs"])).toMatchObject({ welcome_format: "name" });
  });

  it("не подкладывает пустоту вместо «ещё не загружено»", () => {
    const qc = freshClient();
    seedBootstrap(
      qc,
      payload({ employee: null, tasks: null, org_setup: null, ui_prefs: null }),
    );

    // Пустой список поручений означал бы «у тебя ничего нет» и отменил бы
    // скелетон — экран соврал бы, а данные пришли бы только по кнопке.
    expect(qc.getQueryData(["hr-tasks", false])).toBeUndefined();
    expect(qc.getQueryData(["hr-employee"])).toBeUndefined();
    expect(qc.getQueryData(["org-setup"])).toBeUndefined();
    expect(qc.getQueryData(["ui-prefs"])).toBeUndefined();
    // Профиль и участники приходят всегда — без них нечего рисовать.
    expect(qc.getQueryData(["me"])).toBeDefined();
  });

  it("ставит время обновления сейчас, иначе данные сразу «протухшие»", () => {
    const qc = freshClient();
    const before = Date.now();
    seedBootstrap(qc, payload());

    const state = qc.getQueryState(["me"]);
    expect(state?.dataUpdatedAt).toBeGreaterThanOrEqual(before);
    // Свежесть важна: с `updatedAt` из прошлого запрос с `staleTime` ушёл бы
    // в сеть сразу — и один запрос старта превратился бы в семь.
    expect(state?.isInvalidated).toBe(false);
  });
});

describe("useBootstrap", () => {
  it("наполняет кеш до того, как потребители начнут спрашивать", async () => {
    mockedApi.mockResolvedValueOnce(payload());
    const qc = freshClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useBootstrap(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(qc.getQueryData(["me"])).toMatchObject({ display_name: "Сергей" });
    expect(qc.getQueryData(["hr-tasks", false])).toHaveLength(1);
    // Ровно один запрос: этим и объясняется выигрыш.
    expect(mockedApi).toHaveBeenCalledTimes(1);
    expect(mockedApi.mock.calls[0][0]).toBe("/api/bootstrap");
  });
});
