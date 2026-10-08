// @vitest-environment jsdom
/**
 * GHG11(7): порядок и поведение блоков чужого профиля.
 *
 * Сверху вниз: главная плашка (имя/ранг/уровень + активные состояния с
 * причинами), сетка 4 подблоков («раз» у лоха/чухана, пояснение места в чарте),
 * сворачиваемый блок ачивок со сравнением со своими, сворачиваемые истории
 * разнострочно и внизу — свитчер «не показывать события участника в моей ленте».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import GuestProfileScreen from "./GuestProfileScreen";
import { fetchGuestProfile, fetchMyGame, type GuestProfile } from "@/api/game";
import { fetchMe, fetchUiPrefs, updateUiPrefs } from "@/api/availability";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return {
    ...actual,
    fetchGuestProfile: vi.fn(),
    fetchMyGame: vi.fn(),
  };
});

vi.mock("@/api/availability", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/availability")>();
  return {
    ...actual,
    fetchMe: vi.fn(),
    fetchUiPrefs: vi.fn(),
    updateUiPrefs: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

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
  max_level: 10,
  xp_into_level: 88,
  xp_to_next: 12,
  at_max: false,
  prestige: 0,
  supreme: false,
  completionist: false,
  loser_count: 19,
  chukhan_count: 3,
  rank_position: 5,
  ranks_total: 6,
  achievements_collected: 2,
  achievements_total: 34,
  achievements_percent: 15,
  loser_history: [
    { at: "2026-10-03T18:20:00Z", reason: "даже его тень иногда отходит подальше" },
    { at: "2026-10-02T18:20:00Z", reason: "проиграл в камень-ножницы-бумага" },
    { at: "2026-10-01T18:20:00Z", reason: "опять проспал" },
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
    {
      code: "rare_thing",
      title: "Редкая штука",
      icon: "💎",
      description: "нечто редкое",
      points: 5,
      unlocked_at: "2026-09-01T10:00:00Z",
    },
  ],
  today: {
    loser: true,
    loser_reason: "уронил торт на встрече",
    chukhan: false,
    chukhan_reason: null,
    worm: false,
  },
  recent: [
    {
      kind: "message",
      icon: "💬",
      label: "Последнее сообщение в чат",
      text: "ну что, кто сегодня лох",
      at: "2026-10-08T11:55:00Z",
      post_id: null,
      media_type: null,
      media_count: null,
    },
    {
      kind: "achievement",
      icon: "🎙",
      label: "Последняя открытая ачивка",
      text: "«Голос из народа» (+20 XP)",
      at: "2026-10-04T21:47:00Z",
      post_id: null,
      media_type: null,
      media_count: null,
    },
    {
      kind: "activity",
      icon: "🎮",
      label: "Последнее действие в мини-аппе",
      text: "Случайное событие в чате",
      at: "2026-10-07T20:00:00Z",
      post_id: null,
      media_type: null,
      media_count: null,
    },
    {
      kind: "media",
      icon: "📸",
      label: "Последнее медиа в чат",
      text: "фото",
      at: "2026-10-06T19:30:00Z",
      post_id: 42,
      media_type: "photo",
      media_count: 1,
    },
    {
      kind: "visit",
      icon: "🚪",
      label: "Последний заход в мини-апп",
      text: null,
      at: "2026-10-08T12:30:00Z",
      post_id: null,
      media_type: null,
      media_count: null,
    },
  ],
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
    enabled: true,
    achievements: [
      { code: "voice_from_people", collected: true },
      { code: "rare_thing", collected: false },
    ],
    // Минимально нужные для сравнения поля.
  } as unknown as Awaited<ReturnType<typeof fetchMyGame>>);
  vi.mocked(fetchMe).mockResolvedValue({
    id: 99,
    display_name: "Я",
  } as unknown as Awaited<ReturnType<typeof fetchMe>>);
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

function sectionTexts(container: HTMLElement): string[] {
  return [...container.querySelectorAll("section")].map((s) => s.textContent ?? "");
}

describe("GuestProfileScreen: порядок блоков (GHG11(7))", () => {
  it("плашка → 4 подблока → ачивки → истории → свитчер", async () => {
    const { container } = renderProfile();
    await screen.findByText("📊 Открыто ачивок");
    const texts = sectionTexts(container);
    const plaque = texts.findIndex((t) => t.includes("Серж-NEO"));
    const stats = texts.findIndex((t) => t.includes("🤡 Лох дня"));
    const ach = texts.findIndex((t) => t.includes("Открыто ачивок"));
    const loser = texts.findIndex((t) => t.includes("История «лоха дня»"));
    const chukhan = texts.findIndex((t) => t.includes("История «чухана недели»"));
    const mute = texts.findIndex((t) => t.includes("Не показывать события"));
    const recent = texts.findIndex((t) => t.includes("Последняя активность"));
    expect(plaque).toBe(0);
    expect(stats).toBeGreaterThan(plaque);
    expect(ach).toBeGreaterThan(stats);
    expect(loser).toBeGreaterThan(ach);
    expect(chukhan).toBeGreaterThan(loser);
    expect(mute).toBeGreaterThan(chukhan);
    // GHG11(10): превью последней активности — в самом низу профиля.
    expect(recent).toBeGreaterThan(mute);
  });

  it("в плашке активное состояние с причиной", async () => {
    renderProfile();
    await screen.findByText("Сегодня лох дня");
    expect(screen.getByText(/уронил торт на встрече/)).toBeTruthy();
    // Уровень и «сколько до следующего».
    expect(screen.getByText(/Ур\. 3 из 10/)).toBeTruthy();
    expect(screen.getByText(/до след\. ранга: 12 XP/)).toBeTruthy();
  });
});

describe("GuestProfileScreen: 4 подблока (GHG11(7))", () => {
  it("лох и чухан подписаны словом «раз» с правильной формой", async () => {
    renderProfile();
    expect(await screen.findByText("19 раз")).toBeTruthy();
    expect(screen.getByText("3 раза")).toBeTruthy();
  });

  it("место в чарте поясняет, на основе чего считается", async () => {
    renderProfile();
    expect(await screen.findByText("5 из 6")).toBeTruthy();
    expect(screen.getByText("по опыту (XP) среди всех участников")).toBeTruthy();
  });
});

describe("GuestProfileScreen: ачивки (GHG11(7))", () => {
  it("свёрнуты по умолчанию, раскрываются со сравнением со своими", async () => {
    renderProfile();
    await screen.findByText("📊 Открыто ачивок");
    expect(screen.queryByText("Голос из народа")).toBeNull();
    fireEvent.click(screen.getByText("📊 Открыто ачивок"));
    expect(await screen.findByText("Голос из народа")).toBeTruthy();
    // Своя ачивка отмечена галочкой, чужой/недостающей — точка.
    expect(screen.getByTitle("Такая ачивка есть и у тебя")).toBeTruthy();
    expect(screen.getByTitle("У тебя её ещё нет")).toBeTruthy();
  });
});

describe("GuestProfileScreen: история разнострочно (GHG11(7))", () => {
  it("соседние строки чередуют фон", async () => {
    const { container } = renderProfile();
    await screen.findByText("🤡 История «лоха дня»");
    fireEvent.click(screen.getByText("🤡 История «лоха дня»"));
    const stripes = [...container.querySelectorAll("[data-stripe]")].map((el) =>
      el.getAttribute("data-stripe"),
    );
    expect(stripes.length).toBeGreaterThanOrEqual(2);
    expect(stripes[0]).toBe("dark");
    expect(stripes[1]).toBe("light");
  });
});

describe("GuestProfileScreen: свитчер ленты (GHG11(7))", () => {
  it("компактный: контейнер-строка без карточки и свитчер размера sm", async () => {
    renderProfile();
    const wrap = await screen.findByTestId("mute-feed-switch");
    expect(wrap.className).not.toContain("rounded-xl");
    // Тот же контейнер держит переключатель.
    const sw = wrap.querySelector('[role="switch"]');
    expect(sw).not.toBeNull();
    expect(sw!.className).toContain("h-4");
    expect(sw!.className).toContain("w-8");
  });

  it("выключен по умолчанию, при тапе скрывает события участника", async () => {
    renderProfile();
    const sw = await screen.findByRole("switch");
    expect(sw.getAttribute("aria-checked")).toBe("false");
    // Свитчер активен только когда настройки загружены.
    await waitFor(() => expect((sw as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(sw);
    await waitFor(() =>
      expect(updateUiPrefs).toHaveBeenCalledWith({ muted_feed: [1] }),
    );
  });

  it("для своего профиля свитчера нет", async () => {
    vi.mocked(fetchMe).mockResolvedValue({
      id: 1,
      display_name: "Я",
    } as unknown as Awaited<ReturnType<typeof fetchMe>>);
    renderProfile();
    await screen.findByText("📊 Открыто ачивок");
    expect(screen.queryByRole("switch")).toBeNull();
  });
});

describe("GuestProfileScreen: последняя активность (GHG11(10))", () => {
  it("показывает пять строк: сообщение, ачивка, действие, медиа, заход", async () => {
    renderProfile();
    expect(await screen.findByText("Последняя активность", { exact: false })).toBeTruthy();
    expect(screen.getByText("Последнее сообщение в чат")).toBeTruthy();
    expect(screen.getByText("Последняя открытая ачивка")).toBeTruthy();
    expect(screen.getByText("Последнее действие в мини-аппе")).toBeTruthy();
    expect(screen.getByText("Последнее медиа в чат")).toBeTruthy();
    expect(screen.getByText("Последний заход в мини-апп")).toBeTruthy();
    expect(screen.getByText("ну что, кто сегодня лох")).toBeTruthy();
  });

  it("медиа-превью открывается в лайтбоксе по клику", async () => {
    renderProfile();
    const thumb = await screen.findByTestId("media-thumb");
    expect(screen.queryByTestId("media-lightbox")).toBeNull();
    fireEvent.click(thumb);
    expect(await screen.findByTestId("media-lightbox")).toBeTruthy();
    fireEvent.click(screen.getByTestId("media-lightbox"));
    await waitFor(() => expect(screen.queryByTestId("media-lightbox")).toBeNull());
  });
});
