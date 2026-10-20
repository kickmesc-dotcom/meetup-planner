import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import {
  deleteShift,
  fetchShiftWeek,
  moveShift,
  saveShift,
  type ShiftItem,
  type ShiftPerson,
  type ShiftStatus,
  type ShiftWeek,
} from "@/api/shifts";
import { CardSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";

/**
 * Табель смен: одна неделя, одна сетка.
 *
 * Сотрудник видит, кто из его подразделения когда работает — без расспросов в
 * чате. Управляющий и разработчик видят все отделы (с фильтром) и правят
 * клетки: статус, часы, заметка, перенос. Учебные смены помечены точкой «у» —
 * их считает план обучения по фактическим сменам, а не по календарю.
 */
export default function ShiftsScreen() {
  const qc = useQueryClient();
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()));
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [sheet, setSheet] = useState<SheetState | null>(null);

  const startIso = toIso(weekStart);
  const q = useQuery({
    queryKey: ["shifts", startIso, departmentId ?? "all"],
    queryFn: () => fetchShiftWeek(startIso, { departmentId }),
    staleTime: 20_000,
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["shifts"] });
    void qc.invalidateQueries({ queryKey: ["admin", "training-plan"] });
    void qc.invalidateQueries({ queryKey: ["hr-training"] });
  };

  const onError = (error: unknown) => void showAlert(humanizeApiError(error));

  const save = useMutation({
    mutationFn: async (input: SheetInput) => {
      const saved = await saveShift(input.employeeId, input.day, {
        status: input.status,
        starts_at: input.startsAt || null,
        ends_at: input.endsAt || null,
        note: input.note.trim() || null,
      });
      if (input.moveTo && input.moveTo !== input.day) {
        return moveShift(saved.id, input.moveTo);
      }
      return saved;
    },
    onSuccess: () => {
      haptic("success");
      setSheet(null);
      refresh();
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: (shiftId: number) => deleteShift(shiftId),
    onSuccess: () => {
      haptic("success");
      setSheet(null);
      refresh();
    },
    onError,
  });

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addDays(weekStart, index)),
    [weekStart],
  );

  const byCell = useMemo(() => {
    const map = new Map<string, ShiftItem>();
    for (const shift of q.data?.shifts ?? []) {
      map.set(cellKey(shift.employee_id, shift.day), shift);
    }
    return map;
  }, [q.data]);

  const todayIso = q.data?.today ?? toIso(new Date());
  const canEdit = q.data?.can_edit === true;

  const stepWeek = (direction: 1 | -1) => {
    haptic("light");
    setWeekStart((current) => addDays(current, direction * 7));
  };

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-tg-text">🗓 Табель смен</div>
            <div className="text-xs text-tg-hint">
              {rangeLabel(days)} · {canEdit ? "можно править" : "твой отдел"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => stepWeek(-1)}
            className="min-h-11 min-w-11 rounded-lg bg-tg-secondary-bg/60 text-sm text-tg-text"
            aria-label="Предыдущая неделя"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setWeekStart(mondayOf(new Date()));
            }}
            className="min-h-9 rounded-lg bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
          >
            Сегодня
          </button>
          <button
            type="button"
            onClick={() => stepWeek(1)}
            className="min-h-11 min-w-11 rounded-lg bg-tg-secondary-bg/60 text-sm text-tg-text"
            aria-label="Следующая неделя"
          >
            ›
          </button>
        </div>

        {canEdit && (q.data?.departments.length ?? 0) > 1 && (
          <div className="mt-2 flex gap-1.5 overflow-x-auto pb-0.5">
            <FilterChip
              active={departmentId === null}
              label="Все отделы"
              onClick={() => {
                haptic("selection");
                setDepartmentId(null);
              }}
            />
            {q.data?.departments.map((dept) => (
              <FilterChip
                key={dept.id}
                active={departmentId === dept.id}
                label={dept.name}
                onClick={() => {
                  haptic("selection");
                  setDepartmentId(dept.id);
                }}
              />
            ))}
          </div>
        )}
      </header>

      <div className="flex-1 overflow-y-auto p-2">
        {q.isLoading && (
          <div className="space-y-2">
            <CardSkeleton />
            <CardSkeleton />
          </div>
        )}
        {q.isError && (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}

        {q.data && q.data.people.length === 0 && (
          <p className="p-4 text-center text-xs text-tg-hint">
            В этом отделе пока нет сотрудников.
          </p>
        )}

        {q.data && q.data.people.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <div
                className="grid min-w-[520px] gap-1"
                style={{
                  gridTemplateColumns: "minmax(104px, 1.25fr) repeat(7, minmax(40px, 1fr))",
                }}
                role="table"
                aria-label="Табель смен на неделю"
              >
                <div className="px-1 py-1 text-2xs text-tg-hint">Сотрудник</div>
                {days.map((day) => {
                  const iso = toIso(day);
                  const isToday = iso === todayIso;
                  return (
                    <div
                      key={iso}
                      className={`rounded-lg px-0.5 py-1 text-center text-2xs ${
                        isToday
                          ? "bg-tg-link/15 font-medium text-tg-link"
                          : "text-tg-hint"
                      }`}
                    >
                      <div className="uppercase">{weekday(day)}</div>
                      <div className="text-sm tabular-nums">{day.getDate()}</div>
                    </div>
                  );
                })}

                {groupedPeople(q.data).map(([group, people]) => (
                  <GroupRows
                    key={group ?? "none"}
                    group={group}
                    people={people}
                    days={days}
                    todayIso={todayIso}
                    byCell={byCell}
                    canEdit={canEdit}
                    onOpen={setSheet}
                  />
                ))}
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 px-1 text-2xs text-tg-hint">
              {q.data.statuses.map((item) => (
                <span key={item.value}>
                  <b className="text-tg-text">{item.short}</b> — {item.label}
                </span>
              ))}
              <span>
                <b className="text-tg-link">у</b> — учебная смена
              </span>
            </div>
          </>
        )}
      </div>

      {sheet && (
        <ShiftSheet
          state={sheet}
          canEdit={canEdit}
          statuses={q.data?.statuses ?? []}
          busy={save.isPending || remove.isPending}
          onClose={() => setSheet(null)}
          onSave={(input) => save.mutate(input)}
          onDelete={(shiftId) => {
            void (async () => {
              const ok = await showConfirm("Удалить смену из табеля?");
              if (ok) remove.mutate(shiftId);
            })();
          }}
        />
      )}
    </div>
  );
}

/** Группировка строк по подразделению: в режиме «Все отделы» так читаемее. */
function groupedPeople(week: ShiftWeek): [string | null, ShiftPerson[]][] {
  const groups = new Map<string | null, ShiftPerson[]>();
  for (const person of week.people) {
    const key = person.department_name ?? "Без подразделения";
    const list = groups.get(key) ?? [];
    list.push(person);
    groups.set(key, list);
  }
  return [...groups.entries()];
}

function GroupRows({
  group,
  people,
  days,
  todayIso,
  byCell,
  canEdit,
  onOpen,
}: {
  group: string | null;
  people: ShiftPerson[];
  days: Date[];
  todayIso: string;
  byCell: Map<string, ShiftItem>;
  canEdit: boolean;
  onOpen: (state: SheetState) => void;
}) {
  return (
    <>
      <div
        className="col-span-8 mt-2 px-1 pt-1 text-2xs font-medium uppercase tracking-wide text-tg-hint"
        style={{ gridColumn: "1 / -1" }}
      >
        {group}
      </div>
      {people.map((person) => (
        <div key={person.employee_id} className="contents">
          <div className="flex min-h-11 items-center rounded-lg bg-tg-secondary-bg/40 px-2">
            <div className="min-w-0">
              <div className="truncate text-xs text-tg-text">{person.display_name}</div>
              {person.position && (
                <div className="truncate text-2xs text-tg-hint">
                  {person.position}
                </div>
              )}
            </div>
          </div>
          {days.map((day) => {
            const iso = toIso(day);
            const shift = byCell.get(cellKey(person.employee_id, iso));
            const isToday = iso === todayIso;
            return (
              <Cell
                key={`${person.employee_id}-${iso}`}
                shift={shift}
                isToday={isToday}
                canEdit={canEdit}
                onClick={() => {
                  haptic("light");
                  onOpen({
                    person,
                    day: iso,
                    shift: shift ?? null,
                  });
                }}
              />
            );
          })}
        </div>
      ))}
    </>
  );
}

const TONE: Record<ShiftStatus, string> = {
  planned: "bg-tg-link/15 text-tg-link",
  worked: "bg-status-free/15 text-status-free",
  sick: "bg-status-busy/10 text-status-busy",
  absent: "bg-status-busy/20 text-status-busy",
  dayoff: "bg-tg-bg/70 text-tg-hint",
  vacation: "bg-tg-link/10 text-tg-link",
};

function Cell({
  shift,
  isToday,
  canEdit,
  onClick,
}: {
  shift: ShiftItem | undefined;
  isToday: boolean;
  canEdit: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={
        shift
          ? `${shift.status_label}${shift.is_training ? " · учебная" : ""}${
              shift.starts_at ? ` · ${shift.starts_at}` : ""
            }${shift.ends_at ? `–${shift.ends_at}` : ""}`
          : "Смены нет"
      }
      className={`relative flex min-h-11 flex-col items-center justify-center rounded-lg text-xs leading-none transition-transform active:scale-95 ${
        shift
          ? TONE[shift.status]
          : "border border-dashed border-tg-hint/25 text-tg-hint"
      } ${isToday ? "ring-1 ring-inset ring-tg-link/40" : ""}`}
    >
      {shift ? (
        <>
          <span className="font-medium">{shift.short}</span>
          {shift.starts_at && (
            <span className="mt-0.5 text-3xs opacity-80">{shift.starts_at}</span>
          )}
          {shift.is_training && (
            <span className="absolute right-0.5 top-0.5 text-3xs font-semibold">
              у
            </span>
          )}
        </>
      ) : (
        <span className="text-sm opacity-70">{canEdit ? "＋" : "—"}</span>
      )}
    </button>
  );
}

interface SheetState {
  person: ShiftPerson;
  day: string;
  shift: ShiftItem | null;
}

interface SheetInput {
  employeeId: number;
  day: string;
  status: ShiftStatus;
  startsAt: string;
  endsAt: string;
  note: string;
  moveTo: string;
}

function ShiftSheet({
  state,
  canEdit,
  statuses,
  busy,
  onClose,
  onSave,
  onDelete,
}: {
  state: SheetState;
  canEdit: boolean;
  statuses: ShiftWeek["statuses"];
  busy: boolean;
  onClose: () => void;
  onSave: (input: SheetInput) => void;
  onDelete: (shiftId: number) => void;
}) {
  const [status, setStatus] = useState<ShiftStatus>(
    state.shift?.status ?? "planned",
  );
  const [startsAt, setStartsAt] = useState(state.shift?.starts_at ?? "");
  const [endsAt, setEndsAt] = useState(state.shift?.ends_at ?? "");
  const [note, setNote] = useState(state.shift?.note ?? "");
  const [moveTo, setMoveTo] = useState("");

  const statusMeta = statuses.find((item) => item.value === status);

  return (
    <div className="fixed inset-0 z-40 flex items-end bg-black/40" onClick={onClose}>
      <div
        className="mx-auto w-full max-w-[560px] rounded-t-2xl bg-tg-bg p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-tg-text">
              {state.person.display_name} · {formatDate(state.day)}
            </div>
            <div className="text-xs text-tg-hint">
              {state.person.department_name ?? "Без подразделения"}
              {state.shift?.moved_from
                ? ` · перенесена с ${formatDate(state.shift.moved_from)}`
                : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 min-w-11 rounded-lg bg-tg-secondary-bg/60 text-sm text-tg-text"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        {!canEdit && (
          <div className="mt-3 space-y-1 text-xs text-tg-text">
            <div>
              Статус: <b>{state.shift?.status_label ?? "смены нет"}</b>
              {state.shift?.is_training ? " · учебная" : ""}
            </div>
            {state.shift?.starts_at && (
              <div>
                Часы: {state.shift.starts_at}
                {state.shift.ends_at ? `–${state.shift.ends_at}` : ""}
              </div>
            )}
            {state.shift?.note && <div>Заметка: {state.shift.note}</div>}
            <p className="pt-2 text-xs text-tg-hint">
              Править табель может руководитель подразделения.
            </p>
          </div>
        )}

        {canEdit && (
          <>
            <div className="mt-3 grid grid-cols-3 gap-1.5">
              {statuses.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => {
                    haptic("selection");
                    setStatus(item.value);
                  }}
                  className={`min-h-9 rounded-lg px-1 text-xs ${
                    status === item.value
                      ? "bg-tg-button text-tg-button-text"
                      : "bg-tg-secondary-bg/60 text-tg-text"
                  }`}
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
                  className="mt-0.5 min-h-9 w-full rounded-lg bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
                />
              </label>
              <label className="flex-1 text-xs text-tg-hint">
                Конец
                <input
                  type="time"
                  value={endsAt}
                  onChange={(event) => setEndsAt(event.target.value)}
                  className="mt-0.5 min-h-9 w-full rounded-lg bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
                />
              </label>
            </div>

            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={200}
              placeholder="Заметка (необязательно)"
              className="mt-2 min-h-9 w-full rounded-lg bg-tg-secondary-bg/60 px-2 text-xs text-tg-text placeholder:text-tg-hint"
            />

            <label className="mt-2 block text-xs text-tg-hint">
              Перенести на дату (необязательно)
              <input
                type="date"
                value={moveTo}
                onChange={(event) => setMoveTo(event.target.value)}
                className="mt-0.5 min-h-9 w-full rounded-lg bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
              />
            </label>

            <div className="mt-3 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  haptic("medium");
                  onSave({
                    employeeId: state.person.employee_id,
                    day: state.day,
                    status,
                    startsAt,
                    endsAt,
                    note,
                    moveTo,
                  });
                }}
                className="min-h-11 flex-1 rounded-xl bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {busy ? "Сохраняем…" : `Сохранить · ${statusMeta?.label ?? status}`}
              </button>
              {state.shift && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDelete(state.shift!.id)}
                  className="min-h-11 rounded-xl bg-status-busy/15 px-3 text-xs text-status-busy disabled:opacity-50"
                >
                  Удалить
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function FilterChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`shrink-0 min-h-8 rounded-full px-2.5 text-xs ${
        active ? "bg-tg-button text-tg-button-text" : "bg-tg-secondary-bg/60 text-tg-text"
      }`}
    >
      {label}
    </button>
  );
}

// --- Даты ------------------------------------------------------------------

function mondayOf(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  const shift = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - shift);
  return copy;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function toIso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function cellKey(employeeId: number, day: string): string {
  return `${employeeId}:${day}`;
}

function weekday(date: Date): string {
  return date.toLocaleDateString("ru-RU", { weekday: "short" }).slice(0, 2);
}

function formatDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

function rangeLabel(days: Date[]): string {
  const first = days[0];
  const last = days[days.length - 1];
  const sameMonth = first.getMonth() === last.getMonth();
  const left = first.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
  });
  const right = last.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: sameMonth ? undefined : "short",
    year: last.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
  return `${left} — ${right}`;
}
