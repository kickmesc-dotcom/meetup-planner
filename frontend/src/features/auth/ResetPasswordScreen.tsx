import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { confirmPasswordReset } from "@/api/auth";
import { clearAllTokens, humanizeApiError } from "@/api/client";
import Icon from "@/components/Icon";
import ThemeSwitcher from "@/components/ThemeSwitcher";
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
      setError(humanizeApiError(e));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setError("Пароль короче 8 символов.");
      return;
    }
    if (password !== repeat) {
      setError("Пароли не совпадают.");
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
          <ThemeSwitcher />
        </div>

        <div className="rounded-card bg-tg-secondary-bg/40 p-4">
          {done ? (
            <>
              <h1 className="text-lg font-semibold text-tg-text">Пароль обновлён</h1>
              <p className="mt-1 text-xs text-tg-hint">
                Все прежние входы закрыты — это защита на случай, если ссылку
                увидел кто-то ещё.
              </p>
              <button
                type="button"
                onClick={onDone}
                className="mt-4 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text"
              >
                Войти с новым паролем
              </button>
            </>
          ) : (
            <>
              <h1 className="text-lg font-semibold text-tg-text">Новый пароль</h1>
              <p className="mt-1 text-xs text-tg-hint">
                Придумай пароль не короче 8 символов. После сохранения все
                устройства выйдут из аккаунта.
              </p>

              <form className="mt-3 space-y-2" onSubmit={submit} noValidate>
                <label className="block">
                  <span className="text-xs text-tg-hint">Пароль</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    maxLength={128}
                    placeholder="Не короче 8 символов"
                    className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text placeholder:text-tg-hint"
                  />
                </label>

                <label className="block">
                  <span className="text-xs text-tg-hint">Ещё раз</span>
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
                  {confirm.isPending ? "Сохраняем…" : "Сохранить пароль"}
                </button>
              </form>

              <button
                type="button"
                onClick={onDone}
                className="mt-3 min-h-9 text-xs text-tg-link"
              >
                Ссылка не подходит? Запросить новую
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
