import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  loginRequest,
  logoutRequest,
  registerRequest,
  requestPasswordReset,
  type AuthSession,
} from "@/api/auth";
import {
  clearAccessToken,
  clearAllTokens,
  humanizeApiError,
  setSessionToken,
} from "@/api/client";
import Icon from "@/components/Icon";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { haptic } from "@/tg/webapp";

/**
 * Вход по почте и паролю — для веб-версии вне Telegram (шаг 2.1).
 *
 * Почему один экран на три сценария. Регистрация, вход и «забыл пароль» — это
 * одна и та же карточка с разными полями: разводить их по отдельным маршрутам
 * значит плодить переходы там, где человек ещё ничего не знает о продукте.
 * Внутри Telegram экран не показывается вовсе: там личность подтверждает бот.
 *
 * Пароль нигде не сохраняется — только токен сессии, который сервер может
 * отозвать (в отличие от ссылки доступа из бота, которая живёт как пароль).
 */

type Mode = "login" | "register" | "forgot";

const TITLES: Record<Mode, string> = {
  login: "Вход",
  register: "Новый аккаунт",
  forgot: "Сброс пароля",
};

const SUBMITS: Record<Mode, string> = {
  login: "Войти",
  register: "Создать аккаунт",
  forgot: "Отправить ссылку",
};

export default function AuthScreen({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const accept = (session: AuthSession) => {
    // Ссылка доступа из бота больше не нужна: сессия главнее и её можно отозвать.
    clearAccessToken();
    setSessionToken(session.token);
    haptic("success");
    onDone();
  };

  const login = useMutation({
    mutationFn: () => loginRequest(email.trim(), password),
    onSuccess: accept,
    onError: (e) => {
      haptic("error");
      setError(humanizeApiError(e));
    },
  });

  const register = useMutation({
    mutationFn: () => registerRequest(email.trim(), password, name),
    onSuccess: accept,
    onError: (e) => {
      haptic("error");
      setError(humanizeApiError(e));
    },
  });

  const forgot = useMutation({
    mutationFn: () => requestPasswordReset(email.trim()),
    onSuccess: () => {
      haptic("success");
      setError(null);
      setSent(true);
    },
    onError: (e) => {
      haptic("error");
      setError(humanizeApiError(e));
    },
  });

  const pending = login.isPending || register.isPending || forgot.isPending;

  const switchMode = (next: Mode) => {
    haptic("selection");
    setMode(next);
    setError(null);
    setSent(false);
    setPassword("");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError("Введи адрес почты.");
      return;
    }
    if (mode === "forgot") forgot.mutate();
    else if (mode === "register") register.mutate();
    else login.mutate();
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
          <h1 className="text-lg font-semibold text-tg-text">{TITLES[mode]}</h1>
          <p className="mt-1 text-xs text-tg-hint">
            {mode === "login" && "Рабочее приложение смены: задачи, чек-листы и график."}
            {mode === "register" && "Аккаунт нужен, чтобы работать с компьютера и без Telegram."}
            {mode === "forgot" && "Пришлём ссылку на почту — она живёт час и срабатывает один раз."}
          </p>

          {sent ? (
            <div className="mt-4 space-y-3">
              <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-sm text-tg-text">
                Если адрес зарегистрирован, письмо уже в пути. Открой ссылку из
                него и задай новый пароль.
              </p>
              <button
                type="button"
                onClick={() => switchMode("login")}
                className="min-h-11 w-full rounded-tile bg-tg-secondary-bg text-sm font-medium text-tg-text"
              >
                Вернуться ко входу
              </button>
            </div>
          ) : (
            <form className="mt-3 space-y-2" onSubmit={submit} noValidate>
              {mode === "register" && (
                <label className="block">
                  <span className="text-xs text-tg-hint">Как тебя зовут</span>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    autoComplete="name"
                    maxLength={64}
                    placeholder="Необязательно"
                    className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text placeholder:text-tg-hint"
                  />
                </label>
              )}

              <label className="block">
                <span className="text-xs text-tg-hint">Почта</span>
                <input
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  maxLength={255}
                  placeholder="name@company.ru"
                  className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text placeholder:text-tg-hint"
                />
              </label>

              {mode !== "forgot" && (
                <label className="block">
                  <span className="text-xs text-tg-hint">Пароль</span>
                  <input
                    type="password"
                    autoComplete={mode === "register" ? "new-password" : "current-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    maxLength={128}
                    placeholder={mode === "register" ? "Не короче 8 символов" : ""}
                    className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text placeholder:text-tg-hint"
                  />
                </label>
              )}

              {error && (
                <p role="alert" className="rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-status-busy">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={pending}
                className="mt-1 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {pending ? "Секунду…" : SUBMITS[mode]}
              </button>
            </form>
          )}

          {!sent && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
              {mode === "login" ? (
                <>
                  <button type="button" onClick={() => switchMode("forgot")} className="min-h-9 text-tg-link">
                    Забыл пароль
                  </button>
                  <button type="button" onClick={() => switchMode("register")} className="min-h-9 text-tg-link">
                    Создать аккаунт
                  </button>
                </>
              ) : (
                <button type="button" onClick={() => switchMode("login")} className="min-h-9 text-tg-link">
                  У меня уже есть аккаунт
                </button>
              )}
            </div>
          )}
        </div>

        <p className="mt-3 px-1 text-xs text-tg-hint">
          Внутри Telegram вход не нужен: приложение открывается из бота и уже
          знает, кто ты.
        </p>
      </div>
    </div>
  );
}

/**
 * Вошёл, но организации нет: приглашение ещё не пришло (шаг 2.2).
 *
 * Это не ошибка пароля и не «тебя уволили», поэтому экран объясняет, что
 * делать дальше, и оставляет выход — иначе аккаунт на чужом компьютере
 * пришлось бы чистить через настройки браузера.
 */
export function NoOrgScreen() {
  const [leaving, setLeaving] = useState(false);

  const leave = () => {
    setLeaving(true);
    // Выход важнее ответа сервера: локальный токен забываем в любом случае.
    void logoutRequest()
      .catch(() => undefined)
      .finally(() => {
        clearAllTokens();
        window.location.reload();
      });
  };

  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <div className="max-w-sm">
        <Icon name="inbox" size={30} className="mx-auto mb-2 text-tg-hint" />
        <div className="text-lg font-medium text-tg-text">Аккаунт готов</div>
        <p className="mt-2 text-sm text-tg-hint">
          Осталось попасть в организацию: попроси управляющего прислать
          приглашение на эту почту. После этого данные появятся сами.
        </p>
        <button
          type="button"
          disabled={leaving}
          onClick={leave}
          className="mt-4 min-h-11 rounded-full bg-tg-secondary-bg px-4 text-xs text-tg-text disabled:opacity-50"
        >
          {leaving ? "Выходим…" : "Выйти"}
        </button>
      </div>
    </div>
  );
}
