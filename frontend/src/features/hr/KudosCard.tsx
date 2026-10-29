import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchKudosPeople,
  fetchKudosWeek,
  giveKudos,
  kudosErrorText,
} from "@/api/kudos";
import Icon from "@/components/Icon";
import { Skeleton } from "@/components/Skeleton";
import {
  TRANSLATED_MARK_INLINE,
  TranslateBlockButton,
  TranslateFailedNotice,
  useBatchTranslate,
} from "@/components/TranslatableBlock";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";

/**
 * «Спасибо коллеге» (план, 8.4).
 *
 * Карточка живёт в ленте и говорит три вещи, которые иначе пришлось бы
 * собирать глазами: сколько благодарностей человек получил за неделю, где он
 * в недельном топе и сколько ещё может сказать сегодня.
 *
 * Правила («кому можно», «сколько раз») считает сервер — здесь их нет. Это не
 * лень, а защита: копия правил в интерфейсе рано или поздно разойдётся с
 * сервером, и человек получит отказ там, где кнопка была активна.
 *
 * Отдельно про ожидание: карточка появляется каркасом и не «прыгает», когда
 * приходит ответ (каркас занимает ту же высоту). Это тот же принцип, что и у
 * остальных экранов: сначала форма, потом числа.
 */
export default function KudosCard() {
  const { tx } = useTx();
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["kudos-week"],
    queryFn: fetchKudosWeek,
    staleTime: 60_000,
  });

  if (q.isLoading) {
    return (
      <section className="rounded-card bg-tg-secondary-bg/60 p-3" aria-busy="true">
        <Skeleton className="h-4 w-40" />
        <div className="mt-3 grid grid-cols-3 gap-2">
          <Skeleton className="h-12 rounded-tile" />
          <Skeleton className="h-12 rounded-tile" />
          <Skeleton className="h-12 rounded-tile" />
        </div>
      </section>
    );
  }

  // Ошибка здесь не закрывает ленту: карточка — дополнение, а не экран.
  // Поэтому вместо ErrorState с кнопкой «повторить» — одна честная строка.
  if (q.isError || !q.data) {
    return (
      <section className="rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
        {tx("Благодарности сейчас не загрузились — остальное в ленте работает.")}
      </section>
    );
  }

  const week = q.data;
  // Топ из одной строки — это сам смотрящий (сотрудник видит только себя):
  // «топ» из одного человека читался бы как шутка, поэтому показываем числа.
  const showsTop = !(week.top.length === 1 && week.my_place === 1);

  return (
    <section className="rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-tg-text">
          {tx("Спасибо на этой неделе")}
        </h2>
        {week.my_place !== null && (
          <span className="shrink-0 text-xs text-tg-hint">
            {tx("Ты на {place} месте", { place: week.my_place })}
          </span>
        )}
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2 text-center">
        <Stat label={tx("Получено")} value={String(week.received)} />
        <Stat label={tx("Сказал(а)")} value={String(week.given)} />
        <Stat
          label={tx("Осталось сегодня")}
          value={`${week.today_left}/${week.max_per_day}`}
        />
      </div>

      {showsTop && (
        <ul className="mt-3 space-y-1">
          {week.top.map((row, index) => (
            <li
              key={row.employee_id}
              className="flex items-center gap-2 rounded-tile bg-tg-bg/50 px-2 py-1.5"
            >
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-tg-secondary-bg text-2xs font-semibold text-tg-hint">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-tg-text">
                {row.display_name}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-tg-hint">
                {tx("{count} спасибо", { count: row.count })}
              </span>
            </li>
          ))}
        </ul>
      )}

      {week.can_thank === 0 ? (
        <p className="mt-3 text-xs text-tg-hint">
          {tx("Пока некого благодарить — коллег в твоём подразделении нет.")}
        </p>
      ) : (
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setOpen(true);
          }}
          className="mt-3 flex min-h-11 w-full items-center justify-center gap-1.5 rounded-tile bg-tg-bg/70 text-sm font-medium text-tg-link"
        >
          <Icon name="sparkles" size={16} />
          {tx("Сказать спасибо")}
        </button>
      )}

      {open && <KudosSheet onClose={() => setOpen(false)} />}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-tile bg-tg-bg/50 p-2">
      <div className="text-2xs text-tg-hint">{label}</div>
      <div className="tabular-nums text-sm font-semibold text-tg-text">{value}</div>
    </div>
  );
}

/**
 * Лист «сказать спасибо»: выбор коллеги и одна фраза.
 *
 * Фраза необязательна — механика не должна требовать объяснения, иначе ею
 * перестанут пользоваться. Список людей приходит с сервера уже отфильтрованным
 * по правилу видимости, поэтому здесь нет фильтра «а можно ли ему».
 */
export function KudosSheet({
  onClose,
  initialEmployeeId = null,
}: {
  onClose: () => void;
  /** Открыть с уже выбранным человеком (кнопка в карточке коллеги). */
  initialEmployeeId?: number | null;
}) {
  const { tx } = useTx();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number | null>(initialEmployeeId);
  const [message, setMessage] = useState("");
  const [needle, setNeedle] = useState("");

  const peopleQ = useQuery({
    queryKey: ["kudos-people"],
    queryFn: fetchKudosPeople,
    staleTime: 5 * 60 * 1000,
  });

  const send = useMutation({
    mutationFn: () => giveKudos(selected as number, message),
    onSuccess: () => {
      haptic("success");
      // Свежая благодарность — это ещё и новая запись в ленте, поэтому
      // обновляем обе: иначе человек увидит «спасибо отправлено» и старую ленту.
      void queryClient.invalidateQueries({ queryKey: ["kudos-week"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-feed"] });
      onClose();
    },
  });

  const needleLower = needle.trim().toLowerCase();
  const people = (peopleQ.data ?? []).filter(
    (person) =>
      needleLower === "" ||
      person.display_name.toLowerCase().includes(needleLower) ||
      (person.position ?? "").toLowerCase().includes(needleLower),
  );

  // Должности в списке — данные организации, а не код: «Бариста» пишет админ
  // по-русски. Имена — собственные и не переводятся, а фразы благодарности
  // живут в ленте и уезжают вместе с днём. Поэтому единственное, что здесь
  // стоит переводить, — должность.
  const translate = useBatchTranslate(people.map((person) => person.position ?? ""));
  // `kudosErrorText` всегда возвращает фразу: свою для известного кода и
  // общую — для остальных. Поэтому «пустого» отказа на экране не бывает.
  const errorText = send.isError ? kudosErrorText(send.error) : null;

  return (
    <div
      className="fixed inset-0 z-50 mx-auto flex w-full max-w-[560px] flex-col bg-tg-bg"
      role="dialog"
      aria-modal="true"
      aria-label={tx("Кому сказать спасибо")}
    >
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg/60 text-tg-link"
          aria-label={tx("Закрыть")}
        >
          <Icon name="back" size={20} />
        </button>
        <div className="min-w-0 flex-1 truncate text-sm font-semibold text-tg-text">
          {tx("Кому сказать спасибо")}
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        <div className="flex items-center gap-2">
          <input
            type="search"
            value={needle}
            onChange={(e) => setNeedle(e.target.value)}
            placeholder={tx("Поиск по имени")}
            aria-label={tx("Поиск по имени")}
            className="min-h-11 min-w-0 flex-1 rounded-tile bg-tg-secondary-bg/60 px-3 text-sm text-tg-text outline-none"
          />
          {translate.canTranslate && (
            <TranslateBlockButton
              on={translate.on}
              busy={translate.busy}
              onClick={() => void translate.toggle()}
            />
          )}
        </div>
        <TranslateFailedNotice show={translate.failed} />

        {peopleQ.isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-11 rounded-tile" />
            <Skeleton className="h-11 rounded-tile" />
            <Skeleton className="h-11 rounded-tile" />
          </div>
        )}

        {!peopleQ.isLoading && people.length === 0 && (
          <p className="rounded-card bg-tg-secondary-bg/60 p-3 text-center text-xs text-tg-hint">
            {tx("Никого не нашли")}
          </p>
        )}

        <ul className="space-y-1">
          {people.map((person) => {
            const active = person.employee_id === selected;
            return (
              <li key={person.employee_id}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    haptic("selection");
                    setSelected(active ? null : person.employee_id);
                  }}
                  className={`flex min-h-11 w-full items-center gap-2 rounded-tile px-3 text-left ${
                    active
                      ? "bg-tg-link/15 text-tg-text"
                      : "bg-tg-secondary-bg/50 text-tg-text"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {person.display_name}
                  </span>
                  {person.position && (
                    <span
                      className={[
                        "shrink-0 truncate text-xs text-tg-hint",
                        translate.t(person.position) !== person.position
                          ? TRANSLATED_MARK_INLINE
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {translate.t(person.position)}
                    </span>
                  )}
                  {active && <Icon name="check" size={16} />}
                </button>
              </li>
            );
          })}
        </ul>

        <div>
          <label
            className="text-2xs font-medium uppercase tracking-wide text-tg-hint"
            htmlFor="kudos-message"
          >
            {tx("Что сделал(а) — необязательно")}
          </label>
          <textarea
            id="kudos-message"
            value={message}
            maxLength={160}
            rows={2}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={tx("Спасибо за смену")}
            className="mt-1 w-full resize-none rounded-tile bg-tg-secondary-bg/60 p-2 text-sm text-tg-text outline-none"
          />
          <div className="mt-0.5 text-right text-2xs tabular-nums text-tg-hint">
            {message.length}/160
          </div>
        </div>

        {errorText && (
          <p
            role="alert"
            className="rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-tg-text"
          >
            {tx(errorText)}
          </p>
        )}
      </div>

      <footer className="border-t border-tg-secondary-bg px-4 py-3">
        <button
          type="button"
          disabled={selected === null || send.isPending}
          onClick={() => send.mutate()}
          className="min-h-11 w-full rounded-tile bg-tg-link text-sm font-semibold text-white disabled:opacity-50"
        >
          {send.isPending ? tx("Отправляем…") : tx("Сказать спасибо")}
        </button>
      </footer>
    </div>
  );
}
