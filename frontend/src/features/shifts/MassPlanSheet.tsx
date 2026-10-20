import { useMemo, useState } from "react";
import type { ShiftPerson, ShiftStatus, ShiftStatusMeta } from "@/api/shifts";
import { haptic } from "@/tg/webapp";
import { addDays, formatDate, toIso, weekdaysToIso } from "./shiftDates";

/**
 * Шаблон недели и массовые правки табеля.
 *
 * Почему отдельный лист, а не ещё одна строка в сетке: сетка правится по
 * клетке, и на телефоне это нормально ровно до момента, когда нужно поставить
 * «пн/ср/пт по 10:00» пятерым. Здесь три операции одним действием:
 *
 *  • шаблон — выбранные дни текущей недели для выбранных людей;
 *  • копия прошлой недели — день недели сохраняется, занятые клетки по
 *    умолчанию не трогаются;
 *  • очистка — снимает смены только с выбранных дней, остальные не задевает.
 *
 * По умолчанию дни не выбраны и «заменить существующие» выключено: массовая
 * запись в график не должна случаться от одного неосторожного тапа.
 */
export interface MassPlanInput {
  employeeIds: number[];
  days: string[];
  status: ShiftStatus;
  startsAt: string;
  endsAt: string;
  note: string;
  /** true — перезаписать уже стоящие смены, false — только пустые клетки. */
  overwrite: boolean;
}

const WEEKDAYS: { value: number; label: string }[] = [
  { value: 0, label: "Пн" },
  { value: 1, label: "Вт" },
  { value: 2, label: "Ср" },
  { value: 3, label: "Чт" },
  { value: 4, label: "Пт" },
  { value: 5, label: "Сб" },
  { value: 6, label: "Вс" },
];

export default function MassPlanSheet({
  people,
  weekStart,
  statuses,
  busy,
  copyBusy,
  clearBusy,
  onClose,
  onApply,
  onCopyPrevious,
  onClear,
}: {
  people: ShiftPerson[];
  weekStart: Date;
  statuses: ShiftStatusMeta[];
  busy: boolean;
  copyBusy: boolean;
  clearBusy: boolean;
  onClose: () => void;
  onApply: (input: MassPlanInput) => void;
  onCopyPrevious: (employeeIds: number[]) => void;
  onClear: (input: { employeeIds: number[]; days: string[] }) => void;
}) {
  // По умолчанию выбраны все, кто виден в текущем фильтре отдела: чаще всего
  // шаблон ставят всему подразделению. Дни — наоборот, пустые.
  const [picked, setPicked] = useState<number[]>(() =>
    people.map((person) => person.employee_id),
  );
  const [days, setDays] = useState<number[]>([]);
  const [status, setStatus] = useState<ShiftStatus>("planned");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [note, setNote] = useState("");
  const [overwrite, setOverwrite] = useState(false);

  const dayIsos = useMemo(() => weekdaysToIso(weekStart, days), [weekStart, days]);
  const allPicked = picked.length > 0 && picked.length === people.length;
  const ready = picked.length > 0 && dayIsos.length > 0;
  const statusMeta = statuses.find((item) => item.value === status);

  const togglePerson = (employeeId: number) => {
    haptic("selection");
    setPicked((current) =>
      current.includes(employeeId)
        ? current.filter((id) => id !== employeeId)
        : [...current, employeeId],
    );
  };

  const toggleDay = (value: number) => {
    haptic("selection");
    setDays((current) =>
      current.includes(value)
        ? current.filter((day) => day !== value)
        : [...current, value],
    );
  };

  const toggleAllPeople = () => {
    haptic("selection");
    setPicked(allPicked ? [] : people.map((person) => person.employee_id));
  };

  const sameHours = startsAt && endsAt ? `${startsAt}–${endsAt}` : startsAt;

  return (
    <div className="fixed inset-0 z-40 flex items-end bg-black/40" onClick={onClose}>
      <div
        className="mx-auto max-h-[92vh] w-full max-w-[560px] overflow-y-auto rounded-t-card bg-tg-bg p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label="Шаблон недели"
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-tg-text">Шаблон недели</div>
            <div className="text-xs text-tg-hint">
              {`${formatDate(toIso(weekStart))} — ${formatDate(
                toIso(addDays(weekStart, 6)),
              )} · смена сразу на много клеток`}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 min-w-11 rounded-tile bg-tg-secondary-bg/60 text-sm text-tg-text"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        {/* 1. Кому. */}
        <div className="mt-3 flex items-baseline justify-between gap-2">
          <span className="text-xs font-medium text-tg-text">Кому</span>
          <button
            type="button"
            onClick={toggleAllPeople}
            className="min-h-9 text-xs text-tg-link"
          >
            {allPicked ? "Снять всех" : "Выбрать всех"}
          </button>
        </div>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {people.map((person) => {
            const active = picked.includes(person.employee_id);
            return (
              <button
                key={person.employee_id}
                type="button"
                aria-pressed={active}
                onClick={() => togglePerson(person.employee_id)}
                className={[
                  "min-h-9 max-w-[46%] truncate rounded-full px-2.5 text-xs transition-colors",
                  active
                    ? "bg-tg-link/15 font-medium text-tg-text"
                    : "bg-tg-secondary-bg/60 text-tg-hint",
                ].join(" ")}
              >
                {person.display_name}
              </button>
            );
          })}
        </div>

        {/* 2. В какие дни. */}
        <div className="mt-3 text-xs font-medium text-tg-text">В какие дни</div>
        <div className="mt-1 flex gap-1.5">
          {WEEKDAYS.map((day) => {
            const active = days.includes(day.value);
            return (
              <button
                key={day.value}
                type="button"
                aria-pressed={active}
                onClick={() => toggleDay(day.value)}
                className={[
                  "min-h-11 flex-1 rounded-tile text-xs transition-colors",
                  active
                    ? "bg-tg-link/15 font-medium text-tg-text"
                    : "bg-tg-secondary-bg/60 text-tg-hint",
                ].join(" ")}
              >
                {day.label}
              </button>
            );
          })}
        </div>
        <div className="mt-1 text-2xs text-tg-hint">
          {dayIsos.length === 0
            ? "Выбери хотя бы один день — без этого записывать нечего."
            : `Дней выбрано: ${dayIsos.length}`}
        </div>

        {/* 3. Что именно. */}
        <div className="mt-3 grid grid-cols-3 gap-1.5">
          {statuses.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={status === item.value}
              onClick={() => {
                haptic("selection");
                setStatus(item.value);
              }}
              className={[
                "min-h-9 rounded-tile px-1 text-xs transition-colors",
                status === item.value
                  ? "bg-tg-link/15 font-medium text-tg-text"
                  : "bg-tg-secondary-bg/60 text-tg-text",
              ].join(" ")}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="mt-2 flex items-center gap-2">
          <label className="flex-1 text-xs text-tg-hint">
            Начало
            <input
              type="time"
              value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)}
              className="mt-0.5 min-h-9 w-full rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
            />
          </label>
          <label className="flex-1 text-xs text-tg-hint">
            Конец
            <input
              type="time"
              value={endsAt}
              onChange={(event) => setEndsAt(event.target.value)}
              className="mt-0.5 min-h-9 w-full rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
            />
          </label>
        </div>

        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          maxLength={200}
          placeholder="Заметка (необязательно)"
          className="mt-2 min-h-9 w-full rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text placeholder:text-tg-hint"
        />

        <label className="mt-2 flex items-start gap-2 text-xs text-tg-text">
          <input
            type="checkbox"
            className="chk-tg mt-0.5"
            checked={overwrite}
            onChange={(event) => setOverwrite(event.target.checked)}
          />
          <span>
            Заменить уже поставленные смены
            <span className="block text-2xs text-tg-hint">
              Выключено — заполняем только пустые клетки.
            </span>
          </span>
        </label>

        <button
          type="button"
          disabled={!ready || busy}
          onClick={() => {
            haptic("medium");
            onApply({
              employeeIds: picked,
              days: dayIsos,
              status,
              startsAt,
              endsAt,
              note,
              overwrite,
            });
          }}
          className="mt-3 min-h-11 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
        >
          {busy
            ? "Записываем…"
            : `Применить${sameHours ? ` · ${sameHours}` : ""} · ${
                statusMeta?.label ?? status
              }`}
        </button>
        <div className="mt-1 text-center text-2xs text-tg-hint">
          {ready
            ? `${picked.length} чел. × ${dayIsos.length} дн.`
            : "Выбери людей и дни"}
        </div>

        {/* 4. Соседние операции с тем же выделением. */}
        <div className="mt-3 flex gap-2 border-t border-tg-hint/10 pt-3">
          <button
            type="button"
            disabled={!ready || copyBusy}
            onClick={() => onCopyPrevious(picked)}
            className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text disabled:opacity-40"
          >
            {copyBusy ? "Копируем…" : "Скопировать прошлую неделю"}
          </button>
          <button
            type="button"
            disabled={!ready || clearBusy}
            onClick={() => onClear({ employeeIds: picked, days: dayIsos })}
            className="min-h-11 rounded-tile bg-status-busy/15 px-3 text-xs text-status-busy disabled:opacity-40"
          >
            {clearBusy ? "Снимаем…" : "Снять смены"}
          </button>
        </div>
        <p className="mt-2 text-2xs text-tg-hint">
          Копирование переносит прошлую неделю на эту и не затирает занятые дни.
          «Снять смены» трогает только выбранные дни.
        </p>
      </div>
    </div>
  );
}
