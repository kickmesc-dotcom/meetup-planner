import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { confirmEmailVerification } from "@/api/auth";
import { humanizeApiError } from "@/api/client";
import Icon from "@/components/Icon";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { haptic } from "@/tg/webapp";

/**
 * Подтверждение почты по ссылке из письма (`/verify?token=…`).
 *
 * Раньше адрес считался «своим» сразу после регистрации: письма о сбросе и
 * приглашения уходили на непроверенный ящик. Теперь ссылка подтверждает, что
 * человек действительно владеет адресом.
 *
 * Экран не требует входа: письмо часто открывают на телефоне, где сессии ещё
 * нет. Подтверждение привязывается к аккаунту токеном, а не к браузеру.
 * Повторный клик по тому же письму сервер считает успехом — человек не должен
 * видеть «ссылка не подходит» из-за второго нажатия.
 */
export default function VerifyEmailScreen({
  token,
  onDone,
}: {
  token: string;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const started = useRef(false);
  const confirm = useMutation({
    mutationFn: () => confirmEmailVerification(token),
    onSuccess: () => {
      haptic("success");
      // Профиль мог быть открыт в другой вкладке — обновим данные о человеке.
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: () => haptic("error"),
  });

  useEffect(() => {
    // StrictMode в dev вызывает эффект дважды; второй запрос не нужен.
    if (started.current) return;
    started.current = true;
    confirm.mutate();
  }, [confirm]);

  const failed = confirm.isError;
  const errorText = failed ? humanizeApiError(confirm.error) : "";

  return (
    <div className="flex h-full w-full items-center justify-center overflow-y-auto px-4 py-6">
      <div className="w-full max-w-[400px]">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-tg-hint">
            <Icon name="lock" size={15} />
            <span className="text-xs">SemiTask</span>
          </div>
          <ThemeSwitcher />
        </div>

        <div className="rounded-card bg-tg-secondary-bg/40 p-4">
          {confirm.isSuccess ? (
            <>
              <h1 className="text-lg font-semibold text-tg-text">
                Почта подтверждена
              </h1>
              <p className="mt-1 text-xs text-tg-hint">
                Теперь на этот адрес придут вход, сброс пароля и важные
                уведомления. Ничего больше делать не нужно.
              </p>
              <button
                type="button"
                onClick={onDone}
                className="mt-4 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text"
              >
                Перейти в приложение
              </button>
            </>
          ) : failed ? (
            <>
              <h1 className="text-lg font-semibold text-tg-text">
                Ссылка не подошла
              </h1>
              <p className="mt-1 text-xs text-tg-hint">{errorText}</p>
              <p className="mt-2 text-xs text-tg-hint">
                Ссылка живёт двое суток и работает один раз. Попроси новую в
                профиле: «Подтвердить почту» — и открой свежее письмо.
              </p>
              <button
                type="button"
                onClick={onDone}
                className="mt-4 min-h-12 w-full rounded-card bg-tg-secondary-bg text-sm font-medium text-tg-text"
              >
                В приложение
              </button>
            </>
          ) : (
            <>
              <h1 className="text-lg font-semibold text-tg-text">
                Подтверждаем почту…
              </h1>
              <p className="mt-1 text-xs text-tg-hint">
                Один момент — проверяем ссылку из письма.
              </p>
              <div
                aria-hidden="true"
                className="mt-4 h-1 w-full animate-pulse rounded-full bg-tg-secondary-bg"
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
