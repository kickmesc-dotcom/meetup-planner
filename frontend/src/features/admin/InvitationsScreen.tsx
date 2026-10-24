import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createInvitation,
  fetchCurrentOrg,
  fetchInvitations,
  ORG_ROLE_LABELS,
  ORG_ROLES,
  revokeInvitation,
  type OrgInvitation,
  type OrgRole,
} from "@/api/orgs";
import { humanizeApiError } from "@/api/client";
import { copyText } from "@/lib/clipboard";
import { ListSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import SubScreen from "./SubScreen";

import { currentIntlLocale, useTx } from "@/i18n";
/**
 * Приглашения в организацию (B2B_PLATFORM_PLAN, шаг 2.2).
 *
 * Управляющий выписывает ссылку с ролью и сроком. Почта необязательна:
 *  • с почтой — письмо уходит приглашённому, и принять сможет только он;
 *  • без почты — ссылка «для чата смены», принимает любой, у кого она есть.
 *
 * Ссылка показывается один раз: сервер хранит только хеш токена и повторить её
 * не может. Поэтому свежая ссылка сразу попадает на экран с кнопкой
 * «Скопировать», а в списке её уже нет — только роль и срок.
 */
const DAY_OPTIONS = [1, 3, 7, 14, 30];

export default function InvitationsScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>("staff");
  const [days, setDays] = useState(7);
  const [fresh, setFresh] = useState<OrgInvitation | null>(null);
  const [copied, setCopied] = useState(false);
  const [codeCopied, setCodeCopied] = useState(false);

  const q = useQuery({
    queryKey: ["admin", "invitations"],
    queryFn: fetchInvitations,
    staleTime: 30_000,
    retry: false,
  });
  // Код компании — второй способ позвать человека, когда ссылку пересылать
  // неудобно: сотрудник вводит его на первом экране вместе с названием.
  const org = useQuery({
    queryKey: ["org-current"],
    queryFn: fetchCurrentOrg,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const refresh = () =>
    void qc.invalidateQueries({ queryKey: ["admin", "invitations"] });

  const create = useMutation({
    mutationFn: () =>
      createInvitation({ email: email.trim() || null, role, days }),
    onSuccess: (created) => {
      haptic("success");
      setFresh(created);
      setCopied(false);
      setEmail("");
      refresh();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const revoke = useMutation({
    mutationFn: (id: number) => revokeInvitation(id),
    onSuccess: () => {
      haptic("light");
      refresh();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const copy = () => {
    if (!fresh?.link) return;
    void copyText(fresh.link).then((ok) => {
      setCopied(ok);
      haptic(ok ? "success" : "error");
      if (!ok) void showAlert(tx("Не получилось скопировать — выдели ссылку вручную."));
    });
  };

  const copyCode = () => {
    if (!org.data?.slug) return;
    void copyText(org.data.slug).then((ok) => {
      setCodeCopied(ok);
      haptic(ok ? "success" : "error");
    });
  };

  const rows = q.data ?? [];

  return (
    <SubScreen
      title={tx("Приглашения")}
      subtitle={tx("Ссылка с ролью и сроком")}
      onBack={onBack}
    >
      <div className="rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">{tx(
        "Ссылка открывает вход в организацию. Если указать почту, принять сможет только её владелец; без почты ссылку можно скинуть в чат смены. Ссылка одноразовая и перестаёт работать после присоединения.",
      )}</div>

      {org.data && (
        <section className="flex items-start justify-between gap-2 rounded-card bg-tg-secondary-bg/60 p-3">
          <div className="min-w-0">
            <div className="text-xs text-tg-hint">{tx("ID компании")}</div>
            <div className="truncate font-mono text-sm text-tg-text">
              {org.data.slug}
            </div>
            <p className="mt-0.5 text-xs text-tg-hint">{tx(
              "Сотрудник вводит его на первом экране — вместе с названием или вместо него. Список компаний снаружи не виден.",
            )}</p>
          </div>
          <button
            type="button"
            onClick={copyCode}
            className="min-h-9 shrink-0 rounded-tile bg-tg-bg/60 px-2 text-xs text-tg-link"
          >
            {codeCopied ? tx("Скопировано") : tx("Скопировать")}
          </button>
        </section>
      )}

      <section className="space-y-2 rounded-card bg-tg-secondary-bg/60 p-3">
        <div className="text-sm font-semibold text-tg-text">{tx("Новая ссылка")}</div>

        <label className="block">
          <span className="text-xs text-tg-hint">{tx("Почта (необязательно)")}</span>
          <input
            type="email"
            inputMode="email"
            autoComplete="off"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={255}
            placeholder="name@company.ru"
            className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-3 text-sm text-tg-text placeholder:text-tg-hint"
          />
        </label>

        <div className="flex gap-2">
          <label className="min-w-0 flex-1">
            <span className="text-xs text-tg-hint">{tx("Роль")}</span>
            <select
              aria-label={tx("Роль приглашённого")}
              value={role}
              onChange={(e) => setRole(e.target.value as OrgRole)}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            >
              {ORG_ROLES.map((value) => (
                <option key={value} value={value}>
                  {ORG_ROLE_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
          <label className="w-32">
            <span className="text-xs text-tg-hint">{tx("Срок")}</span>
            <select
              aria-label={tx("Срок приглашения")}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            >
              {DAY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {tx("{value} дн.", { value })}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="button"
          disabled={create.isPending}
          onClick={() => {
            haptic("medium");
            create.mutate();
          }}
          className="min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
        >
          {create.isPending ? tx("Создаём…") : tx("Создать ссылку")}
        </button>

        {fresh?.link && (
          <div className="rounded-tile bg-tg-bg/70 p-2">
            <p className="text-2xs text-tg-hint">
              {fresh.mail_sent
                ? tx("Письмо ушло на {email}.", { email: fresh.email ?? "" })
                : fresh.email
                  ? tx("Письмо не отправлено — почтовый транспорт на сервере не настроен. Скопируй ссылку и отправь вручную.")
                  : tx("Почты нет — отправь ссылку в чат смены.")}
            </p>
            <code className="mt-1 block break-all text-2xs text-tg-text">
              {fresh.link}
            </code>
            <button
              type="button"
              onClick={copy}
              className="mt-2 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text"
            >
              <Icon name={copied ? "check" : "copy"} size={15} />
              {copied ? tx("Скопировано") : tx("Скопировать")}
            </button>
          </div>
        )}
      </section>

      {q.isPending && <ListSkeleton rows={3} />}
      {q.isError && (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      )}

      {q.data && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-tg-text">
            {tx("Живые ссылки ({count})", { count: rows.length })}
          </h2>
          {rows.length === 0 && (
            <p className="text-xs text-tg-hint">{tx(
              "Ссылок нет. Создай первую — она появится здесь до присоединения или отзыва.",
            )}</p>
          )}
          {rows.length > 0 && (
            <div className="divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-card bg-tg-secondary-bg/40">
              {rows.map((row) => (
                <div key={row.id} className="flex items-start gap-2 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-tg-text">
                      {ORG_ROLE_LABELS[row.role] ?? row.role}
                      <span className="text-tg-hint"> · </span>
                      <span className="text-xs text-tg-hint">
                        {row.email ?? tx("для всех, у кого есть ссылка")}
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-tg-hint">
                      {tx("до {date}", {
                        date: new Date(row.expires_at).toLocaleDateString(
                          currentIntlLocale(),
                        ),
                      })}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={revoke.isPending}
                    onClick={() => {
                      haptic("medium");
                      void (async () => {
                        const ok = await showConfirm(
                          tx("Отозвать ссылку? Она перестанет работать сразу."),
                        );
                        if (ok) revoke.mutate(row.id);
                      })();
                    }}
                    className="shrink-0 min-h-8 rounded-full bg-tg-bg/60 px-2.5 text-xs text-status-busy disabled:opacity-50"
                  >{tx("Отозвать")}</button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </SubScreen>
  );
}
