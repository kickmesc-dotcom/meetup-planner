import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchDepartments } from "@/api/hr";
import {
  KIND_LABEL,
  createAdminChecklist,
  createAdminHall,
  createChecklistItem,
  deleteChecklistItem,
  fetchAdminChecklists,
  fetchAdminHalls,
  patchAdminChecklist,
  patchAdminHall,
  patchChecklistItem,
  type AdminChecklistItem,
  type AdminChecklistKind,
  type AdminChecklistTemplate,
} from "@/api/checklists";
import { humanizeApiError } from "@/api/client";
import { Checkbox, Toggle as TgToggle } from "@/components/Checkbox";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import SubScreen from "./SubScreen";

/**
 * Админка → «Чек-листы».
 *
 * Управляющий сам правит регламент смены: выбирает подразделение, зал и вид
 * чек-листа, добавляет/переименовывает/удаляет пункты, задаёт порядок и
 * тумблеры «нужен фотоотчёт» / «обязательный». Закрытие смены — общий шаблон
 * (зал «Общий»). Здесь же заводится список залов: новый зал сразу появляется
 * в выборе у официанта.
 */
interface Props {
  onBack: () => void;
}

type HallFilter = number | "common";

export default function ChecklistSettingsScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const deps = useQuery({ queryKey: ["departments"], queryFn: fetchDepartments });
  const hallsQ = useQuery({
    queryKey: ["admin", "halls"],
    queryFn: fetchAdminHalls,
  });
  const tplQ = useQuery({
    queryKey: ["admin", "checklists"],
    queryFn: fetchAdminChecklists,
  });

  const [deptId, setDeptId] = useState<number | null>(null);
  const [hallSel, setHallSel] = useState<HallFilter>("common");
  const [kind, setKind] = useState<AdminChecklistKind>("shift");

  const departmentId = deptId ?? deps.data?.[0]?.id ?? null;
  const halls = hallsQ.data ?? [];
  // Зал имеет смысл только для открытия: закрытие и первый день — общие.
  const effectiveHall: HallFilter = kind === "shift" ? hallSel : "common";

  const template = useMemo(() => {
    if (!departmentId) return null;
    return (
      tplQ.data?.find(
        (t) =>
          t.department_id === departmentId &&
          t.kind === kind &&
          (effectiveHall === "common"
            ? t.hall_id === null
            : t.hall_id === effectiveHall),
      ) ?? null
    );
  }, [tplQ.data, departmentId, kind, effectiveHall]);

  const hallName =
    effectiveHall === "common"
      ? "Общий (все залы)"
      : (halls.find((h) => h.id === effectiveHall)?.name ?? "Зал");

  const invalidate = () => {
    haptic("success");
    void qc.invalidateQueries({ queryKey: ["admin", "checklists"] });
    void qc.invalidateQueries({ queryKey: ["hr-checklist"] });
  };

  const createTpl = useMutation({
    mutationFn: () =>
      createAdminChecklist({
        department_id: departmentId!,
        title:
          kind === "close"
            ? "Закрытие смены"
            : kind === "first_day"
              ? "Первый день"
              : `Открытие — ${hallName}`,
        kind,
        hall_id: effectiveHall === "common" ? null : effectiveHall,
      }),
    onSuccess: () => invalidate(),
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <SubScreen
      title="Чек-листы"
      subtitle="Пункты дня, залы и фотоотчёты"
      onBack={onBack}
    >
      <section className="space-y-2">
        <div className="px-1 text-xs font-semibold uppercase tracking-wide text-tg-hint">
          Подразделение
        </div>
        <Chips
          options={(deps.data ?? []).map((d) => ({
            value: d.id,
            label: `${d.emoji ?? ""} ${d.name}`.trim(),
          }))}
          value={departmentId}
          onChange={(v) => setDeptId(v)}
          loading={deps.isLoading}
        />
      </section>

      <section className="space-y-2">
        <div className="px-1 text-xs font-semibold uppercase tracking-wide text-tg-hint">
          Вид чек-листа
        </div>
        <Chips
          options={(Object.keys(KIND_LABEL) as AdminChecklistKind[]).map((k) => ({
            value: k,
            label: KIND_LABEL[k],
          }))}
          value={kind}
          onChange={(v) => {
            setKind(v);
          }}
        />
      </section>

      {kind === "shift" ? (
        <section className="space-y-2">
          <div className="px-1 text-xs font-semibold uppercase tracking-wide text-tg-hint">
            Зал
          </div>
          <Chips
            options={[
              { value: "common" as const, label: "Общий" },
              ...halls.map((h) => ({ value: h.id, label: h.name })),
            ]}
            value={hallSel}
            onChange={(v) => setHallSel(v)}
          />
          <div className="px-1 text-xs text-tg-hint">
            «Общий» — шаблон-подстраховка, если для зала своего нет. Закрытие
            смены всегда общее.
          </div>
        </section>
      ) : (
        <div className="rounded-xl bg-tg-secondary-bg/40 p-3 text-xs text-tg-hint">
          {kind === "close"
            ? "Закрытие смены — общий чек-лист: один на все залы. Последний пункт обычно с фотоотчётом."
            : "Чек-лист первого дня показывается новичку; зала у него нет."}
        </div>
      )}

      {tplQ.isLoading || deps.isLoading ? (
        <ListSkeleton rows={4} />
      ) : template ? (
        <TemplateEditor
          key={template.id}
          template={template}
          onSaved={invalidate}
        />
      ) : (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-4 text-center">
          <div className="text-3xl" aria-hidden>
            🗒
          </div>
          <div className="mt-1 text-sm font-semibold text-tg-text">
            Чек-листа ещё нет
          </div>
          <div className="mt-1 text-xs text-tg-hint">
            {hallName} · {KIND_LABEL[kind]}. Создай шаблон и добавь пункты — они
            сразу появятся у сотрудников.
          </div>
          <button
            type="button"
            disabled={!departmentId || createTpl.isPending}
            onClick={() => {
              haptic("selection");
              createTpl.mutate();
            }}
            className="mt-3 min-h-11 rounded-lg bg-tg-button px-4 text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {createTpl.isPending ? "Создаю…" : "Создать чек-лист"}
          </button>
        </section>
      )}

      <HallsCard />
    </SubScreen>
  );
}

// ---------------------------------------------------------------------------
// Шаблон и пункты
// ---------------------------------------------------------------------------

function TemplateEditor({
  template,
  onSaved,
}: {
  template: AdminChecklistTemplate;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(template.title);
  const [adding, setAdding] = useState(false);

  const saveTpl = useMutation({
    mutationFn: (body: { title?: string; is_active?: boolean }) =>
      patchAdminChecklist(template.id, body),
    onSuccess: () => onSaved(),
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const addItem = useMutation({
    mutationFn: (body: { title: string; requires_photo: boolean }) =>
      createChecklistItem(template.id, body),
    onSuccess: () => {
      onSaved();
      setAdding(false);
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const items = template.items;

  return (
    <>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="flex items-center gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => {
              const next = title.trim();
              if (next && next !== template.title) saveTpl.mutate({ title: next });
              else setTitle(template.title);
            }}
            maxLength={200}
            className="min-w-0 flex-1 rounded-lg bg-tg-bg/60 px-3 py-2 text-sm font-semibold text-tg-text"
            aria-label="Название чек-листа"
          />
          {saveTpl.isPending && <Spinner />}
        </div>
        <TgToggle
          checked={template.is_active}
          label={template.is_active ? "Включён у сотрудников" : "Выключен"}
          onChange={(v) => saveTpl.mutate({ is_active: v })}
        />
        <div className="text-xs text-tg-hint">
          {items.length} пунктов · фотоотчёт обязателен у{" "}
          {items.filter((i) => i.requires_photo).length}
        </div>
      </section>

      <section className="space-y-2">
        {items.map((item, index) => (
          <ItemEditor
            key={item.id}
            item={item}
            isFirst={index === 0}
            isLast={index === items.length - 1}
            onSaved={onSaved}
            onMove={async (dir) => {
              const neighbour = items[index + dir];
              if (!neighbour) return;
              try {
                await patchChecklistItem(item.id, {
                  sort_order: neighbour.sort_order,
                });
                await patchChecklistItem(neighbour.id, {
                  sort_order: item.sort_order,
                });
                onSaved();
              } catch (e) {
                void showAlert(humanizeApiError(e));
              }
            }}
          />
        ))}
        {items.length === 0 && (
          <div className="rounded-xl bg-tg-secondary-bg/40 p-3 text-xs text-tg-hint">
            Пока ни одного пункта. Добавь первый — иначе сотрудник увидит пустой
            экран.
          </div>
        )}
      </section>

      {adding ? (
        <AddItemForm
          busy={addItem.isPending}
          onCancel={() => setAdding(false)}
          onSubmit={(title, requiresPhoto) =>
            addItem.mutate({ title, requires_photo: requiresPhoto })
          }
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setAdding(true);
          }}
          className="min-h-11 w-full rounded-xl border border-dashed border-tg-hint/40 text-sm text-tg-text"
        >
          ＋ Добавить пункт
        </button>
      )}
    </>
  );
}

function AddItemForm({
  busy,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (title: string, requiresPhoto: boolean) => void;
}) {
  const [title, setTitle] = useState("");
  const [photo, setPhoto] = useState(false);
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
      <textarea
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        rows={2}
        maxLength={500}
        placeholder="Что сделать? Например: протереть столы 400–500"
        className="w-full rounded-lg bg-tg-bg/60 p-2 text-sm text-tg-text"
      />
      <TgToggle
        checked={photo}
        label="Закрывается только фотоотчётом"
        onChange={setPhoto}
      />
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy || !title.trim()}
          onClick={() => onSubmit(title.trim(), photo)}
          className="min-h-11 flex-1 rounded-lg bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
        >
          Добавить
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="min-h-11 rounded-lg bg-tg-bg/60 px-3 text-sm text-tg-text"
        >
          Отмена
        </button>
      </div>
    </section>
  );
}

function ItemEditor({
  item,
  isFirst,
  isLast,
  onSaved,
  onMove,
}: {
  item: AdminChecklistItem;
  isFirst: boolean;
  isLast: boolean;
  onSaved: () => void;
  onMove: (dir: -1 | 1) => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [description, setDescription] = useState(item.description ?? "");

  const save = useMutation({
    mutationFn: (body: Parameters<typeof patchChecklistItem>[1]) =>
      patchChecklistItem(item.id, body),
    onSuccess: () => {
      onSaved();
      setOpen(false);
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const remove = useMutation({
    mutationFn: () => deleteChecklistItem(item.id),
    onSuccess: () => onSaved(),
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setOpen(!open);
          }}
          className="min-w-0 flex-1 text-left"
        >
          <div className="text-sm text-tg-text">{item.title}</div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-tg-hint">
            {item.requires_photo && <span>📷 фотоотчёт</span>}
            {!item.is_mandatory && <span>(опц.)</span>}
            {item.condition_position && (
              <span>только «{item.condition_position}»</span>
            )}
          </div>
        </button>
        <div className="flex shrink-0 flex-col gap-1">
          <button
            type="button"
            aria-label="Выше"
            disabled={isFirst}
            onClick={() => onMove(-1)}
            className="h-11 w-11 rounded-md bg-tg-bg/60 text-xs text-tg-text disabled:opacity-30"
          >
            ↑
          </button>
          <button
            type="button"
            aria-label="Ниже"
            disabled={isLast}
            onClick={() => onMove(1)}
            className="h-11 w-11 rounded-md bg-tg-bg/60 text-xs text-tg-text disabled:opacity-30"
          >
            ↓
          </button>
        </div>
      </div>

      {open && (
        <div className="mt-3 space-y-2 border-t border-tg-hint/15 pt-3">
          <textarea
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            rows={2}
            maxLength={500}
            className="w-full rounded-lg bg-tg-bg/60 p-2 text-sm text-tg-text"
            placeholder="Пункт"
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            maxLength={1000}
            className="w-full rounded-lg bg-tg-bg/60 p-2 text-sm text-tg-text"
            placeholder="Пояснение (необязательно)"
          />
          <TgToggle
            checked={item.requires_photo}
            label="Закрывается только фотоотчётом"
            onChange={(v) => save.mutate({ requires_photo: v })}
          />
          <TgToggle
            checked={item.is_mandatory}
            label="Обязательный пункт"
            onChange={(v) => save.mutate({ is_mandatory: v })}
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={save.isPending || !title.trim()}
              onClick={() =>
                save.mutate({
                  title: title.trim(),
                  description: description.trim() || null,
                })
              }
              className="min-h-11 flex-1 rounded-lg bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              Сохранить
            </button>
            <button
              type="button"
              disabled={remove.isPending}
              onClick={async () => {
                const ok = await showConfirm(
                  `Удалить пункт «${item.title}»? Отметки в уже пройденных сменах исчезнут.`,
                );
                if (ok) remove.mutate();
              }}
              className="min-h-11 rounded-lg bg-status-busy/15 px-3 text-sm text-status-busy"
            >
              Удалить
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Залы
// ---------------------------------------------------------------------------

function HallsCard() {
  const qc = useQueryClient();
  const hallsQ = useQuery({
    queryKey: ["admin", "halls"],
    queryFn: fetchAdminHalls,
  });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");

  const invalidate = () => {
    haptic("success");
    void qc.invalidateQueries({ queryKey: ["admin", "halls"] });
    void qc.invalidateQueries({ queryKey: ["hr-halls"] });
  };

  const create = useMutation({
    mutationFn: (title: string) => createAdminHall(title),
    onSuccess: () => {
      setName("");
      invalidate();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const patch = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: number;
      body: { name?: string; is_active?: boolean };
    }) => patchAdminHall(id, body),
    onSuccess: () => invalidate(),
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen(!open);
        }}
        className="flex w-full items-center justify-between text-left"
      >
        <div>
          <div className="text-sm font-semibold text-tg-text">Залы ресторана</div>
          <div className="text-xs text-tg-hint">
            {hallsQ.data?.length ?? 0} залов · от них зависит выбор у официанта
          </div>
        </div>
        <span className="text-tg-hint">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-2">
          {(hallsQ.data ?? []).map((hall) => (
            <div
              key={hall.id}
              className="flex items-center gap-2 rounded-lg bg-tg-bg/50 p-2"
            >
              <input
                defaultValue={hall.name}
                onBlur={(e) => {
                  const next = e.target.value.trim();
                  if (next && next !== hall.name)
                    patch.mutate({ id: hall.id, body: { name: next } });
                  else e.target.value = hall.name;
                }}
                maxLength={120}
                className="min-w-0 flex-1 rounded-md bg-tg-secondary-bg px-2 py-1 text-sm text-tg-text"
                aria-label={`Название зала ${hall.name}`}
              />
              <Checkbox
                checked={hall.is_active}
                label="Вкл"
                onChange={(v) =>
                  patch.mutate({ id: hall.id, body: { is_active: v } })
                }
              />
            </div>
          ))}
          <div className="flex gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              placeholder="Название нового зала"
              className="min-w-0 flex-1 rounded-lg bg-tg-bg/60 px-3 py-2 text-sm text-tg-text"
            />
            <button
              type="button"
              disabled={create.isPending || !name.trim()}
              onClick={() => create.mutate(name.trim())}
              className="min-h-11 rounded-lg bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              ＋
            </button>
          </div>
          <div className="text-xs text-tg-hint">
            После заведения зала создай для него чек-лист открытия: выбери зал
            выше и нажми «Создать чек-лист».
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Мелкие элементы
// ---------------------------------------------------------------------------

function Chips<T extends string | number>({
  options,
  value,
  onChange,
  loading,
}: {
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (v: T) => void;
  loading?: boolean;
}) {
  if (loading) return <ListSkeleton rows={1} />;
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          onClick={() => {
            haptic("selection");
            onChange(o.value);
          }}
          className={[
            "min-h-11 rounded-full px-3 text-xs transition-colors",
            o.value === value
              ? "bg-tg-button text-tg-button-text"
              : "bg-tg-secondary-bg text-tg-hint",
          ].join(" ")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
