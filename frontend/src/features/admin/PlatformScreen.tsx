/**
 * Админка платформы (B2B_PLATFORM_PLAN, шаг 4.3).
 *
 * Зачем экран, если есть база. Поддержка не должна «править базу руками»:
 * продлить тариф, заблокировать неоплатившего и подтвердить счёт — это три
 * действия, которые делаются в день несколько раз, и каждое руками в SQL
 * заканчивается опечаткой в чужой организации.
 *
 * Почему каталог тарифов приходит с сервера. Коды и цены живут в
 * `services/billing.py`; если бы список был здесь константой, первый же новый
 * тариф появился бы на сервере и отсутствовал в админке — и его нельзя было бы
 * назначить.
 *
 * Почему «подтвердить оплату» отдельно от «я оплатил». Клиентская кнопка лишь
 * просит подтверждения; продлевает подписку только это действие. Так «я
 * оплатил» не становится бесплатным безлимитом.
 */
import { useState } from "react";
import FormField from "@/components/FormField";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelPlatformInvoice,
  confirmPlatformInvoice,
  fetchPlatformInvoices,
  fetchPlatformOnboarding,
  fetchPlatformOrgs,
  fetchPlatformRum,
  fetchPlatformSummary,
  patchPlatformOrg,
  type PlatformInvoice,
  type PlatformOrg,
} from "@/api/platform";
import { Skeleton } from "@/components/Skeleton";
import { BusyLabel } from "@/components/BusyLabel";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";
import { formatDate, formatMoney } from "@/lib/format";

const STATUS_LABEL: Record<string, string> = {
  pending: "Ожидает оплаты",
  awaiting: "Ждёт подтверждения",
  paid: "Оплачен",
  canceled: "Отменён",
  expired: "Просрочен",
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-tile bg-tg-secondary-bg/60 p-3">
      <div className="text-2xs uppercase tracking-wide text-tg-hint">{label}</div>
      <div className="text-base font-semibold text-tg-text">{value}</div>
    </div>
  );
}

function OrgRow({
  org,
  plans,
  onPlan,
  onToggle,
  busy,
}: {
  org: PlatformOrg;
  plans: { code: string; title: string }[];
  onPlan: (id: number, plan: string) => void;
  onToggle: (org: PlatformOrg) => void;
  busy: boolean;
}) {
  const { tx } = useTx();
  const until = org.plan_ends_at ?? org.trial_ends_at;
  return (
    <div className="rounded-tile bg-tg-secondary-bg/60 p-3" data-testid={`org-${org.id}`}>
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-tg-text">{org.name}</div>
          <div className="text-xs text-tg-hint">{org.slug}</div>
        </div>
        <span
          className={
            org.is_active
              ? "rounded-full bg-tg-link/15 px-2 py-1 text-2xs font-semibold text-tg-link"
              : "rounded-full bg-red-500/15 px-2 py-1 text-2xs font-semibold text-red-500"
          }
        >
          {org.is_active ? tx("Активна") : tx("Заблокирован")}
        </span>
      </div>
      <p className="mt-1 text-xs text-tg-hint">
        {tx("Места {used} из {limit}", { used: org.seats_used, limit: org.seats_limit })} ·{" "}
        {tx("Срок: {date}", { date: formatDate(until) })}
      </p>
      {org.subscription_expired && (
        <p className="mt-1 text-xs text-red-500">{tx("Оплата закончилась")}</p>
      )}
      <div className="mt-2 flex gap-2">
        <select
          aria-label={tx("Тариф")}
          value={org.plan}
          disabled={busy}
          onChange={(event) => onPlan(org.id, event.target.value)}
          className="min-h-11 flex-1 rounded-tile bg-tg-bg px-2 text-sm text-tg-text"
        >
          {plans.map((plan) => (
            <option key={plan.code} value={plan.code}>
              {tx(plan.title)}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={busy}
          aria-busy={busy}
          onClick={() => onToggle(org)}
          className="min-h-11 rounded-tile bg-tg-secondary-bg px-3 text-sm font-semibold text-tg-hint disabled:opacity-50"
        >
          <BusyLabel busy={busy}>
            {org.is_active ? tx("Заблокировать") : tx("Разблокировать")}
          </BusyLabel>
        </button>
      </div>
    </div>
  );
}

function InvoiceRow({
  invoice,
  onConfirm,
  onCancel,
  busy,
}: {
  invoice: PlatformInvoice;
  onConfirm: (id: number) => void;
  onCancel: (id: number) => void;
  busy: boolean;
}) {
  const { tx } = useTx();
  const open = invoice.status === "pending" || invoice.status === "awaiting";
  return (
    <div className="rounded-tile bg-tg-secondary-bg/60 p-3" data-testid={`p-invoice-${invoice.id}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-sm font-semibold text-tg-text">{invoice.org_name}</span>
        <span className="text-sm text-tg-hint">{formatMoney(invoice.amount)}</span>
      </div>
      <p className="mt-1 text-xs text-tg-hint">
        {invoice.number} · {tx(invoice.plan_title)} ·{" "}
        {tx(STATUS_LABEL[invoice.status] ?? invoice.status)}
      </p>
      {open && (
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            disabled={busy}
            aria-busy={busy}
            onClick={() => onConfirm(invoice.id)}
            className="min-h-11 flex-1 rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
          >
            <BusyLabel busy={busy}>{tx("Подтвердить оплату")}</BusyLabel>
          </button>
          <button
            type="button"
            disabled={busy}
            aria-busy={busy}
            onClick={() => onCancel(invoice.id)}
            className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg text-sm font-semibold text-tg-hint disabled:opacity-50"
          >
            <BusyLabel busy={busy}>{tx("Отменить")}</BusyLabel>
          </button>
        </div>
      )}
    </div>
  );
}

export default function PlatformScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");

  const summary = useQuery({
    queryKey: ["platform", "summary"],
    queryFn: fetchPlatformSummary,
    staleTime: 30_000,
    retry: false,
  });
  const orgs = useQuery({
    queryKey: ["platform", "orgs", query],
    queryFn: () => fetchPlatformOrgs(query),
    staleTime: 15_000,
    retry: false,
  });
  const invoices = useQuery({
    queryKey: ["platform", "invoices"],
    queryFn: () => fetchPlatformInvoices(),
    staleTime: 15_000,
    retry: false,
  });
  // RUM грузим отдельно от сводки: метрики приходят с реальных устройств и не
  // должны задерживать список клиентов или валить экран при пустом окне.
  const rumQuery = useQuery({
    queryKey: ["platform", "rum"],
    queryFn: fetchPlatformRum,
    staleTime: 60_000,
    retry: false,
  });
  // Онбординг — отдельный запрос по той же причине: цифры по всем клиентам не
  // должны задерживать сводку, а отсутствие ручки (бэкенд ещё не пересобран)
  // не превращает экран в ошибку.
  const onboardingQuery = useQuery({
    queryKey: ["platform", "onboarding"],
    queryFn: fetchPlatformOnboarding,
    staleTime: 60_000,
    retry: false,
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["platform"] });
  };
  const patch = useMutation({
    mutationFn: (vars: { id: number; body: { plan?: string; is_active?: boolean } }) =>
      patchPlatformOrg(vars.id, vars.body),
    onSuccess: refresh,
  });
  const confirm = useMutation({
    mutationFn: (id: number) => confirmPlatformInvoice(id),
    onSuccess: refresh,
  });
  const cancel = useMutation({
    mutationFn: (id: number) => cancelPlatformInvoice(id),
    onSuccess: refresh,
  });

  const busy = patch.isPending || confirm.isPending || cancel.isPending;
  const data = summary.data;
  const awaiting = invoices.data?.items.filter(
    (invoice) => invoice.status === "awaiting" || invoice.status === "pending",
  );
  // Кому звонить: сначала самые низкие доли, только организации с людьми.
  const lagging = (onboardingQuery.data?.orgs ?? [])
    .filter((org) => org.people > 0 && org.first_task_share < 1)
    .sort((a, b) => a.first_task_share - b.first_task_share)
    .slice(0, 5);

  return (
    <SubScreen title={tx("Платформа")} onBack={onBack}>
      {summary.isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-24" />
        </div>
      )}

      {summary.isError && (
        <p className="rounded-tile bg-tg-secondary-bg p-3 text-sm text-tg-hint">
          {tx("Не удалось загрузить платформу — обнови экран.")}
        </p>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Stat label={tx("Организаций")} value={String(data.organizations)} />
            <Stat label={tx("На триале")} value={String(data.on_trial)} />
            <Stat label={tx("Ждут оплаты")} value={String(data.awaiting_invoices)} />
            <Stat label={tx("К оплате")} value={formatMoney(data.unpaid_amount)} />
          </div>

          <div className="space-y-2" data-testid="platform-rum">
            <div className="text-sm font-semibold text-tg-text">
              {tx("Скорость у людей")}
            </div>
            <p className="text-xs text-tg-hint">
              {tx("Core Web Vitals по устройствам за 24 часа: p75 и доля хороших.")}
            </p>
            {rumQuery.data && rumQuery.data.events === 0 && (
              <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
                {tx("Замеров пока нет — появятся после первых сессий.")}
              </p>
            )}
            {Object.entries(rumQuery.data?.metrics ?? {}).map(([name, byDevice]) => (
              <div key={name} className="rounded-tile bg-tg-secondary-bg/60 p-3">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-semibold text-tg-text">{name}</span>
                  <span className="text-2xs uppercase tracking-wide text-tg-hint">p75</span>
                </div>
                {Object.entries(byDevice).map(([device, stat]) => {
                  const label =
                    device === "mobile"
                      ? tx("Телефон")
                      : device === "desktop"
                        ? tx("Компьютер")
                        : tx("Веб");
                  // Цвет — по порогу «хорошо» для конкретной метрики, а не
                  // общий: 0,05 для CLS хорошо, а для LCP те же 0,05 — шум.
                  const good =
                    name === "CLS" ? stat.p75 <= 0.1 : name === "INP" ? stat.p75 <= 200 : stat.p75 <= 2500;
                  return (
                    <div
                      key={device}
                      className="mt-1 flex items-baseline justify-between text-xs"
                    >
                      <span className="text-tg-hint">{label}</span>
                      <span className={good ? "text-tg-link" : "text-red-500"}>
                        {name === "CLS"
                          ? stat.p75.toFixed(2)
                          : `${Math.round(stat.p75)} мс`}{" "}
                        · {tx("{share}% хороших", { share: Math.round(stat.good_share * 100) })}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          {/* Онбординг: не «сколько зарегистрировалось», а «сколько дошло до
              первой закрытой задачи». Ручка считает по фактам; если бэкенд
              ещё не пересобран, блока просто нет — пустая карточка с нулями
              выглядела бы как «никто не доходит». */}
          {onboardingQuery.data && (
            <div className="space-y-2" data-testid="platform-onboarding">
              <div className="text-sm font-semibold text-tg-text">
                {tx("Онбординг")}
              </div>
              <p className="text-xs text-tg-hint">
                {tx(
                  "Доля людей, закрывших первую задачу и первый чек-лист. Считается по фактам, демо исключены.",
                )}
              </p>
              <div className="grid grid-cols-2 gap-2">
                <Stat
                  label={tx("Первая задача")}
                  value={`${Math.round(onboardingQuery.data.totals.first_task_share * 100)}%`}
                />
                <Stat
                  label={tx("Медиана до задачи")}
                  value={
                    onboardingQuery.data.totals.median_hours_to_first_task === null
                      ? "—"
                      : `${onboardingQuery.data.totals.median_hours_to_first_task} ч`
                  }
                />
                <Stat
                  label={tx("Первый чек-лист")}
                  value={`${Math.round(onboardingQuery.data.totals.first_checklist_share * 100)}%`}
                />
                <Stat
                  label={tx("Дошли до конца")}
                  value={`${Math.round(onboardingQuery.data.totals.onboarding_share * 100)}%`}
                />
              </div>
              {lagging.length > 0 && (
                <div className="space-y-1">
                  {lagging.map((org) => (
                    <div
                      key={org.org_id}
                      className="flex items-baseline justify-between rounded-tile bg-tg-secondary-bg/60 p-2 text-xs"
                    >
                      <span className="min-w-0 truncate text-tg-text">{org.name}</span>
                      <span className="shrink-0 text-tg-hint">
                        {Math.round(org.first_task_share * 100)}% ·{" "}
                        {org.people} {tx("чел.")}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="space-y-2">
            <div className="text-sm font-semibold text-tg-text">{tx("Клиенты")}</div>
            <FormField
              id="platform-search"
              label={tx("Поиск по названию или коду")}
              labelClassName="sr-only"
            >
              {(field) => (
                <input
                  {...field}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={tx("Поиск по названию или коду")}
                  className="min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text"
                />
              )}
            </FormField>
            {(orgs.data?.items ?? []).map((org) => (
              <OrgRow
                key={org.id}
                org={org}
                plans={data.plans}
                busy={busy}
                onPlan={(id, plan) => patch.mutate({ id, body: { plan } })}
                onToggle={(row) =>
                  patch.mutate({ id: row.id, body: { is_active: !row.is_active } })
                }
              />
            ))}
            {orgs.data?.items.length === 0 && (
              <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
                {tx("Ничего не найдено")}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <div className="text-sm font-semibold text-tg-text">
              {tx("Счета клиентов")}
            </div>
            {(awaiting ?? []).map((invoice) => (
              <InvoiceRow
                key={invoice.id}
                invoice={invoice}
                busy={busy}
                onConfirm={(id) => confirm.mutate(id)}
                onCancel={(id) => cancel.mutate(id)}
              />
            ))}
            {awaiting?.length === 0 && (
              <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
                {tx("Счетов, ждущих подтверждения, нет.")}
              </p>
            )}
          </div>
        </>
      )}
    </SubScreen>
  );
}
