// @vitest-environment jsdom
/**
 * FormField — единственное место, где собираются подпись, подсказка и ошибка.
 *
 * Тест держит то, ради чего компонент появился: поле находят по подписи,
 * звёздочка не попадает в имя, а подсказка и ошибка реально связаны с полем,
 * а не висят рядом. Если эту связь убрать, скринридер снова прочитает ошибку
 * как посторонний текст.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import FormField from "./FormField";

afterEach(cleanup);

describe("FormField", () => {
  it("связывает подпись с полем и не тащит звёздочку в имя", () => {
    render(
      <FormField id="email" label="Почта" required>
        {(field) => <input {...field} />}
      </FormField>,
    );

    // Ищем по доступному имени: звёздочка помечена `aria-hidden` и в имя
    // поля не входит, хотя видна рядом с подписью.
    const input = screen.getByRole("textbox", { name: "Почта" }) as HTMLInputElement;
    expect(input.id).toBe("email");
    expect(input.getAttribute("aria-required")).toBe("true");
  });

  it("объединяет подсказку и ошибку в одно описание", () => {
    render(
      <FormField
        id="password"
        label="Пароль"
        hint="Минимум 8 символов"
        error="Слишком короткий"
      >
        {(field) => <input {...field} />}
      </FormField>,
    );

    const input = screen.getByLabelText("Пароль");
    expect(input.getAttribute("aria-describedby")).toBe(
      "password-hint password-error",
    );
    expect(input.getAttribute("aria-invalid")).toBe("true");
    // Ошибка объявляется сразу, а не ждёт следующего фокуса.
    expect(screen.getByRole("alert").id).toBe("password-error");
  });

  it("учитывает внешний id описания (общая ошибка формы)", () => {
    render(
      <FormField
        id="email"
        label="Почта"
        invalid
        describedBy="form-error"
      >
        {(field) => <input {...field} />}
      </FormField>,
    );

    const input = screen.getByLabelText("Почта");
    expect(input.getAttribute("aria-describedby")).toBe("form-error");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    // Своей ошибки нет — второй alert не появляется.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("без обязательности и ошибок не выставляет лишних атрибутов", () => {
    render(
      <FormField id="note" label="Заметка">
        {(field) => <input {...field} />}
      </FormField>,
    );

    const input = screen.getByLabelText("Заметка");
    expect(input.hasAttribute("aria-required")).toBe(false);
    expect(input.hasAttribute("aria-invalid")).toBe(false);
    expect(input.hasAttribute("aria-describedby")).toBe(false);
  });
});
