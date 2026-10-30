import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  loginRequest,
  logoutRequest,
  registerRequest,
  requestPasswordReset,
  type AuthSession,
} from "@/api/auth";
import { clearAccessToken, clearAllTokens, setSessionToken } from "@/api/client";
import Icon from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { useErrorMessage, useT } from "@/i18n";
import type { MessageKey } from "@/i18n/messages";
import {
  isStandalone,
  markStandaloneHintSeen,
  shouldShowStandaloneHint,
} from "@/tg/standalone";
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

const TITLES: Record<Mode, MessageKey> = {
  login: "auth.login.title",
  register: "auth.register.title",
  forgot: "auth.forgot.title",
};

const SUBMITS: Record<Mode, MessageKey> = {
  login: "auth.login.submit",
  register: "auth.register.submit",
  forgot: "auth.forgot.submit",
};

export default function AuthScreen({
  onDone,
  invited,
}: {
  onDone: () => void;
  /** Человек пришёл по ссылке-приглашению: скажем, зачем его просят войти. */
  invited?: boolean;
}) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  // M2: в установленном приложении человек не понимает, почему перед ним
  // форма, а не бот. Подсказка — один раз и закрываемая, не блокирует вход.
  const [standalone] = useState(() => isStandalone());
  const [appHint, setAppHint] = useState(() => shouldShowStandaloneHint());
  const { t } = useT();
  const errorText = useErrorMessage();

  useEffect(() => {
    // Помечаем при показе: иначе человек, который сразу вошёл, видел бы
    // подсказку при каждом запуске до первого «Понятно».
    if (shouldShowStandaloneHint()) markStandaloneHintSeen();
  }, []);

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
      setError(errorText(e));
    },
  });

  const register = useMutation({
    mutationFn: () => registerRequest(email.trim(), password, name),
    onSuccess: accept,
    onError: (e) => {
      haptic("error");
      setError(errorText(e));
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
      setError(errorText(e));
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
      setError(t("auth.emailRequired"));
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
          <div className="flex items-center gap-1">
            <LanguageSwitcher />
            <ThemeSwitcher />
          </div>
        </div>

        {appHint && (
          <div className="mb-3 flex items-start gap-2 rounded-card bg-tg-link/10 p-3">
            <p className="min-w-0 flex-1 text-xs text-tg-text">
              {t("auth.appNote")}
            </p>
            <button
              type="button"
              onClick={() => {
                haptic("light");
                setAppHint(false);
              }}
              className="min-h-9 shrink-0 rounded-tile px-2 text-xs font-medium text-tg-link"
            >
              {t("auth.appNote.dismiss")}
            </button>
          </div>
        )}

        <div className="rounded-card bg-tg-secondary-bg/40 p-4">
          <h1 className="text-lg font-semibold text-tg-text">{t(TITLES[mode])}</h1>
          {invited && (
            <p className="mt-2 rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-tg-text">
              {t("auth.invited")}
            </p>
          )}
          <p className="mt-1 text-xs text-tg-hint">
            {mode === "login" && t("auth.login.hint")}
            {mode === "register" && t("auth.register.hint")}
            {mode === "forgot" && t("auth.forgot.hint")}
          </p>

          {sent ? (
            <div className="mt-4 space-y-3">
              <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-sm text-tg-text">
                {t("auth.sent")}
              </p>
              <button
                type="button"
                onClick={() => switchMode("login")}
                className="min-h-11 w-full rounded-tile bg-tg-secondary-bg text-sm font-medium text-tg-text"
              >
                {t("auth.backToLogin")}
              </button>
            </div>
          ) : (
            <form className="mt-3 space-y-2" onSubmit={submit} noValidate>
              {mode === "register" && (
                <label className="block">
                  <span className="text-xs text-tg-hint">{t("auth.name.label")}</span>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    autoComplete="name"
                    maxLength={64}
                    placeholder={t("auth.name.placeholder")}
                    className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text placeholder:text-tg-hint"
                  />
                </label>
              )}

              <label className="block">
                <span className="text-xs text-tg-hint">{t("auth.email.label")}</span>
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
                  <span className="text-xs text-tg-hint">{t("auth.password.label")}</span>
                  <input
                    type="password"
                    autoComplete={mode === "register" ? "new-password" : "current-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    maxLength={128}
                    placeholder={mode === "register" ? t("auth.password.placeholder") : ""}
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
                {pending ? t("auth.pending") : t(SUBMITS[mode])}
              </button>
            </form>
          )}

          {!sent && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
              {mode === "login" ? (
                <>
                  <button type="button" onClick={() => switchMode("forgot")} className="min-h-9 text-tg-link">
                    {t("auth.forgot")}
                  </button>
                  <button type="button" onClick={() => switchMode("register")} className="min-h-9 text-tg-link">
                    {t("auth.create")}
                  </button>
                </>
              ) : (
                <button type="button" onClick={() => switchMode("login")} className="min-h-9 text-tg-link">
                  {t("auth.haveAccount")}
                </button>
              )}
            </div>
          )}
        </div>

        {/* В установленном приложении про Telegram молчим: там его нет, и
            фраза читалась бы как ошибка выбора. */}
        {!standalone && (
          <p className="mt-3 px-1 text-xs text-tg-hint">
            {t("auth.telegramNote")}
          </p>
        )}
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
  const { t } = useT();

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
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <div className="mb-6 flex items-center gap-1 self-end">
        <LanguageSwitcher />
        <ThemeSwitcher />
      </div>
      <div className="max-w-sm">
        <Icon name="inbox" size={30} className="mx-auto mb-2 text-tg-hint" />
        <div className="text-lg font-medium text-tg-text">
          {t("auth.noorg.title")}
        </div>
        <p className="mt-2 text-sm text-tg-hint">{t("auth.noorg.text")}</p>
        <button
          type="button"
          disabled={leaving}
          onClick={leave}
          className="mt-4 min-h-11 rounded-full bg-tg-secondary-bg px-4 text-xs text-tg-text disabled:opacity-50"
        >
          {leaving ? t("auth.noorg.leaving") : t("auth.noorg.logout")}
        </button>
      </div>
    </div>
  );
}
