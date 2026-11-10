import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createMenuItem,
  deleteMenuItem,
  fetchMenu,
  updateMenuItem,
  type MenuDraft,
  type MenuItem,
} from "@/api/menu";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import FormField from "@/components/FormField";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import MenuList from "@/features/menu/MenuList";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";

/**
 * Меню смены: правка внутри приложения.
 *
 * Почему экран, а не «кнопка в таблице». Меню меняется в последний момент и
 * чаще всего — с телефона: кончилась рыба, поменялась цена. Пока меню жило
 * листом Google, руководитель либо не правил его вовсе, либо правил после
 * смены. Здесь три действия, которых достаточно: убрать на сегодня, поправить,
 * добавить.
 *
 * «Убрать» — не удаление: строка остаётся, помечается «нет в наличии» и
 * возвращается одним нажатием. Удаление отдельно и с подтверждением — иначе
 * случайное нажатие стирает позицию вместе с ценой и описанием, и её заводят
 * заново.
 */
export default function MenuScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["menu"], queryFn: fetchMenu });
  /** `"new"` — форма новой позиции, объект — правка существующей. */
  const [editing, setEditing] = useState<MenuItem | "new" | null>(null);

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["menu"] });

  const toggle = useMutation({
    mutationFn: (item: MenuItem) =>
      updateMenuItem(item.id, { is_available: !item.is_available }),
    onSuccess: (item) => {
      haptic("success");
      invalidate();
      // Подсказка после действия: видно, что позиция не удалена, а спрятана.
      void (item.is_available ? null : showAlert(tx("Позиция скрыта из меню сотрудников.")));
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteMenuItem(id),
    onSuccess: () => {
      haptic("success");
      invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const save = useMutation({
    mutationFn: (draft: { id: number | null; body: MenuDraft }) =>
      draft.id === null
        ? createMenuItem(draft.body)
        : updateMenuItem(draft.id, draft.body),
    onSuccess: () => {
      haptic("success");
      setEditing(null);
      invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const askDelete = async (item: MenuItem) => {
    const ok = await showConfirm(
      tx("Удалить «{name}» из меню? Вернуть её можно будет только заново.", {
        name: item.name,
      }),
    );
    if (ok) remove.mutate(item.id);
  };

  const busyId = toggle.isPending ? (toggle.variables?.id ?? null) : null;

  if (editing) {
    return (
      <SubScreen
        title={editing === "new" ? tx("Новая позиция") : tx("Позиция меню")}
        subtitle={
          editing === "new"
            ? tx("Название, цена и группа — остальное по желанию")
            : editing.name
        }
        onBack={() => setEditing(null)}
      >
        <MenuForm
          initial={editing === "new" ? null : editing}
          categories={q.data?.categories ?? []}
          saving={save.isPending}
          onCancel={() => setEditing(null)}
          onSubmit={(body) =>
            save.mutate({ id: editing === "new" ? null : editing.id, body })
          }
        />
      </SubScreen>
    );
  }

  return (
    <SubScreen
      title={tx("Меню смены")}
      subtitle={
        q.data && q.data.hidden > 0
          ? tx("Скрыто позиций: {count}", { count: String(q.data.hidden) })
          : tx("Что сегодня в меню: сотрудник видит это в материалах смены")
      }
      onBack={onBack}
    >
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setEditing("new");
        }}
        className="min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text press"
      >
        {tx("+ Добавить позицию")}
      </button>

      {q.isPending ? (
        <section className="rounded-card bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={4} />
        </section>
      ) : q.isError ? (
        <div className="rounded-card bg-status-busy/10 p-3 text-xs text-status-busy">
          {humanizeApiError(q.error)}
        </div>
      ) : (
        <MenuList
          items={q.data?.items ?? []}
          categories={q.data?.categories ?? []}
          busyId={busyId}
          onEdit={(item) => {
            haptic("light");
            setEditing(item);
          }}
          onToggle={(item) => toggle.mutate(item)}
          onDelete={(item) => void askDelete(item)}
        />
      )}
    </SubScreen>
  );
}

/** Пустая строка цены — это «по запросу», а не ноль. */
function parsePrice(value: string): number | null {
  const trimmed = value.replace(/\s/g, "").replace(",", ".");
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? Math.round(parsed) : null;
}

function MenuForm({
  initial,
  categories,
  saving,
  onSubmit,
  onCancel,
}: {
  initial: MenuItem | null;
  categories: string[];
  saving: boolean;
  onSubmit: (body: MenuDraft) => void;
  onCancel: () => void;
}) {
  const { tx } = useTx();
  const [name, setName] = useState(initial?.name ?? "");
  const [category, setCategory] = useState(initial?.category ?? "");
  const [price, setPrice] = useState(
    initial?.price_rub === null || initial?.price_rub === undefined
      ? ""
      : String(initial.price_rub),
  );
  const [description, setDescription] = useState(initial?.description ?? "");

  const [nameTouched, setNameTouched] = useState(false);
  /** Один символ в названии — почти наверняка опечатка: говорим сразу. */
  const nameError =
    nameTouched && name.trim().length > 0 && name.trim().length < 2
      ? tx("Название короче двух символов")
      : undefined;
  const canSave = name.trim().length >= 2 && !saving;

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        onSubmit({
          name: name.trim(),
          category: category.trim() || undefined,
          price_rub: parsePrice(price),
          description: description.trim() || null,
        });
      }}
    >
      <FormField
        id="menu-name"
        label={tx("Название")}
        required
        error={nameError}
      >
        {(field) => (
          <input
            {...field}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setNameTouched(true)}
            maxLength={160}
            placeholder={tx("Например: Борщ с пампушкой")}
            className="min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text"
          />
        )}
      </FormField>

      <FormField
        id="menu-category"
        label={tx("Группа")}
        hint={tx("Пусто — общий список «Меню»")}
      >
        {(field) => (
          <>
            <input
              {...field}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              maxLength={64}
              list="menu-categories"
              placeholder={tx("Супы, Горячее, Бар")}
              className="min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text"
            />
            <datalist id="menu-categories">
              {categories.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </>
        )}
      </FormField>

      <FormField
        id="menu-price"
        label={tx("Цена, ₽")}
        hint={tx("Оставь пустой — будет «по запросу»")}
      >
        {(field) => (
          <input
            {...field}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            inputMode="numeric"
            className="min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text"
          />
        )}
      </FormField>

      <FormField
        id="menu-description"
        label={tx("Описание")}
        hint={tx("Состав или подача — по желанию")}
      >
        {(field) => (
          <textarea
            {...field}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={300}
            rows={2}
            className="w-full rounded-tile bg-tg-secondary-bg px-3 py-2 text-sm text-tg-text"
          />
        )}
      </FormField>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!canSave}
          aria-busy={saving}
          className="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50 press"
        >
          {saving && <Spinner size={14} />}
          {saving ? tx("Сохраняю…") : tx("Сохранить")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg text-sm text-tg-text press"
        >
          {tx("Отмена")}
        </button>
      </div>
    </form>
  );
}


