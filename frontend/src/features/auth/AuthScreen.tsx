import { useEffect, useRef, useState } from "react";
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
import FormField from "@/components/FormField";
import Icon from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { Spinner } from "@/components/Spinner";
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

/** Достаточно строгая проверка формы, а не полная по RFC: цель — поймать опечатку. */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

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
  // UI_UX_PRO_MAX §8 `password-toggle`: человек должен иметь возможность
  // проверить ввод, не перепечатывая пароль вслепую.
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  // §8 `inline-validation`: ошибка формата рядом с полем, а не после отправки.
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  // §8 `focus-management`: после отказа фокус уходит на первое поле, которое
  // человеку нужно поправить, — иначе он остаётся на кнопке и не понимает,
  // куда смотреть.
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
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

  /** Первое поле, которое могло вызвать отказ: почта или пароль. */
  const focusProblem = (current: Mode) => {
    if (current === "forgot" || !email.trim()) emailRef.current?.focus();
    else passwordRef.current?.focus();
  };

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
      focusProblem(mode);
    },
  });

  const register = useMutation({
    mutationFn: () => registerRequest(email.trim(), password, name),
    onSuccess: accept,
    onError: (e) => {
      haptic("error");
      setError(errorText(e));
      focusProblem(mode);
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
      focusProblem(mode);
    },
  });

  const pending = login.isPending || register.isPending || forgot.isPending;

  const switchMode = (next: Mode) => {
    haptic("selection");
    setMode(next);
    setError(null);
    setSent(false);
    setPassword("");
    // Пароль нового режима не должен открытым текстом перейти в следующий.
    setShowPassword(false);
  };

  const checkEmail = () => {
    const value = email.trim();
    // Пустое поле на выходе не ругаем: до первой попытки это не ошибка.
    setEmailError(
      value && !EMAIL_RE.test(value) ? t("auth.email.invalid") : null,
    );
  };

  const checkPassword = () => {
    setPasswordError(
      mode !== "forgot" && password.length > 0 && password.length < 8
        ? t("auth.password.short")
        : null,
    );
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError(t("auth.emailRequired"));
      emailRef.current?.focus();
      return;
    }
    if (mode === "forgot") forgot.mutate();
    else if (mode === "register") register.mutate();
    else login.mutate();
  };

  return (
    <div className="flex h-full w-full items-center justify-center overflow-y-auto px-4 py-6">
      <div className="w-full max-w-[400px]">
        {/* Одна линия: марка слева, языки и тема — в общей капсуле справа.
            Разные по весу контролы раньше читались как случайные элементы. */}
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2 text-tg-hint">
            <Icon name="lock" size={16} />
            <span className="truncate text-sm font-medium text-tg-text">SemiTask</span>
          </div>
          <div className="flex shrink-0 items-center gap-0.5 rounded-full bg-tg-secondary-bg/70 p-0.5">
            <LanguageSwitcher bare />
            <ThemeSwitcher bare />
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
              className="min-h-11 shrink-0 rounded-tile px-2 text-xs font-medium text-tg-link"
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
          {/* На входе подсказка ничего не добавляла к полям и только отвлекала:
              режимы регистрации и сброса объясняют правила, вход — нет. */}
          {mode !== "login" && (
            // Подпись режима лежит на полупрозрачной плашке; hint на ней
            // не дотягивал до AA (axe). Это объяснение, а не декор.
            <p className="mt-1 text-xs leading-snug text-tg-text">
              {mode === "register" && t("auth.register.hint")}
              {mode === "forgot" && t("auth.forgot.hint")}
            </p>
          )}

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
                <FormField id="auth-name" label={t("auth.name.label")}>
                  {(field) => (
                    <input
                      {...field}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      autoComplete="name"
                      maxLength={64}
                      placeholder={t("auth.name.placeholder")}
                      className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-base text-tg-text placeholder:text-tg-hint"
                    />
                  )}
                </FormField>
              )}

              <FormField
                id="auth-email"
                label={t("auth.email.label")}
                required
                invalid={!!error || !!emailError}
                error={emailError}
                describedBy={error ? "auth-error" : undefined}
              >
                {(field) => (
                  <input
                    {...field}
                    ref={emailRef}
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (emailError) setEmailError(null);
                    }}
                    onBlur={checkEmail}
                    maxLength={255}
                    placeholder="name@company.ru"
                    className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-base text-tg-text placeholder:text-tg-hint"
                  />
                )}
              </FormField>

              {mode !== "forgot" && (
                // `label htmlFor` + отдельная кнопка-глаз: обёртка-label
                // перехватывала бы клик по глазу и уводила фокус в поле.
                <FormField
                  id="auth-password"
                  label={t("auth.password.label")}
                  required
                  invalid={!!error || !!passwordError}
                  error={passwordError}
                  describedBy={error ? "auth-error" : undefined}
                >
                  {(field) => (
                    <div className="relative mt-1">
                      <input
                        {...field}
                        ref={passwordRef}
                        type={showPassword ? "text" : "password"}
                        autoComplete={mode === "register" ? "new-password" : "current-password"}
                        value={password}
                        onChange={(e) => {
                          setPassword(e.target.value);
                          if (passwordError) setPasswordError(null);
                        }}
                        onBlur={checkPassword}
                        maxLength={128}
                        placeholder={mode === "register" ? t("auth.password.placeholder") : ""}
                        className="min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 pr-12 text-base text-tg-text placeholder:text-tg-hint"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword((value) => !value)}
                        aria-label={t(showPassword ? "auth.password.hide" : "auth.password.show")}
                        aria-pressed={showPassword}
                        className="absolute inset-y-0 right-0 grid min-h-11 min-w-11 place-items-center rounded-tile px-3 text-tg-hint"
                      >
                        <Icon name={showPassword ? "eyeOff" : "eye"} size={18} />
                      </button>
                    </div>
                  )}
                </FormField>
              )}

              {error && (
                <p
                  id="auth-error"
                  role="alert"
                  className="rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-status-busy"
                >
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={pending}
                aria-busy={pending}
                className="mt-1 inline-flex min-h-12 w-full items-center justify-center gap-1.5 rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {pending && <Spinner size={14} />}
                {pending ? t("auth.pending") : t(SUBMITS[mode])}
              </button>
              {/* §8 `required-indicators`: звёздочка без расшифровки — загадка,
                  поэтому подпись идёт под формой, а не только в скринридере. */}
              {/* Сноска про звёздочку — единственное объяснение, зачем она.
                  На плашке `secondary-bg/40` hint не дотягивал до AA. */}
              <p className="text-2xs text-tg-text">{t("auth.requiredNote")}</p>
            </form>
          )}

          {!sent && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
              {mode === "login" ? (
                <>
                  <button type="button" onClick={() => switchMode("forgot")} className="min-h-11 text-tg-link">
                    {t("auth.forgot")}
                  </button>
                  <button type="button" onClick={() => switchMode("register")} className="min-h-11 text-tg-link">
                    {t("auth.create")}
                  </button>
                </>
              ) : (
                <button type="button" onClick={() => switchMode("login")} className="min-h-11 text-tg-link">
                  {t("auth.haveAccount")}
                </button>
              )}
            </div>
          )}
        </div>

        {/* В установленном приложении про Telegram молчим: там его нет, и
            фраза читалась бы как ошибка выбора.
            Смысл — пояснение, а не часть формы: отдельная плашка с иконкой,
            чтобы текст не висел в воздухе мелким абзацем. */}
        {!standalone && (
          <div className="mt-3 flex items-start gap-2 rounded-tile bg-tg-secondary-bg/50 p-3 ring-1 ring-tg-hint/10">
            <Icon
              name="bot"
              size={16}
              className="mt-0.5 shrink-0 text-tg-hint"
            />
            <p className="min-w-0 flex-1 text-xs leading-snug text-tg-text">
              {t("auth.telegramNote")}
            </p>
          </div>
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
      <div className="mb-6 flex items-center gap-0.5 self-end rounded-full bg-tg-secondary-bg/70 p-0.5">
        <LanguageSwitcher bare />
        <ThemeSwitcher bare />
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
