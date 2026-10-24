import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import {
  applyShiftTemplate,
  bulkSaveShifts,
  clearShiftCells,
  copyShiftWeek,
  deleteShift,
  deleteShiftTemplate,
  fetchShiftTemplates,
  fetchShiftWeek,
  moveShift,
  saveShift,
  saveShiftTemplate,
  type BulkResult,
  type ShiftItem,
  type ShiftPerson,
  type ShiftStatus,
  type ShiftWeek,
} from "@/api/shifts";
import { CardSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { useTx } from "@/i18n";
import MassPlanSheet, {
  type MassPlanInput,
  type TemplateSaveInput,
} from "./MassPlanSheet";
import {
  addDays,
  cellKey,
  formatDate,
  mondayOf,
  rangeLabel,
  toIso,
  weekday,
} from "./shiftDates";

/**
 * Табель смен: одна неделя, одна сетка.
 *
 * Сотрудник видит, кто из его подразделения когда работает — без расспросов в
 * чате. Управляющий и разработчик видят все отделы (с фильтром) и правят
 * клетки: статус, часы, заметка, перенос. Учебные смены помечены точкой «у» —
 * их считает план обучения по фактическим сменам, а не по календарю.
 */
export default function ShiftsScreen() {
  const { tx } = useTx();
  const qc = useQueryClient();
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()));
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [sheet, setSheet] = useState<SheetState | null>(null);
  // Шаблон недели / массовые правки — отдельный лист: сетка остаётся по клеткам.
  const [massOpen, setMassOpen] = useState(false);

  const startIso = toIso(weekStart);
  const q = useQuery({
    queryKey: ["shifts", startIso, departmentId ?? "all"],
    queryFn: () => fetchShiftWeek(startIso, { departmentId }),
    staleTime: 20_000,
  });

  // Шаблоны нужны только тем, кто правит табель: сотруднику ручка ответит 403.
  const templatesQ = useQuery({
    queryKey: ["shift-templates"],
    queryFn: fetchShiftTemplates,
    enabled: q.data?.can_edit === true,
    retry: false,
    staleTime: 60_000,
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["shifts"] });
    void qc.invalidateQueries({ queryKey: ["shift-templates"] });
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

  /** «Записано 5, пропущено 2» — без чисел результат массовой правки не понять. */
  const bulkText = (result: BulkResult, verb: string) =>
    `${verb}: ${result.saved}` +
    (result.skipped
      ? ` · ${tx("пропущено занятых: {count}", { count: result.skipped })}`
      : "");

  const bulk = useMutation({
    mutationFn: (input: MassPlanInput) =>
      bulkSaveShifts({
        employee_ids: input.employeeIds,
        days: input.days,
        status: input.status,
        starts_at: input.startsAt || null,
        ends_at: input.endsAt || null,
        note: input.note.trim() || null,
        overwrite: input.overwrite,
      }),
    onSuccess: (result) => {
      haptic("success");
      setMassOpen(false);
      refresh();
      void showAlert(bulkText(result, tx("Записано смен")));
    },
    onError,
  });

  const copyPrevious = useMutation({
    mutationFn: (employeeIds: number[]) =>
      copyShiftWeek({
        from_start: toIso(addDays(weekStart, -7)),
        to_start: toIso(weekStart),
        employee_ids: employeeIds,
      }),
    onSuccess: (result) => {
      haptic("success");
      setMassOpen(false);
      refresh();
      void showAlert(bulkText(result, tx("Скопировано смен")));
    },
    onError,
  });

  const saveTemplate = useMutation({
    mutationFn: (input: TemplateSaveInput) =>
      saveShiftTemplate({
        name: input.name,
        department_id: departmentId,
        days: input.days,
      }),
    onSuccess: (template) => {
      haptic("success");
      refresh();
      void showAlert(`Шаблон «${template.name}» сохранён`);
    },
    onError,
  });

  const applyTemplate = useMutation({
    mutationFn: ({
      templateId,
      employeeIds,
    }: {
      templateId: number;
      employeeIds: number[];
    }) =>
      applyShiftTemplate(templateId, {
        employee_ids: employeeIds,
        week_start: toIso(weekStart),
      }),
    onSuccess: (result) => {
      haptic("success");
      setMassOpen(false);
      refresh();
      void showAlert(bulkText(result, tx("Записано смен")));
    },
    onError,
  });

  const removeTemplate = useMutation({
    mutationFn: (templateId: number) => deleteShiftTemplate(templateId),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError,
  });

  const clearCells = useMutation({
    mutationFn: (input: { employeeIds: number[]; days: string[] }) =>
      clearShiftCells({ employee_ids: input.employeeIds, days: input.days }),
    onSuccess: (result) => {
      haptic("success");
      setMassOpen(false);
      refresh();
      void showAlert(`Снято смен: ${result.removed}`);
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
            <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
              <Icon name="calendar" size={16} />{tx("Табель смен")}</div>
            <div className="text-xs text-tg-hint">
              {rangeLabel(days)} · {canEdit ? tx("можно править") : tx("твой отдел")}
            </div>
          </div>
          <button
            type="button"
            onClick={() => stepWeek(-1)}
            className="min-h-11 min-w-11 rounded-tile bg-tg-secondary-bg/60 text-sm text-tg-text"
            aria-label={tx("Предыдущая неделя")}
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setWeekStart(mondayOf(new Date()));
            }}
            className="min-h-9 rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
          >{tx("Сегодня")}</button>
          <button
            type="button"
            onClick={() => stepWeek(1)}
            className="min-h-11 min-w-11 rounded-tile bg-tg-secondary-bg/60 text-sm text-tg-text"
            aria-label={tx("Следующая неделя")}
          >
            ›
          </button>
        </div>

        {canEdit && (q.data?.departments.length ?? 0) > 1 && (
          <div className="mt-2 flex gap-1.5 overflow-x-auto pb-0.5">
            <FilterChip
              active={departmentId === null}
              label={tx("Все отделы")}
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

        {canEdit && q.data && (
          <button
            type="button"
            onClick={() => {
              haptic("light");
              setMassOpen(true);
            }}
            className="mt-2 flex min-h-11 w-full items-center justify-center gap-1.5 rounded-tile bg-tg-secondary-bg/60 text-xs font-medium text-tg-text"
          >
            <Icon name="clipboard" size={16} />{tx("Шаблон недели и массовые правки")}</button>
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
          <p className="p-4 text-center text-xs text-tg-hint">{tx("В этом отделе пока нет сотрудников.")}</p>
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
                aria-label={tx("Табель смен на неделю")}
              >
                <div className="px-1 py-1 text-2xs text-tg-hint">{tx("Сотрудник")}</div>
                {days.map((day) => {
                  const iso = toIso(day);
                  const isToday = iso === todayIso;
                  return (
                    <div
                      key={iso}
                      className={`rounded-tile px-0.5 py-1 text-center text-2xs ${
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
                <b className="text-tg-link">{tx("у")}</b>{tx("— учебная смена")}</span>
            </div>
          </>
        )}
      </div>

      {massOpen && q.data && (
        <MassPlanSheet
          people={q.data.people}
          weekStart={weekStart}
          statuses={q.data.statuses}
          templates={templatesQ.data ?? []}
          busy={bulk.isPending}
          copyBusy={copyPrevious.isPending}
          clearBusy={clearCells.isPending}
          templateBusy={
            saveTemplate.isPending ||
            applyTemplate.isPending ||
            removeTemplate.isPending
          }
          onClose={() => setMassOpen(false)}
          onApply={(input) => bulk.mutate(input)}
          onCopyPrevious={(employeeIds) => copyPrevious.mutate(employeeIds)}
          onApplyTemplate={(templateId, employeeIds) =>
            applyTemplate.mutate({ templateId, employeeIds })
          }
          onSaveTemplate={(input) => saveTemplate.mutate(input)}
          onDeleteTemplate={(templateId) => {
            void (async () => {
              const ok = await showConfirm(tx("Удалить шаблон недели?"));
              if (ok) removeTemplate.mutate(templateId);
            })();
          }}
          onClear={(input) => {
            void (async () => {
              const count = input.employeeIds.length * input.days.length;
              const ok = await showConfirm(
                tx("Снять смены с выбранных клеток ({count})?", { count }),
              );
              if (ok) clearCells.mutate(input);
            })();
          }}
        />
      )}

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
              const ok = await showConfirm(tx("Удалить смену из табеля?"));
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
    const key = person.department_name ?? "";
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
  const { tx } = useTx();
  return (
    <>
      <div
        className="col-span-8 mt-2 px-1 pt-1 text-2xs font-medium uppercase tracking-wide text-tg-hint"
        style={{ gridColumn: "1 / -1" }}
      >
        {group || tx("Без подразделения")}
      </div>
      {people.map((person) => (
        <div key={person.employee_id} className="contents">
          <div className="flex min-h-11 items-center rounded-tile bg-tg-secondary-bg/40 px-2">
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
  const { tx } = useTx();
  return (
    <button
      type="button"
      onClick={onClick}
      title={
        shift
          ? `${tx(shift.status_label)}${shift.is_training ? tx(" · учебная") : ""}${
              shift.starts_at ? ` · ${shift.starts_at}` : ""
            }${shift.ends_at ? `–${shift.ends_at}` : ""}`
          : tx("Смены нет")
      }
      className={`relative flex min-h-11 flex-col items-center justify-center rounded-tile text-xs leading-none transition-transform active:scale-95 ${
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
            <span className="absolute right-0.5 top-0.5 text-3xs font-semibold">{tx("у")}</span>
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
  const { tx } = useTx();
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
        className="mx-auto w-full max-w-[560px] rounded-t-card bg-tg-bg p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-tg-text">
              {state.person.display_name} · {formatDate(state.day)}
            </div>
            <div className="text-xs text-tg-hint">
              {state.person.department_name ?? tx("Без подразделения")}
              {state.shift?.moved_from
                ? tx(" · перенесена с {date}", {
                    date: formatDate(state.shift.moved_from),
                  })
                : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg/60 text-sm text-tg-text"
            aria-label={tx("Закрыть")}
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        {!canEdit && (
          <div className="mt-3 space-y-1 text-xs text-tg-text">
            <div>{tx("Статус:")}<b>{tx(state.shift?.status_label ?? "смены нет")}</b>
              {state.shift?.is_training ? tx(" · учебная") : ""}
            </div>
            {state.shift?.starts_at && (
              <div>
                {tx("Часы:")} {state.shift.starts_at}
                {state.shift.ends_at ? `–${state.shift.ends_at}` : ""}
              </div>
            )}
            {state.shift?.note && <div>{tx("Заметка:")} {state.shift.note}</div>}
            <p className="pt-2 text-xs text-tg-hint">{tx("Править табель может руководитель подразделения.")}</p>
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
                  className={`min-h-9 rounded-tile px-1 text-xs ${
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
              <label className="flex-1 text-xs text-tg-hint">{tx("Начало")}<input
                  type="time"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                  className="mt-0.5 min-h-9 w-full rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
                />
              </label>
              <label className="flex-1 text-xs text-tg-hint">{tx("Конец")}<input
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
              placeholder={tx("Заметка (необязательно)")}
              className="mt-2 min-h-9 w-full rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text placeholder:text-tg-hint"
            />

            <label className="mt-2 block text-xs text-tg-hint">{tx("Перенести на дату (необязательно)")}<input
                type="date"
                value={moveTo}
                onChange={(event) => setMoveTo(event.target.value)}
                className="mt-0.5 min-h-9 w-full rounded-tile bg-tg-secondary-bg/60 px-2 text-xs text-tg-text"
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
                className="min-h-11 flex-1 rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {busy
                  ? tx("Сохраняем…")
                  : tx("Сохранить · {status}", {
                      status: tx(statusMeta?.label ?? status),
                    })}
              </button>
              {state.shift && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDelete(state.shift!.id)}
                  className="min-h-11 rounded-card bg-status-busy/15 px-3 text-xs text-status-busy disabled:opacity-50"
                >{tx("Удалить")}</button>
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
        active
          ? "bg-tg-link/15 font-medium text-tg-text"
          : "bg-tg-secondary-bg/60 text-tg-text"
      }`}
    >
      {label}
    </button>
  );
}
