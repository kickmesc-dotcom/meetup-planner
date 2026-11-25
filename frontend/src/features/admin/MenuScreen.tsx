import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createMenuItem,
  deleteMenuItem,
  fetchMenu,
  setMenuCurrency,
  updateMenuItem,
  type MenuDraft,
  type MenuItem,
} from "@/api/menu";
import { humanizeApiError } from "@/api/client";
import { mediaUrl, uploadPhoto } from "@/api/media";
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
/**
 * Валюты, которые предлагаем в списке.
 *
 * Сервер принимает любой код ISO-4217, но список короче, чем мир: человеку
 * нужно выбрать свою, а не искать «KZT» в полусотне строк. Если понадобится
 * ещё — добавляется здесь, без миграций и ручек.
 */
const CURRENCIES = ["RUB", "KZT", "UZS", "EUR", "USD"];

export default function MenuScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["menu"], queryFn: fetchMenu });
  const currency = q.data?.currency ?? "RUB";
  /** `"new"` — форма новой позиции, объект — правка существующей. */
  const [editing, setEditing] = useState<MenuItem | "new" | null>(null);

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["menu"] });

  const toggle = useMutation({
    mutationFn: (item: MenuItem) =>
      updateMenuItem(item.id, { is_available: !item.is_available }),
    onSuccess: (item) => {
      haptic("success");
      invalidate();
      // Подсказка после действия: позиция не удалена, а попала в стоп-лист.
      void (
        item.is_available
          ? null
          : showAlert(tx("Позиция в стоп-листе: сотрудники видят «нет в наличии»."))
      );
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const changeCurrency = useMutation({
    mutationFn: (code: string) => setMenuCurrency(code),
    onSuccess: () => {
      haptic("success");
      invalidate();
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
          currency={currency}
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
        q.data && q.data.stopped > 0
          ? tx("В стоп-листе: {count}", { count: String(q.data.stopped) })
          : tx("Что сегодня в меню: сотрудник видит это в материалах смены")
      }
      onBack={onBack}
    >
      <div className="flex items-center justify-between gap-2 rounded-card bg-tg-secondary-bg/60 px-3 py-2">
        <label htmlFor="menu-currency" className="text-xs text-tg-hint">
          {tx("Валюта цен")}
        </label>
        <select
          id="menu-currency"
          value={currency}
          disabled={changeCurrency.isPending}
          onChange={(e) => changeCurrency.mutate(e.target.value)}
          className="min-h-9 rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text disabled:opacity-50"
        >
          {CURRENCIES.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
      </div>

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
          currency={currency}
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
  currency,
  saving,
  onSubmit,
  onCancel,
}: {
  initial: MenuItem | null;
  categories: string[];
  currency: string;
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
  /**
   * Снимок уже загружен на сервер и живёт отдельно от формы.
   *
   * Так замена фото — это один POST и одно поле в сохранении, а не загрузка
   * картинки на каждое «убрал позицию на сегодня». Если человек передумал и
   * нажал «Отмена», осиротевший блоб просто не попадёт в меню.
   */
  const [photo, setPhoto] = useState<{ id: number; url: string } | null>(
    initial?.photo_url && initial.photo_blob_id
      ? { id: initial.photo_blob_id, url: initial.photo_url }
      : null,
  );
  const [uploading, setUploading] = useState(false);

  const pickPhoto = async (file?: File) => {
    if (!file) return;
    setUploading(true);
    try {
      const media = await uploadPhoto(file);
      setPhoto({ id: media.id, url: media.url });
      haptic("success");
    } catch (error) {
      haptic("error");
      // Причина «фото больше 8 МБ» приходит обычным `Error`, а не ApiError:
      // показываем её текст, иначе человек не поймёт, почему снимок не ушёл.
      void showAlert(
        error instanceof Error && error.message
          ? error.message
          : humanizeApiError(error),
      );
    } finally {
      setUploading(false);
    }
  };

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
          photo_blob_id: photo?.id ?? null,
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
        label={tx("Цена, {currency}", { currency })}
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
        id="menu-photo"
        label={tx("Фото блюда")}
        hint={tx("Показывается сотруднику рядом с названием")}
      >
        {(field) => (
          <div className="flex items-center gap-2">
            {photo && (
              <img
                src={mediaUrl(photo.url) ?? undefined}
                alt=""
                width={64}
                height={64}
                className="h-16 w-16 rounded-tile object-cover"
              />
            )}
            <label className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text">
              {uploading && <Spinner size={14} />}
              {tx(photo ? "Заменить фото" : "Добавить фото")}
              <input
                {...field}
                type="file"
                accept="image/*"
                disabled={uploading}
                onChange={(e) => void pickPhoto(e.target.files?.[0])}
                className="sr-only"
              />
            </label>
            {photo && (
              <button
                type="button"
                onClick={() => setPhoto(null)}
                className="min-h-11 rounded-tile px-2 text-xs text-status-busy press"
              >
                {tx("Убрать фото")}
              </button>
            )}
          </div>
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


