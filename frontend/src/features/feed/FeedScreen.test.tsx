// @vitest-environment jsdom
/**
 * GHG11(4): регрессионные тесты ленты.
 *
 * 1. `ParticipantsStrip` — компактные миниатюры участников (+XP / лайки) и тап.
 * 2. `FeedDetailPanel` — условие задания приходит с HTML-разметкой (<b>/<i>) и
 *    должна рендериться тегами, а не показываться текстом; пустые сдачи дают
 *    «Никто не отправил свой вариант.».
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FeedDetailPanel, ParticipantsStrip } from "./FeedScreen";
import type { FeedItem } from "@/api/game";

afterEach(cleanup);

describe("ParticipantsStrip (GHG11(4))", () => {
  it("рисует миниатюры и бейдж +XP", () => {
    render(
      <ParticipantsStrip
        participants={[
          { user_id: 5, user_name: "Серж", avatar_url: null, xp: 50 },
          { user_id: 6, user_name: "Митян", avatar_url: null, xp: 0 },
        ]}
      />,
    );
    expect(screen.getByText("+50")).toBeTruthy();
    expect(screen.getByTitle("Серж")).toBeTruthy();
    expect(screen.getByTitle("Митян")).toBeTruthy();
  });

  it("для музыки без XP показывает лайки", () => {
    render(
      <ParticipantsStrip
        participants={[{ user_id: 3, user_name: "Сомов", xp: 0, likes: 3 }]}
      />,
    );
    expect(screen.getByText("❤️3")).toBeTruthy();
  });

  it("клик по миниатюре вызывает onSelect", () => {
    const onSelect = vi.fn();
    render(
      <ParticipantsStrip
        participants={[{ user_id: 1, user_name: "Серж", xp: 50 }]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTitle("Серж"));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("пустой список не рисует участников", () => {
    const { container } = render(<ParticipantsStrip participants={[]} />);
    const strip = container.querySelector('[data-testid="participants-strip"]');
    expect(strip?.children.length).toBe(0);
  });
});

describe("FeedDetailPanel: разметка условия задания (GHG11(4))", () => {
  const makeItem = (): FeedItem => ({
    id: "voice:1",
    source: "voice",
    kind: "voice",
    icon: "🎙",
    title: "Голосовое задание",
    text: "«Задание» — +50 XP",
    at: new Date().toISOString(),
    user_id: null,
    user_name: null,
    user_telegram_id: null,
    avatar_url: null,
    detail: {
      condition: "🦹 Задание: <b>произнеси угрозу</b>. Голосом, с паузами.",
      reward: 50,
      opened_at: null,
      closed_at: null,
      expires_at: null,
      closed: true,
      submissions: [],
    },
  });

  it("рендерит <b> тегом, а не показывает его текстом", () => {
    const { container } = render(
      <FeedDetailPanel
        item={makeItem()}
        playerLike
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    const bold = container.querySelector("b");
    expect(bold?.textContent).toBe("произнеси угрозу");
    // Литеральных тегов в тексте быть не должно.
    expect(container.textContent).not.toContain("<b>");
    expect(container.textContent).not.toContain("</b>");
  });

  it("при отсутствии сдач пишет «Никто не отправил свой вариант.»", () => {
    render(
      <FeedDetailPanel
        item={makeItem()}
        playerLike
        compact
        autoPlayId={null}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/Никто не отправил свой вариант/)).toBeTruthy();
  });
});
