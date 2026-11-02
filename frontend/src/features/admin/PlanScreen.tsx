/**
 * Тариф и лимиты организации (B2B_PLATFORM_PLAN, шаг 4.1).
 *
 * Зачем экран, если лимиты проверяет сервер. Отказ без объяснения — это
 * «приглашение не создалось, попробуйте ещё раз»: руководитель будет пробовать,
 * пока не напишет в поддержку. Экран отвечает заранее: сколько мест занято,
 * сколько осталось и что делать, когда осталось ноль.
 *
 * Почему тариф не переключается здесь. Смена тарифа — это деньги (шаг 4.2):
 * кнопка «повысить» без оплаты дала бы бесплатный безлимит. Пока лимит
 * поднимается вручную, и экран честно об этом говорит.
 *
 * Почему занятое место считает сервер, а не клиент. Приглашение уже обещает
 * место, демо-профили его не занимают, а погашенные отделы не считаются. Эти
 * три правила живут в одном месте (`services/billing.py`), и дублировать их в
 * браузере значило бы разойтись на первой же правке.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchOrgPlan } from "@/api/orgs";
import { Skeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";
import { useUI } from "@/store/ui";
import { useTx } from "@/i18n";

function Meter({
  label,
  used,
  limit,
  hint,
}: {
  label: string;
  used: number;
  limit: number;
  hint: string;
}) {
  const { tx } = useTx();
  const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const full = used >= limit;
  return (
    <div className="rounded-tile bg-tg-secondary-bg/60 p-3" data-testid={`meter-${label}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-tg-text">{label}</span>
        <span className={full ? "text-sm font-semibold text-red-500" : "text-sm text-tg-hint"}>
          {tx("{used} из {limit}", { used, limit })}
        </span>
      </div>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-tg-bg"
        role="progressbar"
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={limit}
      >
        <div
          className={full ? "h-full bg-red-500" : "h-full bg-tg-link"}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-tg-hint">{tx(hint)}</p>
    </div>
  );
}

export default function PlanScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const setSection = useUI((s) => s.setAdminSection);
  const q = useQuery({
    queryKey: ["org-plan"],
    queryFn: fetchOrgPlan,
    staleTime: 60_000,
    retry: false,
  });

  const plan = q.data;

  return (
    <SubScreen title={tx("Тариф и лимиты")} onBack={onBack}>
      {q.isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      )}

      {q.isError && (
        <p className="rounded-tile bg-tg-secondary-bg p-3 text-sm text-tg-hint">
          {tx("Не удалось узнать тариф — обнови экран.")}
        </p>
      )}

      {plan && (
        <>
          <div className="rounded-tile bg-tg-secondary-bg/60 p-3">
            <div className="flex items-baseline justify-between gap-2">
              <div>
                <div className="text-2xs uppercase tracking-wide text-tg-hint">
                  {tx("Ваш тариф")}
                </div>
                <div className="text-base font-semibold text-tg-text">{tx(plan.title)}</div>
              </div>
              {plan.trial_days_left !== null && (
                <span className="rounded-full bg-tg-link/15 px-2 py-1 text-2xs font-semibold text-tg-link">
                  {tx("Осталось {days} дн.", { days: plan.trial_days_left })}
                </span>
              )}
            </div>
            {plan.trial_expired && (
              <p
                className="mt-2 rounded-tile bg-red-500/10 p-2 text-xs text-red-600"
                data-testid="trial-expired"
              >
                {tx(
                  "Пробный период закончился. Люди и данные на месте, но новых сотрудников и подразделений добавить нельзя.",
                )}
              </p>
            )}
          </div>

          <Meter
            label={tx("Сотрудники")}
            used={plan.seats_used}
            limit={plan.seats_limit}
            hint="Считаются живые люди и непринятые приглашения: ссылка уже обещает место. Демо-профили места не занимают."
          />
          <Meter
            label={tx("Подразделения")}
            used={plan.branches_used}
            limit={plan.branches_limit}
            hint="Активные отделы и филиалы. Погашенное подразделение место освобождает."
          />

          <div className="space-y-2 rounded-tile bg-tg-secondary-bg/60 p-3">
            <div className="text-sm font-semibold text-tg-text">{tx("Когда места кончатся")}</div>
            <p className="text-xs text-tg-hint">
              {tx(
                "Смена и работа продолжается: закрывается только добавление новых людей и подразделений. Чтобы поднять лимит, напишите нам — переключим тариф вручную.",
              )}
            </p>
            <button
              type="button"
              onClick={() => setSection("invitations")}
              className="min-h-11 w-full rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link"
            >
              {tx("Пригласить человека")}
            </button>
          </div>
        </>
      )}
    </SubScreen>
  );
}
