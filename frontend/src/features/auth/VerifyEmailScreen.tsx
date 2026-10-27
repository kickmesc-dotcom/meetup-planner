import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { confirmEmailVerification } from "@/api/auth";
import Icon from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { useErrorMessage, useT } from "@/i18n";
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
  const { t } = useT();
  const errorText = useErrorMessage();
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
  const failure = failed ? errorText(confirm.error) : "";

  return (
    <div className="flex h-full w-full items-center justify-center overflow-y-auto px-4 py-6">
      <div className="w-full max-w-[400px]">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-tg-hint">
            <Icon name="lock" size={15} />
            <span className="text-xs">SemiTask</span>
          </div>
          <div className="flex items-center gap-1">
            <LanguageSwitcher />
            <ThemeSwitcher />
          </div>
        </div>

        <div className="rounded-card bg-tg-secondary-bg/40 p-4">
          {confirm.isSuccess ? (
            <>
              <h1 className="text-lg font-semibold text-tg-text">
                {t("verify.done.title")}
              </h1>
              <p className="mt-1 text-xs text-tg-hint">{t("verify.done.text")}</p>
              <button
                type="button"
                onClick={onDone}
                className="mt-4 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text"
              >
                {t("verify.done.button")}
              </button>
            </>
          ) : failed ? (
            <>
              <h1 className="text-lg font-semibold text-tg-text">
                {t("verify.error.title")}
              </h1>
              <p className="mt-1 text-xs text-tg-hint">{failure}</p>
              <p className="mt-2 text-xs text-tg-hint">
                {t("verify.error.hint")}
              </p>
              <button
                type="button"
                onClick={onDone}
                className="mt-4 min-h-12 w-full rounded-card bg-tg-secondary-bg text-sm font-medium text-tg-text"
              >
                {t("verify.error.button")}
              </button>
            </>
          ) : (
            <>
              <h1 className="text-lg font-semibold text-tg-text">
                {t("verify.title")}
              </h1>
              <p className="mt-1 text-xs text-tg-hint">{t("verify.hint")}</p>
              <div
                aria-hidden="true"
                className="mt-4 h-1 w-full animate-pulse motion-reduce:animate-none rounded-full bg-tg-secondary-bg"
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
