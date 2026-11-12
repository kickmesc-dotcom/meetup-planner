/**
 * Пакет отрасли: что именно получит организация (план, фаза 3, шаг 3.2).
 *
 * Зачем отдельный экран, если отрасль выбирается в мастере. Мастер проходят
 * один раз, а «у нас всё равно про залы» — это вопрос, который возникает на
 * второй день, когда сотрудник открывает вкладку и читает чужое слово. Здесь
 * видно содержимое пакета до нажатия и можно применить его ещё раз.
 *
 * Почему показано содержимое, а не только название. «Применить пакет салона»
 * без списка — лотерея: человек не знает, заменит ли это его чек-листы и
 * переименует ли залы. Поэтому на экране слова, пункты и цифры, а кнопка
 * «Применить» рядом с предупреждением, что уже заведённое не тронется.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyPack, fetchPack, type Pack, type PackApplyResult } from "@/api/packs";
import { humanizeApiError } from "@/api/client";
import Icon, { InlineIcon } from "@/components/Icon";
import { Skeleton } from "@/components/Skeleton";
import { BusyLabel } from "@/components/BusyLabel";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";

interface Props {
  onBack: () => void;
}

/** Подписи для пар «одно / много»: код термина → что это за слово. */
const TERM_PAIRS: { one: string; many: string; label: string }[] = [
  { one: "term.hall.one", many: "term.hall.many", label: "Объект работы" },
  { one: "term.shift.one", many: "term.shift.many", label: "Рабочий день" },
  { one: "term.task.one", many: "term.task.many", label: "Поручение" },
];

/** Веса опыта в человеческих словах: ключ `admin_config` → подпись. */
const KPI_LABELS: Record<string, string> = {
  xp_checklist_item: "Опыт за пункт чек-листа",
  xp_shift_done: "Опыт за закрытую смену",
  xp_task: "Опыт за закрытое поручение",
  xp_on_time: "Надбавка за срок",
  min_xp_winner: "Минимум для «сотрудника недели»",
};

function TermTable({ pack }: { pack: Pack }) {
  const { tx } = useTx();
  const rows = TERM_PAIRS.map((pair) => ({
    label: pair.label,
    one: pack.terms[pair.one],
    many: pack.terms[pair.many],
  })).filter((row) => row.one || row.many);
  if (!rows.length) return null;
  return (
    <div className="space-y-1">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-2">
          <span className="text-2xs uppercase tracking-wide text-tg-hint">
            {tx(row.label)}
          </span>
          <span className="text-xs text-tg-text">
            {row.many || row.one}
            {row.one && row.many ? (
              <span className="text-tg-hint"> · {tx("один")} — {row.one}</span>
            ) : null}
          </span>
        </div>
      ))}
    </div>
  );
}

function PackCard({ pack }: { pack: Pack }) {
  const { tx } = useTx();
  return (
    <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-3">
      <div className="flex items-center gap-2">
        <Icon name="layout" size={18} className="text-tg-link" />
        <span className="text-sm font-semibold text-tg-text">{pack.title}</span>
      </div>
      <div className="text-xs text-tg-hint">{pack.why}</div>

      <TermTable pack={pack} />

      {pack.positions.length > 0 && (
        <div className="space-y-1">
          <div className="text-2xs uppercase tracking-wide text-tg-hint">
            {tx("Должности")}
          </div>
          <div className="flex flex-wrap gap-1">
            {pack.positions.map((position) => (
              <span
                key={position}
                className="rounded-tile bg-tg-secondary-bg px-2 py-0.5 text-2xs text-tg-text"
              >
                {position}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1">
        <div className="text-2xs uppercase tracking-wide text-tg-hint">
          {tx("Чек-листы")} · {tx("{n} пунктов", { n: pack.checklist_items })}
        </div>
        <ul className="space-y-0.5">
          {[...pack.opening_items, ...pack.closing_items].map((item) => (
            <li key={item} className="text-2xs text-tg-hint">
              · {item}
            </li>
          ))}
        </ul>
      </div>

      {Object.keys(pack.kpi).length > 0 && (
        <div className="space-y-1">
          <div className="text-2xs uppercase tracking-wide text-tg-hint">
            {tx("Веса опыта")}
          </div>
          {Object.entries(pack.kpi).map(([key, value]) => (
            <div key={key} className="flex items-baseline justify-between gap-2">
              <span className="text-2xs text-tg-hint">
                {tx(KPI_LABELS[key] ?? key)}
              </span>
              <span className="text-xs text-tg-text">{value}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function PackScreen({ onBack }: Props) {
  const { tx } = useTx();
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["org-pack"],
    queryFn: fetchPack,
    staleTime: 60_000,
    retry: false,
  });

  const mut = useMutation({
    mutationFn: (force: boolean) => applyPack({ force_terms: force }),
    onSuccess: async (out: PackApplyResult) => {
      haptic("success");
      // Термины и чек-листы живут в разных кэшах: без сброса экран сотрудника
      // остался бы с прежними словами до перезапуска.
      void qc.invalidateQueries({ queryKey: ["app-texts"] });
      void qc.invalidateQueries({ queryKey: ["hr-departments"] });
      void qc.invalidateQueries({ queryKey: ["checklist"] });
      void qc.invalidateQueries({ queryKey: ["org-setup"] });
      await showAlert(
        tx(
          "Готово: слова — {terms}, чек-листы — {templates}.",
          { terms: out.terms_set, templates: out.templates_created },
        ) +
          (out.kpi_updated ? ` ${tx("Веса опыта обновлены.")}` : ""),
      );
    },
    onError: async (e) => {
      haptic("error");
      await showAlert(humanizeApiError(e));
    },
  });

  const pack = q.data?.pack;
  const canApply = q.data?.can_apply ?? false;
  const busy = q.isPending || mut.isPending;

  return (
    <SubScreen
      title={tx("Пакет отрасли")}
      subtitle={tx("Термины, чек-листы, KPI и должности")}
      onBack={onBack}
    >
      {q.isError && (
        <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
          <InlineIcon name="alert" />
          {humanizeApiError(q.error)}
        </div>
      )}

      {q.isPending && <Skeleton className="h-24 w-full" />}

      {pack && <PackCard pack={pack} />}

      {pack && (
        <section className="rounded-card bg-tg-secondary-bg/40 p-3 space-y-2">
          <div className="text-2xs uppercase tracking-wide text-tg-hint">
            {tx("Что изменится")}
          </div>
          <p className="text-xs text-tg-hint">
            {tx(
              "Пакет добавляет то, чего ещё нет: слова, пару чек-листов на каждое подразделение и подсказки должностей. Переименованное и отредактированное он не трогает.",
            )}
          </p>
          <p className="text-xs text-tg-hint">
            {tx(
              "Веса опыта задаются только на чистой установке: там, где руководитель уже настроил их сам, пакет молчит, чтобы не пересчитать чужой опыт.",
            )}
          </p>
          <button
            type="button"
            disabled={busy || !canApply}
            aria-busy={busy}
            onClick={() => {
              haptic("light");
              mut.mutate(false);
            }}
            className="w-full rounded-tile bg-tg-link px-3 py-2 text-sm font-semibold text-white press disabled:opacity-50"
          >
            <BusyLabel busy={busy}>{tx("Применить пакет")}</BusyLabel>
          </button>
          <button
            type="button"
            disabled={busy || !canApply}
            aria-busy={busy}
            onClick={async () => {
              const ok = await showConfirm(
                tx(
                  "Вернуть слова пакета поверх ваших правок? Переименованные подписи будут заменены.",
                ),
              );
              if (ok) mut.mutate(true);
            }}
            className="w-full rounded-tile bg-tg-secondary-bg px-3 py-2 text-xs text-tg-text press disabled:opacity-50"
          >
            <BusyLabel busy={busy}>{tx("Вернуть слова пакета")}</BusyLabel>
          </button>
          {!canApply && (
            <div className="text-2xs text-tg-hint">
              {tx("Применять пакет может руководитель или администратор организации.")}
            </div>
          )}
        </section>
      )}
    </SubScreen>
  );
}
