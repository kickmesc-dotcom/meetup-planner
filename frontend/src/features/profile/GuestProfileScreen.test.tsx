// @vitest-environment jsdom
/**
 * GHG11(6): перестройка чужого профиля «глазами гостя».
 *
 * Прод-фидбек: сверху — последние ачивки с датой/временем получения, ниже
 * сворачиваемые истории «лоха дня» и «чухана недели». Проверяем порядок
 * блоков, дату в строке ачивки и то, что истории свёрнуты до тапа.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import GuestProfileScreen from "./GuestProfileScreen";
import { fetchGuestProfile, fetchMyGame, type GuestProfile } from "@/api/game";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return {
    ...actual,
    fetchGuestProfile: vi.fn(),
    fetchMyGame: vi.fn(),
  };
});

afterEach(cleanup);

const PROFILE: GuestProfile = {
  enabled: true,
  telegram_id: 306733739,
  user_id: 1,
  name: "Серж-NEO",
  avatar_url: null,
  level: 3,
  rank: { level: 3, name: "Терпила средней руки", hex: "#3b82f6", bold: false },
  rank_name: "Терпила средней руки",
  xp: 388,
  prestige: 0,
  supreme: false,
  completionist: false,
  loser_count: 19,
  chukhan_count: 3,
  rank_position: 1,
  ranks_total: 6,
  achievements_collected: 5,
  achievements_total: 34,
  achievements_percent: 15,
  loser_history: [
    { at: "2026-10-03T18:20:00Z", reason: "даже его тень иногда отходит подальше" },
  ],
  chukhan_history: [
    { at: "2026-08-10T09:00:00Z", reason: "Зарегистрирован в списке катаклизмов" },
  ],
  worm_total_days: 3,
  achievements: [
    {
      code: "voice_from_people",
      title: "Голос из народа",
      icon: "🎙",
      description: "сдать голосовое задание",
      points: 20,
      unlocked_at: "2026-10-04T21:47:00Z",
    },
  ],
  today: null,
};

function renderProfile() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <GuestProfileScreen userId={1} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchGuestProfile).mockResolvedValue(PROFILE);
  vi.mocked(fetchMyGame).mockResolvedValue({
    enabled: false,
    achievements: [],
  } as unknown as Awaited<ReturnType<typeof fetchMyGame>>);
});

describe("GuestProfileScreen: порядок блоков (GHG11(6))", () => {
  it("сверху «Последние ачивки», ниже лох, ещё ниже чухан", async () => {
    const { container } = renderProfile();
    await screen.findByText("🏅 Последние ачивки");
    const texts = [...container.querySelectorAll("section")].map(
      (s) => s.textContent ?? "",
    );
    const ach = texts.findIndex((t) => t.includes("Последние ачивки"));
    const loser = texts.findIndex((t) => t.includes("История «лоха дня»"));
    const chukhan = texts.findIndex((t) => t.includes("История «чухана недели»"));
    expect(ach).toBe(0);
    expect(loser).toBeGreaterThan(ach);
    expect(chukhan).toBeGreaterThan(loser);
  });

  it("у ачивки справа дата и время получения", async () => {
    renderProfile();
    await screen.findByText("Голос из народа");
    // День/месяц не фиксируем точно: 21:47 UTC — это уже следующая дата в МSK.
    expect(screen.getByText(/^\d{1,2} [а-я]{3}/)).toBeTruthy();
    expect(screen.getByText(/^\d{2}:\d{2}$/)).toBeTruthy();
  });

  it("раскрытие ачивки показывает «за что» и награду", async () => {
    renderProfile();
    fireEvent.click(await screen.findByText("Голос из народа"));
    expect(screen.getByText(/сдать голосовое задание/)).toBeTruthy();
    expect(screen.getByText("Награда: +20 XP")).toBeTruthy();
  });
});

describe("GuestProfileScreen: сворачиваемые истории (GHG11(6))", () => {
  it("истории свёрнуты до тапа и раскрываются", async () => {
    renderProfile();
    await screen.findByText("🤡 История «лоха дня»");
    // Пока свёрнуто — ни причин, ни записей в DOM.
    expect(screen.queryByText(/его тень иногда отходит/)).toBeNull();
    fireEvent.click(screen.getByText("🤡 История «лоха дня»"));
    expect(screen.getByText(/его тень иногда отходит/)).toBeTruthy();
    // Вторая история осталась свёрнутой — раскрывается отдельно.
    expect(screen.queryByText(/списке катаклизмов/)).toBeNull();
    fireEvent.click(screen.getByText("💩 История «чухана недели»"));
    expect(screen.getByText(/списке катаклизмов/)).toBeTruthy();
  });

  it("пустая история показывается сразу, без кнопки", async () => {
    vi.mocked(fetchGuestProfile).mockResolvedValue({
      ...PROFILE,
      loser_history: [],
    });
    renderProfile();
    expect(await screen.findByText("Ни разу не был лохом дня.")).toBeTruthy();
  });
});
