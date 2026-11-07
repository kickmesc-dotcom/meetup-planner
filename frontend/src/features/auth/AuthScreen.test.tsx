// @vitest-environment jsdom
/**
 * Аудит UI_UX_PRO_MAX §8: пароль можно проверить, не перепечатывая вслепую.
 *
 * Заодно держим §5 `readable-font-size`: поля на мобиле — 16px, иначе iOS
 * зумит страницу при фокусе и человек теряет кнопку «Войти» из виду.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AuthScreen from "./AuthScreen";

vi.mock("@/tg/webapp", () => ({ haptic: vi.fn() }));
vi.mock("@/tg/standalone", () => ({
  isStandalone: () => false,
  shouldShowStandaloneHint: () => false,
  markStandaloneHintSeen: vi.fn(),
}));
vi.mock("@/api/auth", () => ({
  loginRequest: vi.fn(),
  registerRequest: vi.fn(),
  requestPasswordReset: vi.fn(),
  logoutRequest: vi.fn(() => Promise.resolve({ ok: true })),
}));

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <AuthScreen onDone={vi.fn()} />
    </QueryClientProvider>,
  );
}

afterEach(cleanup);

describe("AuthScreen — показ пароля", () => {
  it("по умолчанию пароль скрыт", () => {
    renderScreen();
    const password = screen.getByLabelText("Пароль") as HTMLInputElement;
    expect(password.type).toBe("password");
    expect(
      screen.getByRole("button", { name: "Показать пароль" }),
    ).toBeTruthy();
  });

  it("кнопка открывает пароль и меняет подпись для скринридера", () => {
    renderScreen();
    const password = screen.getByLabelText("Пароль") as HTMLInputElement;

    fireEvent.click(screen.getByRole("button", { name: "Показать пароль" }));

    expect(password.type).toBe("text");
    const toggle = screen.getByRole("button", { name: "Скрыть пароль" });
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
  });

  it("поля не мельче 16px — iOS не будет зумить при фокусе", () => {
    renderScreen();
    const email = screen.getByLabelText("Почта") as HTMLInputElement;
    expect(email.className).toContain("text-base");
  });
});

describe("AuthScreen — ошибка у поля", () => {
  it("ошибка связана с полем, а фокус уходит в почту", () => {
    renderScreen();
    fireEvent.click(screen.getByRole("button", { name: /Войти|Вход/i }));

    const email = screen.getByLabelText("Почта") as HTMLInputElement;
    // §8 `error-placement`: скринридер должен связать сообщение с полем,
    // а не читать его как отдельный текст где-то ниже формы.
    expect(email.getAttribute("aria-invalid")).toBe("true");
    expect(email.getAttribute("aria-describedby")).toBe("auth-error");
    expect(screen.getByRole("alert").id).toBe("auth-error");
    // §8 `focus-management`: после отказа фокус на первом проблемном поле.
    expect(document.activeElement).toBe(email);
  });
});
