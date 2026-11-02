/**
 * Пути ручек пакета отрасли.
 *
 * Зачем такой простой тест. Типы проверяют форму ответа, но не адрес: ручка
 * кабинета смонтирована с префиксом `/api`, и клиент с лишним `/hr` спокойно
 * собирается, а на боевом сервере отвечает 404. Именно это и случилось при
 * первом деплое шага 3.2 — тест на строку адреса дешевле повторной выкладки.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.fn();

vi.mock("./client", () => ({
  api: (...args: unknown[]) => apiMock(...args),
}));

import { applyPack, fetchPack } from "./packs";

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue({});
});

describe("packs api", () => {
  it("читает пакет из /api/pack", async () => {
    await fetchPack();
    expect(apiMock).toHaveBeenCalledWith("/api/pack");
  });

  it("применяет пакет по /api/pack/apply методом POST", async () => {
    await applyPack({ force_terms: true });
    expect(apiMock).toHaveBeenCalledWith("/api/pack/apply", {
      method: "POST",
      body: JSON.stringify({ force_terms: true }),
    });
  });
});
