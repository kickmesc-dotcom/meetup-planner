/**
 * Оплата и счета организации (B2B_PLATFORM_PLAN, шаг 4.2).
 *
 * Зачем экран, если счёт можно выписать где-то ещё. Смысл витрины — ответить на
 * вопрос «сколько и за что» до разговора с поддержкой. Без него тариф
 * поднимается только письмом «здравствуйте, а сколько стоит», и половина
 * клиентов до письма не доходит.
 *
 * Почему кнопка называется «Выставить счёт», а не «Оплатить». Платёжного
 * провайдера подключает владелец продукта; до этого «Оплатить» — обещание
 * действия, которого нет. Счёт же существует: номер, сумма, срок, статус.
 *
 * Почему «Я оплатил» ничего не продлевает. Продление подтверждает платформа
 * (или платёжный провайдер). Кнопка, которая продлевает подписку сама, была бы
 * бесплатным безлимитом, поэтому она лишь переводит счёт в «ждёт
 * подтверждения».
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelInvoice,
  createInvoice,
  fetchOrgBilling,
  requestInvoicePaid,
  type OrgInvoice,
} from "@/api/orgs";
import { Skeleton } from "@/components/Skeleton";
import { BusyLabel } from "@/components/BusyLabel";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";
import { formatDate, formatMoney } from "@/lib/format";

/** Подпись статуса. Коды — из `services/billing.py`, текст живёт здесь. */
const STATUS_LABEL: Record<string, string> = {
  pending: "Ожидает оплаты",
  awaiting: "Ждёт подтверждения",
  paid: "Оплачен",
  canceled: "Отменён",
  expired: "Просрочен",
};

function InvoiceRow({
  invoice,
  onPaid,
  onCancel,
  busy,
}: {
  invoice: OrgInvoice;
  onPaid: (id: number) => void;
  onCancel: (id: number) => void;
  busy: boolean;
}) {
  const { tx } = useTx();
  const open = invoice.status === "pending" || invoice.status === "awaiting";
  const title =
    invoice.period === "year" ? tx("Год") : tx("Месяц");
  return (
    <div className="rounded-tile bg-tg-secondary-bg/60 p-3" data-testid={`invoice-${invoice.id}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-tg-text">{invoice.number}</span>
        <span className="text-sm text-tg-hint">{formatMoney(invoice.amount)}</span>
      </div>
      <p className="mt-1 text-xs text-tg-hint">
        {tx(invoice.plan_title)} · {title} · {tx(STATUS_LABEL[invoice.status] ?? invoice.status)}
      </p>
      {invoice.status === "pending" && (
        <p className="mt-1 text-xs text-tg-hint">
          {tx("Оплатить до {date}", { date: formatDate(invoice.expires_at) })}
        </p>
      )}
      {invoice.status === "paid" && invoice.period_end && (
        <p className="mt-1 text-xs text-tg-hint">
          {tx("Оплачено до {date}", { date: formatDate(invoice.period_end) })}
        </p>
      )}
      {open && (
        <div className="mt-2 flex gap-2">
          {invoice.status === "pending" && (
            <button
              type="button"
              disabled={busy}
              aria-busy={busy}
              onClick={() => onPaid(invoice.id)}
              className="min-h-11 flex-1 rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
            >
              <BusyLabel busy={busy}>{tx("Я оплатил")}</BusyLabel>
            </button>
          )}
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

export default function BillingScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["org-billing"],
    queryFn: fetchOrgBilling,
    staleTime: 30_000,
    retry: false,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["org-billing"] });
  const create = useMutation({
    mutationFn: (body: { plan: string; period: string }) => createInvoice(body),
    onSuccess: refresh,
  });
  const paid = useMutation({
    mutationFn: (id: number) => requestInvoicePaid(id),
    onSuccess: refresh,
  });
  const cancel = useMutation({
    mutationFn: (id: number) => cancelInvoice(id),
    onSuccess: refresh,
  });

  const data = q.data;
  const busy = paid.isPending || cancel.isPending;

  return (
    <SubScreen title={tx("Оплата и счета")} onBack={onBack}>
      {q.isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      )}

      {q.isError && (
        <p className="rounded-tile bg-tg-secondary-bg p-3 text-sm text-tg-hint">
          {tx("Не удалось загрузить счета — обнови экран.")}
        </p>
      )}

      {data && (
        <>
          <div className="rounded-tile bg-tg-secondary-bg/60 p-3">
            <div className="text-2xs uppercase tracking-wide text-tg-hint">
              {tx("Ваш тариф")}
            </div>
            <div className="text-base font-semibold text-tg-text">{tx(data.plan.title)}</div>
            <p className="mt-1 text-xs text-tg-hint" data-testid="subscription-line">
              {data.plan.subscription_expired
                ? tx(
                    "Оплата закончилась. Люди и данные на месте, но новых сотрудников и подразделений добавить нельзя.",
                  )
                : data.plan.plan_ends_at
                  ? tx("Подписка оплачена до {date}", {
                      date: formatDate(data.plan.plan_ends_at),
                    })
                  : tx("Оплата не требуется: тариф действует без срока.")}
            </p>
          </div>

          <div className="space-y-2">
            <div className="text-sm font-semibold text-tg-text">{tx("Тарифы")}</div>
            <p className="text-xs text-tg-hint">
              {tx("Цена за месяц или за год. Год — десять месяцев.")}
            </p>
            {data.prices.map((price) => (
              <div
                key={price.code}
                className="rounded-tile bg-tg-secondary-bg/60 p-3"
                data-testid={`price-${price.code}`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-semibold text-tg-text">{tx(price.title)}</span>
                  <span className="text-sm text-tg-hint">{formatMoney(price.price_month)}</span>
                </div>
                <p className="mt-1 text-xs text-tg-hint">
                  {tx("До {seats} сотрудников, {branches} подразделений", {
                    seats: price.seats,
                    branches: price.branches,
                  })}
                </p>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    disabled={create.isPending}
                    aria-busy={create.isPending}
                    onClick={() => create.mutate({ plan: price.code, period: "month" })}
                    className="min-h-11 flex-1 rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
                  >
                    {tx("Счёт за месяц")}
                  </button>
                  <button
                    type="button"
                    disabled={create.isPending}
                    aria-busy={create.isPending}
                    onClick={() => create.mutate({ plan: price.code, period: "year" })}
                    className="min-h-11 flex-1 rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
                  >
                    {tx("Счёт за год · {amount}", { amount: formatMoney(price.price_year) })}
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="space-y-2">
            <div className="text-sm font-semibold text-tg-text">{tx("Счета")}</div>
            {data.invoices.length === 0 && (
              <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
                {tx("Счетов пока нет — выставьте первый на нужный тариф.")}
              </p>
            )}
            {data.invoices.map((invoice) => (
              <InvoiceRow
                key={invoice.id}
                invoice={invoice}
                busy={busy}
                onPaid={(id) => paid.mutate(id)}
                onCancel={(id) => cancel.mutate(id)}
              />
            ))}
          </div>

          <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
            {tx(
              "Оплата по счёту: после перевода нажмите «Я оплатил» — мы подтвердим и продлим подписку. Списаний с карты нет.",
            )}
          </p>
        </>
      )}
    </SubScreen>
  );
}
