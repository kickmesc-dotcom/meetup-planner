import { useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  acceptInvitation,
  previewInvitation,
  type OrgRole,
} from "@/api/orgs";
import { logoutRequest } from "@/api/auth";
import { ApiError, clearAllTokens } from "@/api/client";
import Icon from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { useErrorMessage, useT, useTx } from "@/i18n";
import type { MessageKey } from "@/i18n/messages";
import { haptic } from "@/tg/webapp";

const ROLE_KEYS: Record<string, MessageKey> = {
  owner: "role.owner",
  manager: "role.manager",
  staff: "role.staff",
};

/**
 * Принятие приглашения: `/invite?token=…` (B2B_PLATFORM_PLAN, шаг 2.2).
 *
 * Показываем ровно то, что человеку нужно решить: **кто** зовёт, **какая**
 * роль и до какого срока. Ничего не спрашиваем и не требуем заполнять профиль —
 * после присоединения приложение само заведёт сотрудника в этой организации.
 *
 * Экран живёт внутри `App`, а не до него: принять приглашение может только
 * вошедший человек. Если сессии нет, `App` сначала покажет форму входа, а
 * токен останется в адресе — после входа человек вернётся сюда же.
 *
 * Если приглашение выписано на конкретную почту, а вошли под другой, сервер
 * откажет. Здесь на этот случай есть «сменить аккаунт»: иначе человек видел бы
 * только ошибку и не понимал, что браузер помнит чужой вход.
 */
export default function InviteScreen({
  token,
  onDone,
}: {
  token: string;
  onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [emailMismatch, setEmailMismatch] = useState(false);
  const [joined, setJoined] = useState<{ orgName: string; role: OrgRole } | null>(
    null,
  );
  const { locale, t } = useT();
  const { tx } = useTx();
  const errorText = useErrorMessage();
  const roleLabel = (role: OrgRole) => {
    const key = ROLE_KEYS[role];
    return key ? t(key) : role;
  };

  const preview = useQuery({
    queryKey: ["invite", token],
    queryFn: () => previewInvitation(token),
    retry: false,
    staleTime: 60_000,
  });

  const accept = useMutation({
    mutationFn: () => acceptInvitation(token),
    onSuccess: (result) => {
      haptic("success");
      setJoined({ orgName: result.org_name, role: result.role });
    },
    onError: (e) => {
      haptic("error");
      // Код, а не фраза: текст зависит от языка, поведение — нет.
      setError(errorText(e));
      setEmailMismatch(
        e instanceof ApiError && e.detail === "invite_email_mismatch",
      );
    },
  });

  const switchAccount = () => {
    // Выход важнее ответа сервера: локальный токен забываем в любом случае.
    void logoutRequest()
      .catch(() => undefined)
      .finally(() => {
        clearAllTokens();
        window.location.reload();
      });
  };

  const card = (children: ReactNode) => (
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
        <div className="rounded-card bg-tg-secondary-bg/40 p-4">{children}</div>
      </div>
    </div>
  );

  if (joined) {
    return card(
      <>
        <h1 className="text-lg font-semibold text-tg-text">
          {t("invite.joined.title")}
        </h1>
        <p className="mt-1 text-xs text-tg-hint">
          {t("invite.joined.text", {
            org: joined.orgName,
            role: roleLabel(joined.role),
          })}
        </p>
        <button
          type="button"
          onClick={onDone}
          className="mt-4 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text"
        >
          {t("invite.openApp")}
        </button>
      </>,
    );
  }

  if (preview.isPending) {
    // Заголовок приглашения не зависит от ответа сервера — он и есть первый
    // кадр. Ждём только название компании, роль и срок: именно они приходят
    // из базы, а на медленном контуре это секунды.
    return card(
      <>
        <div className="flex items-center gap-2 animate-pulse motion-reduce:animate-none">
          <div className="h-4 w-4 rounded-tile bg-tg-bg/50" />
          <div className="h-3 w-24 rounded-tile bg-tg-bg/40" />
        </div>
        <h1 className="mt-1 text-lg font-semibold text-tg-text">
          {t("invite.title")}
        </h1>
        <div className="mt-1 animate-pulse motion-reduce:animate-none space-y-2">
          <div className="h-3 w-3/4 rounded-tile bg-tg-bg/40" />
          <div className="h-11 rounded-tile bg-tg-bg/40" />
        </div>
      </>
    );
  }

  if (preview.isError || !preview.data) {
    return card(
      <>
        <h1 className="text-lg font-semibold text-tg-text">
          {t("invite.error.title")}
        </h1>
        <p className="mt-1 text-xs text-tg-hint">
          {errorText(preview.error)}
        </p>
        <button
          type="button"
          onClick={onDone}
          className="mt-4 min-h-11 w-full rounded-card bg-tg-secondary-bg text-sm text-tg-text"
        >
          {t("invite.error.go")}
        </button>
      </>,
    );
  }

  const invite = preview.data;
  const until = new Date(invite.expires_at).toLocaleDateString(
    locale === "en" ? "en-GB" : "ru-RU",
    { day: "numeric", month: "long" },
  );

  return card(
    <>
      <div className="flex items-center gap-2 text-tg-hint">
        <Icon name="team" size={18} />
        <span className="text-xs">{invite.org_name}</span>
      </div>
      <h1 className="mt-1 text-lg font-semibold text-tg-text">
        {t("invite.title")}
      </h1>
      <p className="mt-1 text-xs text-tg-hint">
        {t("invite.role", { role: roleLabel(invite.role), until })}
      </p>
      {(invite.position || invite.department_name) && (
        <p className="mt-1 text-xs text-tg-hint">
          {tx("Вас ждут: {details}", {
            details: [invite.position, invite.department_name]
              .filter(Boolean)
              .join(" · "),
          })}
        </p>
      )}

      {invite.email && (
        <p className="mt-2 rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-tg-text">
          {t("invite.emailNote", { email: invite.email })}
        </p>
      )}

      {error && (
        <p
          role="alert"
          className="mt-2 rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-status-busy"
        >
          {error}
        </p>
      )}

      <button
        type="button"
        disabled={accept.isPending}
        onClick={() => {
          haptic("medium");
          setError(null);
          accept.mutate();
        }}
        className="mt-3 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
      >
        {accept.isPending ? t("invite.joining") : t("invite.join")}
      </button>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
        <button
          type="button"
          onClick={onDone}
          className="min-h-9 text-tg-hint"
        >
          {t("invite.later")}
        </button>
        {(emailMismatch || error) && (
          <button
            type="button"
            onClick={switchAccount}
            className="min-h-9 text-tg-link"
          >
            {t("invite.switchAccount")}
          </button>
        )}
      </div>
    </>,
  );
}
