// @vitest-environment jsdom
/**
 * Экран `/reset`: два поля, одна кнопка — и никакого тупика.
 *
 * Проверяем обещания, которые видит человек из письма:
 *  - короткий пароль и несовпадение ловятся до запроса к серверу;
 *  - после успеха все локальные токены забыты (сервер уже погасил сессии);
 *  - протухшая ссылка объясняется по-русски и оставляет путь «запросить новую».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ResetPasswordScreen from "./ResetPasswordScreen";
import { confirmPasswordReset } from "@/api/auth";
import { ApiError, getSessionToken, setSessionToken } from "@/api/client";

vi.mock("@/tg/webapp", () => ({
  getInitData: vi.fn(() => ""),
  haptic: vi.fn(),
}));
vi.mock("@/api/auth", () => ({ confirmPasswordReset: vi.fn() }));

const confirmMock = vi.mocked(confirmPasswordReset);

function renderScreen() {
  const onDone = vi.fn();
  const qc = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <ResetPasswordScreen token="reset_tok" onDone={onDone} />
    </QueryClientProvider>,
  );
  return onDone;
}

function fill(password: string, repeat: string) {
  fireEvent.change(screen.getByLabelText("Пароль"), {
    target: { value: password },
  });
  fireEvent.change(screen.getByLabelText("Ещё раз"), {
    target: { value: repeat },
  });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить пароль" }));
}

beforeEach(() => {
  confirmMock.mockReset();
  setSessionToken("старая_сессия");
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("ResetPasswordScreen", () => {
  it("короткий пароль не отправляет на сервер", () => {
    renderScreen();

    fill("1234", "1234");

    expect(screen.getByRole("alert").textContent).toContain(
      "Пароль короче 8 символов",
    );
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("несовпадение паролей ловится до запроса", () => {
    renderScreen();

    fill("пароль123", "пароль124");

    expect(screen.getByRole("alert").textContent).toContain(
      "Пароли не совпадают",
    );
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("после успеха забывает токены и ведёт ко входу", async () => {
    confirmMock.mockResolvedValue({ ok: true });
    const onDone = renderScreen();

    fill("новый_пароль_1", "новый_пароль_1");

    expect(await screen.findByText("Пароль обновлён")).toBeTruthy();
    expect(confirmMock).toHaveBeenCalledWith("reset_tok", "новый_пароль_1");
    expect(getSessionToken()).toBeNull();
    expect(onDone).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Войти с новым паролем" }));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("протухшая ссылка объясняется и оставляет форму", async () => {
    confirmMock.mockRejectedValue(new ApiError(400, "reset_expired"));
    renderScreen();

    fill("новый_пароль_1", "новый_пароль_1");

    expect(
      await screen.findByText("Срок ссылки истёк — запроси новую."),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Сохранить пароль" }),
    ).toBeTruthy();
  });
});
