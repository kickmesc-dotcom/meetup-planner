import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { confirmPasswordReset } from "@/api/auth";
import { clearAllTokens } from "@/api/client";
import Icon from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { useErrorMessage, useT } from "@/i18n";
import { haptic } from "@/tg/webapp";

/**
 * Смена пароля по ссылке из письма (`/reset?token=…`).
 *
 * Отдельный маршрут, а не режим формы входа: человек приходит сюда из почты,
 * часто на другом устройстве, и пароля у него ещё нет. Поэтому здесь только
 * два поля и никаких «войти» — после успеха сервер гасит все сессии (в том
 * числе чужие), и остаётся один шаг: войти заново.
 *
 * Токен одноразовый и живёт час; протухший показываем человеческим текстом и
 * сразу предлагаем запросить новую ссылку, а не оставляем тупик.
 */
const MIN_PASSWORD = 8;

export default function ResetPasswordScreen({
  token,
  onDone,
}: {
  token: string;
  onDone: () => void;
}) {
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const { t } = useT();
  const errorText = useErrorMessage();

  const confirm = useMutation({
    mutationFn: () => confirmPasswordReset(token, password),
    onSuccess: () => {
      // Все прежние сессии сервер уже погасил — локальные токены тоже не нужны.
      clearAllTokens();
      haptic("success");
      setError(null);
      setDone(true);
    },
    onError: (e) => {
      haptic("error");
      setError(errorText(e));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setError(t("reset.short"));
      return;
    }
    if (password !== repeat) {
      setError(t("reset.mismatch"));
      return;
    }
    confirm.mutate();
  };

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
          {done ? (
            <>
              <h1 className="text-lg font-semibold text-tg-text">{t("reset.done.title")}</h1>
              <p className="mt-1 text-xs text-tg-hint">{t("reset.done.text")}</p>
              <button
                type="button"
                onClick={onDone}
                className="mt-4 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text"
              >
                {t("reset.done.button")}
              </button>
            </>
          ) : (
            <>
              <h1 className="text-lg font-semibold text-tg-text">{t("reset.title")}</h1>
              <p className="mt-1 text-xs text-tg-hint">{t("reset.hint")}</p>

              <form className="mt-3 space-y-2" onSubmit={submit} noValidate>
                <label className="block">
                  <span className="text-xs text-tg-hint">{t("reset.password")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    maxLength={128}
                    placeholder={t("reset.password.placeholder")}
                    className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text placeholder:text-tg-hint"
                  />
                </label>

                <label className="block">
                  <span className="text-xs text-tg-hint">{t("reset.repeat")}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={repeat}
                    onChange={(e) => setRepeat(e.target.value)}
                    maxLength={128}
                    className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text"
                  />
                </label>

                {error && (
                  <p
                    role="alert"
                    className="rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-status-busy"
                  >
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={confirm.isPending}
                  className="mt-1 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
                >
                  {confirm.isPending ? t("reset.saving") : t("reset.save")}
                </button>
              </form>

              <button
                type="button"
                onClick={onDone}
                className="mt-3 min-h-9 text-xs text-tg-link"
              >
                {t("reset.needNew")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
