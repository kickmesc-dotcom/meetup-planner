// @vitest-environment jsdom
/**
 * UI_UX_PRO_MAX §9 `modal-escape` и §1 `escape-routes`:
 * шторка должна закрываться не только тапом по фону.
 *
 * Почему тест, а не «мы добавили Escape». Фон шторки на телефоне перекрыт
 * контентом, а на компьютере у человека без мыши другого выхода из шторки не
 * было вовсе. Обработчик легко потерять при следующей правке анимации, поэтому
 * проверяем поведение: Escape, именованная кнопка закрытия и `aria-modal`,
 * без которого скринридер читает фон как доступный.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BottomSheet from "./BottomSheet";

// В проекте не включён автоочистка testing-library: без неё четыре кейса
// складывают четыре шторки в один document, и `getByRole` находит сразу все.
afterEach(cleanup);

function renderSheet(onClose = vi.fn()) {
  render(
    <BottomSheet title="Массовая постановка" onClose={onClose}>
      <p>Тело шторки</p>
    </BottomSheet>,
  );
  return onClose;
}

describe("шторка: выход и модальность", () => {
  it("объявлена модальным диалогом с именем", () => {
    renderSheet();
    const dialog = screen.getByRole("dialog", { name: "Массовая постановка" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });

  it("закрывается клавишей Escape", () => {
    const onClose = renderSheet();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("не закрывается на другие клавиши", () => {
    const onClose = renderSheet();
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("кнопка закрытия подписана и не меньше 44×44", () => {
    const onClose = renderSheet();
    const button = screen.getByRole("button", { name: "Закрыть" });
    // 44px заданы фиксированной стороной (h-11 = 44px), а не min-height:
    // кнопка должна быть ровным квадратом, а не растягиваться по заголовку.
    expect(button.className).toContain("h-11");
    expect(button.className).toContain("w-11");
    fireEvent.click(button);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
