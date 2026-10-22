import { useQuery } from "@tanstack/react-query";
import { fetchEmployeeCard, type HrProfileCard } from "@/api/hr";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { CardSkeleton } from "@/components/Skeleton";
import Badge from "@/features/hr/Badge";
import { departmentTone, personTone } from "@/features/hr/tone";
import { haptic } from "@/tg/webapp";

/**
 * Карточка коллеги: тап по имени в ленте, табеле или «Команде».
 *
 * Правило видимости решает сервер, экран его только показывает:
 *  • свой профиль и профиль подчинённого руководителю — целиком;
 *  • профиль коллеги — если человек не закрыл его в своих настройках;
 *  • закрытый — имя, отдел и плашка, без цифр и истории.
 *
 * Админ может зайти в закрытый профиль так же, как руководитель: сервер
 * возвращает `can_view=true`, и экран ничего не блокирует.
 */
export default function EmployeeCardSheet({
  employeeId,
  onClose,
}: {
  employeeId: number;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["hr-profile-card", employeeId],
    queryFn: () => fetchEmployeeCard(employeeId),
    staleTime: 30_000,
  });

  return (
    <div
      className="fixed inset-0 z-50 mx-auto flex w-full max-w-[560px] flex-col bg-tg-bg"
      role="dialog"
      aria-modal="true"
      aria-label="Карточка сотрудника"
    >
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg/60 text-tg-link"
          aria-label="Закрыть карточку"
        >
          <Icon name="back" size={20} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-tg-text">
            {q.data?.display_name ?? "Карточка сотрудника"}
          </div>
          <div className="truncate text-xs text-tg-hint">
            {q.data?.department_name ?? "что делал на смене"}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {q.isLoading && (
          <div className="space-y-3">
            <CardSkeleton />
            <CardSkeleton />
          </div>
        )}
        {q.isError && (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}
        {q.data && <CardBody card={q.data} />}
      </div>
    </div>
  );
}

function CardBody({ card }: { card: HrProfileCard }) {
  const person = personTone(card.employee_id);
  const dept = departmentTone(card.department_id);

  return (
    <div className="space-y-4">
      <section className="rounded-card bg-tg-secondary-bg/60 p-3">
        <div className="flex items-center gap-3">
          <div
            className="grid h-12 w-12 shrink-0 place-items-center rounded-full text-tg-hint"
            style={{ backgroundColor: person.soft, border: `1px solid ${person.border}` }}
            aria-hidden
          >
            <Icon name="profile" size={24} />
          </div>
          <div className="min-w-0 flex-1">
            {/* Имя отдельной строкой и переносится: раньше плашка в той же
                строке обрезала его до «Серж-…». */}
            <div className="break-words text-base font-semibold text-tg-text">
              {card.display_name}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge text={card.badge} emoji={card.badge_emoji} demo={card.is_demo} />
              {card.department_name && (
                <span
                  className="inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium text-tg-text"
                  style={{ backgroundColor: dept.soft, border: `1px solid ${dept.border}` }}
                >
                  {card.department_name}
                </span>
              )}
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              {card.role_label}
              {card.position ? ` · ${card.position}` : ""}
            </div>
          </div>
        </div>
      </section>

      {!card.can_view ? (
        <section className="rounded-card bg-tg-secondary-bg/60 p-4 text-center">
          <div className="text-2xl" aria-hidden>
            🔒
          </div>
          <div className="mt-2 text-sm font-medium text-tg-text">
            Профиль закрыт
          </div>
          <p className="mt-1 text-xs text-tg-hint">
            {card.is_self
              ? "Тебя никто не видит в карточке — открой профиль в настройках."
              : "Человек сам решает, показывать ли активность и цифры. Руководитель и администратор видят её всегда."}
          </p>
        </section>
      ) : (
        <>
          <section className="rounded-card bg-tg-secondary-bg/60 p-3">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold text-tg-text">Опыт</h2>
              <span className="text-xs text-tg-hint">
                {card.rank_emoji} {card.rank_title}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <Stat label="Всего опыта" value={`${card.xp} XP`} />
              <Stat label="За неделю" value={`${card.week_xp} XP`} />
              <Stat
                label="Место в неделе"
                value={
                  card.week_place && card.week_total
                    ? `${card.week_place} из ${card.week_total}`
                    : "—"
                }
              />
              <Stat label="Смен закрыто" value={String(card.shifts_done)} />
              <Stat label="Пунктов чек-листа" value={String(card.checklist_items)} />
              <Stat label="Поручений закрыто" value={String(card.tasks_done)} />
            </div>
          </section>

          <section>
            <h2 className="px-1 text-2xs font-medium uppercase tracking-wide text-tg-hint">
              Последние действия
            </h2>
            {card.activity.length === 0 ? (
              <p className="mt-2 rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
                Пока пусто: человек ещё ничего не отмечал.
              </p>
            ) : (
              <ul className="mt-1 divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-card bg-tg-secondary-bg/40">
                {card.activity.map((item) => (
                  <li key={`${item.kind}-${item.ref_id}-${item.at}`} className="px-3 py-2">
                    <div className="text-sm text-tg-text break-words">{item.text}</div>
                    <div className="mt-0.5 text-xs text-tg-hint">
                      {formatWhen(item.at)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      {!card.profile_open && card.can_view && !card.is_self && (
        <p className="px-1 text-2xs text-tg-hint">
          Профиль закрыт для коллег, но тебе он виден: ты руководитель или
          администратор.
        </p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-tile bg-tg-bg/50 p-2">
      <div className="text-tg-hint">{label}</div>
      <div className="tabular-nums text-tg-text">{value}</div>
    </div>
  );
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
