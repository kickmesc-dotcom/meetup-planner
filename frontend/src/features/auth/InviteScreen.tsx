import { useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  acceptInvitation,
  ORG_ROLE_LABELS,
  previewInvitation,
  type OrgRole,
} from "@/api/orgs";
import { logoutRequest } from "@/api/auth";
import { clearAllTokens, humanizeApiError } from "@/api/client";
import Icon from "@/components/Icon";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { haptic } from "@/tg/webapp";

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
      const text = humanizeApiError(e);
      setError(text);
      setEmailMismatch(text.includes("другую почту"));
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
          <ThemeSwitcher />
        </div>
        <div className="rounded-card bg-tg-secondary-bg/40 p-4">{children}</div>
      </div>
    </div>
  );

  if (joined) {
    return card(
      <>
        <h1 className="text-lg font-semibold text-tg-text">
          Ты в организации
        </h1>
        <p className="mt-1 text-xs text-tg-hint">
          {joined.orgName} · {ORG_ROLE_LABELS[joined.role] ?? joined.role}. Данные
          смены появятся сразу после входа.
        </p>
        <button
          type="button"
          onClick={onDone}
          className="mt-4 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text"
        >
          Открыть приложение
        </button>
      </>,
    );
  }

  if (preview.isPending) {
    return card(
      <div className="animate-pulse space-y-2">
        <div className="h-5 w-1/2 rounded-tile bg-tg-bg/50" />
        <div className="h-3 w-3/4 rounded-tile bg-tg-bg/40" />
        <div className="h-11 rounded-tile bg-tg-bg/40" />
      </div>,
    );
  }

  if (preview.isError || !preview.data) {
    return card(
      <>
        <h1 className="text-lg font-semibold text-tg-text">
          Приглашение не открылось
        </h1>
        <p className="mt-1 text-xs text-tg-hint">
          {humanizeApiError(preview.error)}
        </p>
        <button
          type="button"
          onClick={onDone}
          className="mt-4 min-h-11 w-full rounded-card bg-tg-secondary-bg text-sm text-tg-text"
        >
          Перейти в приложение
        </button>
      </>,
    );
  }

  const invite = preview.data;
  const roleLabel = ORG_ROLE_LABELS[invite.role] ?? invite.role;
  const until = new Date(invite.expires_at).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
  });

  return card(
    <>
      <div className="flex items-center gap-2 text-tg-hint">
        <Icon name="team" size={18} />
        <span className="text-xs">{invite.org_name}</span>
      </div>
      <h1 className="mt-1 text-lg font-semibold text-tg-text">
        Приглашение в команду
      </h1>
      <p className="mt-1 text-xs text-tg-hint">
        Тебе открывают доступ с ролью «{roleLabel}». Присоединиться можно до{" "}
        {until}.
      </p>

      {invite.email && (
        <p className="mt-2 rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-tg-text">
          Приглашение выписано на {invite.email} — оно сработает только под этим
          адресом.
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
        {accept.isPending ? "Присоединяемся…" : "Присоединиться"}
      </button>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
        <button
          type="button"
          onClick={onDone}
          className="min-h-9 text-tg-hint"
        >
          Не сейчас
        </button>
        {(emailMismatch || error) && (
          <button
            type="button"
            onClick={switchAccount}
            className="min-h-9 text-tg-link"
          >
            Войти под другой почтой
          </button>
        )}
      </div>
    </>,
  );
}
