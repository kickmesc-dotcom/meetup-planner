// @vitest-environment jsdom
/**
 * GHG11(5): deep-link CTA из анонса фичи.
 *
 * `goToFeature` — вся логика кнопки «Открыть и применить →»: переключает вкладку,
 * просит целевой экран раскрыть блок (`feedAnchor`) и, если ведём в админку,
 * сразу открывает нужный подраздел (`pendingAdminSection`). Проверяем именно
 * проводку store, не полный рендер профиля.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { goToFeature } from "./GameSection";
import { useUI } from "@/store/ui";

beforeEach(() => {
  vi.useFakeTimers();
  useUI.setState({
    tab: "feed",
    feedAnchor: null,
    pendingAdminSection: null,
  });
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  cleanup();
});

describe("goToFeature (GHG11(5))", () => {
  it("в админку открывает подраздел и не ставит якорь", () => {
    goToFeature("admin", "", "loser");
    const s = useUI.getState();
    expect(s.tab).toBe("admin");
    expect(s.pendingAdminSection).toBe("loser");
    expect(s.feedAnchor).toBeNull();
  });

  it("в ленту с якорем раскрывает «Действия» и не трогает админку", () => {
    goToFeature("feed", "feed-actions");
    vi.advanceTimersByTime(3000);
    const s = useUI.getState();
    expect(s.tab).toBe("feed");
    expect(s.feedAnchor).toBe("feed-actions");
    expect(s.pendingAdminSection).toBeNull();
  });

  it("в админку БЕЗ подраздела не оставляет якорь и секцию", () => {
    goToFeature("admin", "", undefined);
    const s = useUI.getState();
    expect(s.tab).toBe("admin");
    expect(s.pendingAdminSection).toBeNull();
    expect(s.feedAnchor).toBeNull();
  });

  it("неизвестная вкладка — no-op (ничего не переключаем)", () => {
    goToFeature("bogus", "x", "loser");
    const s = useUI.getState();
    expect(s.tab).toBe("feed");
    expect(s.pendingAdminSection).toBeNull();
    expect(s.feedAnchor).toBeNull();
  });

  it("не-админский переход не тащит adminSection", () => {
    goToFeature("calendar", "some-anchor", "chukhan");
    const s = useUI.getState();
    expect(s.tab).toBe("calendar");
    expect(s.pendingAdminSection).toBeNull();
  });
});
