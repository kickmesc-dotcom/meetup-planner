// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import StatusAnnouncer from "./StatusAnnouncer";

/**
 * Страж живого региона. Причина: без `role="status"` скринридер не узнаёт,
 * что после фильтра изменился результат, — человек слышит тишину и нажимает
 * ещё раз. Тест держит свойства, от которых зависит объявление.
 */
afterEach(cleanup);

describe("StatusAnnouncer", () => {
  it("объявляет текст вежливо и целиком", () => {
    render(<StatusAnnouncer text="Найдено: 3 из 12" />);

    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    // Без `aria-atomic` скринридер прочитал бы только изменившийся фрагмент:
    // «20» без «из 140» бесполезно.
    expect(status.getAttribute("aria-atomic")).toBe("true");
    expect(status.textContent).toBe("Найдено: 3 из 12");
  });

  it("не занимает место на экране", () => {
    render(<StatusAnnouncer text="Записей нет" />);

    expect(screen.getByRole("status").className).toContain("sr-only");
  });
});
