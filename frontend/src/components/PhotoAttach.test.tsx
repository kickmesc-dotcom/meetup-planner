// @vitest-environment jsdom
/**
 * Превью фото: сеть рвётся — картинка не должна оставаться «сломанной».
 *
 * Раньше `<img>` после единственной неудачи показывал иконку битого файла
 * навсегда. Теперь два повтора с параметром `retry`, а дальше — понятная
 * подпись вместо пустого квадрата.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PhotoThumbs } from "./PhotoAttach";

vi.mock("@/api/media", () => ({
  mediaUrl: (path: string) => path,
  uploadPhoto: vi.fn(),
  telegramPhotoUrl: (path: string) => path,
}));

afterEach(cleanup);

describe("PhotoThumbs", () => {
  it("повторяет запрос картинки с меткой retry", () => {
    render(<PhotoThumbs photos={[{ id: 1, url: "/api/media/1?s=abc" }]} />);
    fireEvent.error(screen.getByAltText("Фотоотчёт"));
    const retried = screen.getByAltText("Фотоотчёт") as HTMLImageElement;
    expect(retried.getAttribute("src")).toBe("/api/media/1?s=abc&retry=1");
  });

  it("после двух сбоев показывает подпись вместо пустого места", () => {
    render(<PhotoThumbs photos={[{ id: 2, url: "/api/media/2?s=abc" }]} />);
    for (let i = 0; i < 3; i += 1) {
      const img = screen.queryByAltText("Фотоотчёт");
      if (img) fireEvent.error(img);
    }
    expect(screen.getByText("Фото не открылось")).toBeTruthy();
  });
});
