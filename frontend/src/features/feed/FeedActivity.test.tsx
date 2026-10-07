// @vitest-environment jsdom
/**
 * GHG11(8): участие в активностях прямо из ленты.
 *
 * Оператор: анонс задания висит в ленте — по тапу по нему должен открываться
 * интерфейс участия (варианты кнопками, поле ввода, запись голосового), а не
 * отдельный блок где-то ещё.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeedDetailPanel, FeedRow } from "./FeedScreen";
import type { FeedItem } from "@/api/game";
import { answerActivity, fetchVoiceCurrent } from "@/api/game";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return {
    ...actual,
    answerActivity: vi.fn(),
    fetchVoiceCurrent: vi.fn(),
    fetchVoiceAudioUrl: vi.fn(),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(cleanup);

function renderInProvider(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

/** Анонс открытого призыва «маму любишь?» прямо в ленте. */
function announceItem(): FeedItem {
  return {
    id: "journal:42",
    source: "journal",
    kind: "event",
    icon: "⚡️",
    title: "Событие",
    text: "🫶 Маму любишь? Напиши «да» или «нет».",
    at: new Date().toISOString(),
    user_id: null,
    user_name: null,
    user_telegram_id: null,
    avatar_url: null,
    detail: {
      activity: {
        id: 7,
        code: "mom_love",
        options: [
          { label: "да", xp: 10 },
          { label: "нет", xp: 50 },
        ],
        needs_text: true,
        expires_at: null,
        answered_by_me: false,
      },
    },
  };
}

/** Голосовое задание с открытым приёмом. */
function voiceItem(): FeedItem {
  return {
    id: "voice:5",
    source: "voice",
    kind: "voice",
    icon: "🎙",
    title: "Голосовое задание",
    text: "«спой» — +50 XP",
    at: new Date().toISOString(),
    user_id: null,
    user_name: null,
    user_telegram_id: null,
    avatar_url: null,
    detail: {
      task_id: 5,
      condition: "спой",
      reward: 50,
      opened_at: null,
      closed_at: null,
      expires_at: null,
      closed: false,
      submissions: [],
    },
  };
}

describe("FeedDetailPanel: призыв из ленты (GHG11(8))", () => {
  it("даёт варианты кнопками и поле ввода", () => {
    renderInProvider(
      <FeedDetailPanel
        item={announceItem()}
        playerLike={false}
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("да")).toBeTruthy();
    expect(screen.getByText("нет")).toBeTruthy();
    expect(screen.getByPlaceholderText("Ответь прямо здесь…")).toBeTruthy();
  });

  it("тап по варианту отправляет ответ и показывает «засчитано»", async () => {
    vi.mocked(answerActivity).mockResolvedValue({ ok: true, status: "ok", xp: 10 });
    renderInProvider(
      <FeedDetailPanel
        item={announceItem()}
        playerLike={false}
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("да"));
    expect(await screen.findByText(/Засчитано/)).toBeTruthy();
    expect(answerActivity).toHaveBeenCalledWith(7, "да");
  });

  it("своё засчитанное задание сразу помечено", () => {
    const item = announceItem();
    item.detail!.activity!.answered_by_me = true;
    renderInProvider(
      <FeedDetailPanel
        item={item}
        playerLike={false}
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/Засчитано/)).toBeTruthy();
    expect(screen.queryByPlaceholderText("Ответь прямо здесь…")).toBeNull();
  });
});

describe("FeedDetailPanel: голосовое задание из ленты (GHG11(8))", () => {
  it("открытое задание даёт запись голосового", async () => {
    vi.mocked(fetchVoiceCurrent).mockResolvedValue({
      enabled: true,
      task_id: 5,
      title: "спой",
      text: "",
      reward: 50,
      expires_at: null,
      my_submission_id: null,
      submissions: [],
    });
    renderInProvider(
      <FeedDetailPanel
        item={voiceItem()}
        playerLike
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByText("🎙 Записать голосовое")).toBeTruthy();
  });

  it("своя сдача предлагает убрать вариант", async () => {
    vi.mocked(fetchVoiceCurrent).mockResolvedValue({
      enabled: true,
      task_id: 5,
      title: "спой",
      text: "",
      reward: 50,
      expires_at: null,
      my_submission_id: 11,
      submissions: [],
    });
    renderInProvider(
      <FeedDetailPanel
        item={voiceItem()}
        playerLike
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByText("Твой вариант принят.")).toBeTruthy();
    expect(screen.getByText("Убрать")).toBeTruthy();
  });

  it("чужое задание (id не совпал) не даёт записи", async () => {
    vi.mocked(fetchVoiceCurrent).mockResolvedValue({
      enabled: true,
      task_id: 99,
      title: "другое",
      text: "",
      reward: 10,
      expires_at: null,
      my_submission_id: null,
      submissions: [],
    });
    renderInProvider(
      <FeedDetailPanel
        item={voiceItem()}
        playerLike
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByText("🎙 Записать голосовое")).toBeNull();
  });
});

describe("FeedRow: анонс задания раскрывается (GHG11(8))", () => {
  it("тап по записи-событию показывает интерфейс участия", async () => {
    renderInProvider(
      <FeedRow
        item={announceItem()}
        meId={1}
        isAdmin={false}
        onOpenUser={() => {}}
        onModerated={() => {}}
        compact
      />,
    );
    expect(screen.queryByTestId("feed-activity")).toBeNull();
    fireEvent.click(screen.getByText(/Маму любишь/));
    expect(screen.getByTestId("feed-activity")).toBeTruthy();
  });
});
