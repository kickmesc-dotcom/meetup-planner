// @vitest-environment jsdom
/**
 * GHG11(5): тумблер вида ленты (`feed.view_compact`).
 *
 * Экран читает флаг и на переключение зовёт PUT. Проверяем: отображение
 * текущего флага, отправку правильного значения и обновление по ответу сервера.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import FeedSettingsScreen from "./FeedSettingsScreen";
import { fetchFeedViewFlag, setFeedViewFlag } from "@/api/admin";

vi.mock("@/api/admin", () => ({
  fetchFeedViewFlag: vi.fn(),
  setFeedViewFlag: vi.fn(),
}));

const fetchMock = vi.mocked(fetchFeedViewFlag);
const setMock = vi.mocked(setFeedViewFlag);

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <FeedSettingsScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  setMock.mockReset();
});
afterEach(cleanup);

describe("FeedSettingsScreen (GHG11(5))", () => {
  it("показывает включённый компактный вид", async () => {
    fetchMock.mockResolvedValue({ compact: true });
    renderScreen();
    const sw = await screen.findByRole("switch");
    // ждём загрузки флага (до ответа компакт = default true, но тумблер busy)
    await waitFor(() => expect((sw as HTMLButtonElement).disabled).toBe(false));
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  it("показывает выключенный флаг как классический вид", async () => {
    fetchMock.mockResolvedValue({ compact: false });
    renderScreen();
    // до ответа показывается дефолт (true) — дожидаемся применения флага
    await waitFor(() =>
      expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false"),
    );
  });

  it("переключение отправляет новое значение и обновляет тумблер", async () => {
    fetchMock.mockResolvedValue({ compact: true });
    setMock.mockResolvedValue({ compact: false });
    renderScreen();
    const sw = await screen.findByRole("switch");
    await waitFor(() => expect((sw as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(sw);
    await waitFor(() => expect(setMock).toHaveBeenCalledTimes(1));
    expect(setMock).toHaveBeenCalledWith(false);
    await waitFor(() =>
      expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false"),
    );
  });
});
