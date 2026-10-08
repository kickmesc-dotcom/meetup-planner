// @vitest-environment jsdom
/**
 * GHG11(7): фильтр ленты «по участникам».
 *
 * Мастер-пикеры «Все»/«Никто» вверху, чекбоксы участников, своя галочка
 * неснимаемая (свои события из ленты не выкидываются).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ParticipantsFilterSheet from "./ParticipantsFilterSheet";
import { fetchUsers, fetchUiPrefs, updateUiPrefs } from "@/api/availability";

vi.mock("@/api/availability", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/availability")>();
  return {
    ...actual,
    fetchUsers: vi.fn(),
    fetchUiPrefs: vi.fn(),
    updateUiPrefs: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const USERS = [
  { id: 1, display_name: "Я", avatar_url: null, color_hex: "#111" },
  { id: 2, display_name: "Митян", avatar_url: null, color_hex: "#222" },
  { id: 3, display_name: "Сомов", avatar_url: null, color_hex: "#333" },
];

function renderSheet() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ParticipantsFilterSheet meId={1} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchUsers).mockResolvedValue(
    USERS as unknown as Awaited<ReturnType<typeof fetchUsers>>,
  );
  vi.mocked(fetchUiPrefs).mockResolvedValue({
    hide_greeting: false,
    welcome_format: "avatar",
    muted_feed: [],
    show_last_seen: true,
  });
  vi.mocked(updateUiPrefs).mockImplementation(async (p) => ({
    hide_greeting: false,
    welcome_format: "avatar",
    muted_feed: p.muted_feed ?? [],
    show_last_seen: p.show_last_seen ?? true,
  }));
});

describe("ParticipantsFilterSheet (GHG11(7))", () => {
  it("показывает мастер-пикеры и список участников", async () => {
    renderSheet();
    await screen.findByText("Митян");
    expect(screen.getByText("Все")).toBeTruthy();
    expect(screen.getByText("Никто")).toBeTruthy();
    expect(screen.getByText("Сомов")).toBeTruthy();
    expect(screen.getByText("Это ты — свои события видны всегда")).toBeTruthy();
  });

  it("своя галочка стоит и заблокирована", async () => {
    renderSheet();
    await screen.findByText("Митян");
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes[0].checked).toBe(true);
    expect(boxes[0].disabled).toBe(true);
  });

  it("«Все» скрывает всех, кроме себя", async () => {
    renderSheet();
    await screen.findByText("Митян");
    fireEvent.click(screen.getByText("Все"));
    await waitFor(() =>
      expect(updateUiPrefs).toHaveBeenCalledWith({ muted_feed: [2, 3] }),
    );
  });

  it("«Никто» очищает список", async () => {
    vi.mocked(fetchUiPrefs).mockResolvedValue({
      hide_greeting: false,
      welcome_format: "avatar",
      muted_feed: [2, 3],
      show_last_seen: true,
    });
    renderSheet();
    await screen.findByText("Митян");
    fireEvent.click(screen.getByText("Никто"));
    await waitFor(() =>
      expect(updateUiPrefs).toHaveBeenCalledWith({ muted_feed: [] }),
    );
  });

  it("тап по участнику добавляет его в скрытые", async () => {
    renderSheet();
    await screen.findByText("Митян");
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    fireEvent.click(boxes[1]);
    await waitFor(() =>
      expect(updateUiPrefs).toHaveBeenCalledWith({ muted_feed: [2] }),
    );
  });
});
