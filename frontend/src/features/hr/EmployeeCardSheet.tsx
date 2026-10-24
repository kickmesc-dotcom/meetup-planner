import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchEmployeeCard, type HrProfileCard } from "@/api/hr";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import MediaLightbox from "@/components/MediaLightbox";
import { CardSkeleton } from "@/components/Skeleton";
import Badge from "@/features/hr/Badge";
import { departmentTone, personTone } from "@/features/hr/tone";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";
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
  const { tx } = useTx();
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
      aria-label={tx("Карточка сотрудника")}
    >
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg/60 text-tg-link"
          aria-label={tx("Закрыть карточку")}
        >
          <Icon name="back" size={20} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-tg-text">
            {q.data?.display_name ?? tx("Карточка сотрудника")}
          </div>
          <div className="truncate text-xs text-tg-hint">
            {q.data?.department_name ?? tx("что делал на смене")}
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
  const { tx } = useTx();
  const person = personTone(card.employee_id);
  const dept = departmentTone(card.department_id);
  const [lightbox, setLightbox] = useState<string | null>(null);

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
          <Icon name="lock" size={26} className="mx-auto text-tg-hint" />
          <div className="mt-2 text-sm font-medium text-tg-text">{tx("Профиль закрыт")}</div>
          <p className="mt-1 text-xs text-tg-hint">
            {card.is_self
              ? tx("Тебя никто не видит в карточке — открой профиль в настройках.")
              : tx("Человек сам решает, показывать ли активность и цифры. Руководитель и администратор видят её всегда.")}
          </p>
        </section>
      ) : (
        <>
          <section className="rounded-card bg-tg-secondary-bg/60 p-3">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold text-tg-text">{tx("Опыт")}</h2>
              <span className="text-xs text-tg-hint">
                {card.rank_emoji} {card.rank_title}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <Stat label={tx("Всего опыта")} value={`${card.xp} XP`} />
              <Stat label={tx("За неделю")} value={`${card.week_xp} XP`} />
              <Stat
                label={tx("Место в неделе")}
                value={
                  card.week_place && card.week_total
                    ? tx("{place} из {total}", {
                        place: card.week_place,
                        total: card.week_total,
                      })
                    : "—"
                }
              />
              <Stat label={tx("Смен закрыто")} value={String(card.shifts_done)} />
              <Stat label={tx("Пунктов чек-листа")} value={String(card.checklist_items)} />
              <Stat label={tx("Поручений закрыто")} value={String(card.tasks_done)} />
            </div>
          </section>

          {/* Два «живых» блока карточки: чем человек занят прямо сейчас.
              Оба отключаются в его профиле, а руководство может запретить
              отключение — тогда блок показывается всегда и честно об этом
              говорит, если данные скрыты не им. */}
          <section className="grid grid-cols-2 gap-2">
            <div className="rounded-card bg-tg-secondary-bg/60 p-3">
              <div className="flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-tg-hint">
                <Icon name="clock" size={12} />
                {tx("Последний вход")}
              </div>
              {!card.show_last_seen ? (
                <div className="mt-1 text-xs text-tg-hint">
                  {tx("Скрыто настройками профиля")}
                </div>
              ) : card.last_seen_at ? (
                <div className="mt-1 text-sm text-tg-text">
                  {lastSeenLabel(card.last_seen_at, tx)}
                </div>
              ) : (
                <div className="mt-1 text-xs text-tg-hint">
                  {tx("Ещё не заходил(а)")}
                </div>
              )}
            </div>
            <div className="rounded-card bg-tg-secondary-bg/60 p-3">
              <div className="flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-tg-hint">
                <Icon name="camera" size={12} />
                {tx("Последнее медиа")}
              </div>
              {!card.show_last_media ? (
                <div className="mt-1 text-xs text-tg-hint">
                  {tx("Скрыто настройками профиля")}
                </div>
              ) : card.last_media ? (
                <button
                  type="button"
                  onClick={() => setLightbox(card.last_media!.url)}
                  className="mt-1 block w-full overflow-hidden rounded-tile active:opacity-80"
                  aria-label={tx("Открыть последнее фото")}
                >
                  <img
                    src={card.last_media.url}
                    alt={card.last_media.caption}
                    className="h-24 w-full object-cover"
                    loading="lazy"
                  />
                  <span className="mt-1 block truncate text-2xs text-tg-hint">
                    {card.last_media.caption} · {formatWhen(card.last_media.at)}
                  </span>
                </button>
              ) : (
                <div className="mt-1 text-xs text-tg-hint">
                  {tx("Фотоотчётов пока нет")}
                </div>
              )}
            </div>
          </section>

          <section>
            <h2 className="px-1 text-2xs font-medium uppercase tracking-wide text-tg-hint">{tx("Последние действия")}</h2>
            {card.activity.length === 0 ? (
              <p className="mt-2 rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">{tx("Пока пусто: человек ещё ничего не отмечал.")}</p>
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
        <p className="px-1 text-2xs text-tg-hint">{tx(
          "Профиль закрыт для коллег, но тебе он виден: ты руководитель или администратор.",
        )}</p>
      )}

      {lightbox && (
        <MediaLightbox src={lightbox} onClose={() => setLightbox(null)} />
      )}
    </div>
  );
}

/** «10 минут назад» — карточку открывают, чтобы понять «он ещё здесь?». */
function lastSeenLabel(
  iso: string,
  tx: (text: string, params?: Record<string, string | number>) => string,
): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60_000));
  if (minutes < 1) return tx("только что");
  if (minutes < 60) return tx("{count} мин назад", { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return tx("{count} ч назад", { count: hours });
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
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
