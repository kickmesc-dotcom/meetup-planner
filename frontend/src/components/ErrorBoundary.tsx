/**
 * Последний рубеж: ошибка рендера не должна оставлять белый экран.
 *
 * Зачем. React при исключении в дереве размонтирует всё приложение: человек
 * видит пустую страницу и не знает, ждать ему или обновлять. Класс-граница
 * ловит такие ошибки и показывает один понятный экран с кнопкой «Обновить».
 *
 * Почему класс, а не хук: `componentDidCatch` есть только у классовых
 * компонентов — это ограничение React, а не стиль.
 *
 * Почему тексты через `tx`, а не `useTx`: граница обязана работать, даже если
 * провайдеры выше упали. Локаль читаем прямо из `localStorage` (тот же ключ,
 * что у `initLocale`), а неизвестная — откатываемся на русский.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";
import { LOCALE_STORAGE_KEY, tx, type Locale } from "@/i18n";
import { reportClientError } from "@/lib/telemetry";

type Props = { children: ReactNode };
type State = { error: Error | null };

function currentLocale(): Locale {
  try {
    const raw = localStorage.getItem(LOCALE_STORAGE_KEY);
    return raw === "ru" || raw === "en" || raw === "uz" ? raw : "ru";
  } catch {
    return "ru";
  }
}

export default class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Консоль — для локальной отладки; отчёт уходит на сервер, чтобы о падении
    // у клиента узнали до его звонка, а не после.
    console.error("app.crashed", error, info.componentStack);
    reportClientError("render", error, info.componentStack ?? "");
  }

  override render(): ReactNode {
    if (!this.state.error) return this.props.children;

    const locale = currentLocale();
    return (
      <div
        role="alert"
        className="flex min-h-screen flex-col items-center justify-center gap-3 bg-tg-bg px-6 text-center"
      >
        <h1 className="text-title text-tg-text">
          {tx(locale, "Не удалось загрузить")}
        </h1>
        <p className="max-w-sm text-sm text-tg-hint">
          {tx(locale, "Что-то пошло не так")}
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="min-h-11 rounded-tile bg-tg-button px-4 text-sm font-medium text-tg-button-text"
        >
          {tx(locale, "Обновить")}
        </button>
      </div>
    );
  }
}
