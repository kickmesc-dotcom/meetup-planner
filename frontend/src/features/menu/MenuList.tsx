import { useMemo } from "react";
import type { MenuItem } from "@/api/menu";
import Icon from "@/components/Icon";
import { Spinner } from "@/components/Spinner";
import { useTx } from "@/i18n";

/**
 * Список меню по группам. Одна разметка на две роли: сотрудник читает, а
 * руководителю те же строки дают кнопки. Вторая копия верстки разошлась бы с
 * первой на первой же правке цены или скрытия позиции.
 *
 * Порядок групп берём с сервера (`categories`): он же решает, что «Супы» идут
 * раньше «Горячего». Здесь только раскладка по группам — никакой сортировки,
 * иначе подписи групп и строки поехали бы вразнобой.
 */
export default function MenuList({
  items,
  categories,
  onEdit,
  onToggle,
  onDelete,
  busyId = null,
}: {
  items: MenuItem[];
  categories: string[];
  onEdit?: (item: MenuItem) => void;
  onToggle?: (item: MenuItem) => void;
  onDelete?: (item: MenuItem) => void;
  busyId?: number | null;
}) {
  const { tx } = useTx();
  const groups = useMemo(() => {
    const byCategory = new Map<string, MenuItem[]>();
    for (const item of items) {
      const list = byCategory.get(item.category) ?? [];
      list.push(item);
      byCategory.set(item.category, list);
    }
    return categories
      .map((name) => ({ name, items: byCategory.get(name) ?? [] }))
      .filter((group) => group.items.length > 0);
  }, [items, categories]);

  if (groups.length === 0) {
    return (
      <div className="rounded-card bg-tg-secondary-bg/40 p-4 text-center text-xs text-tg-hint">
        {tx("Меню пока пустое.")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <section key={group.name} className="space-y-1.5">
          <h2 className="px-1 text-xs font-semibold uppercase tracking-wide text-tg-hint">
            {group.name}
          </h2>
          <div className="overflow-hidden rounded-card border border-tg-secondary-bg">
            {group.items.map((item) => (
              <MenuRow
                key={item.id}
                item={item}
                onEdit={onEdit}
                onToggle={onToggle}
                onDelete={onDelete}
                busy={busyId === item.id}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function MenuRow({
  item,
  onEdit,
  onToggle,
  onDelete,
  busy,
}: {
  item: MenuItem;
  onEdit?: (item: MenuItem) => void;
  onToggle?: (item: MenuItem) => void;
  onDelete?: (item: MenuItem) => void;
  busy: boolean;
}) {
  const { tx } = useTx();
  const editable = !!onEdit || !!onToggle || !!onDelete;
  return (
    <div
      data-testid={`menu-item-${item.id}`}
      className={[
        "flex items-start gap-2 border-b border-tg-secondary-bg/60 p-2.5 last:border-b-0",
        item.is_available ? "" : "bg-tg-secondary-bg/30",
        busy ? "opacity-50" : "",
      ].join(" ")}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span
            className={[
              "text-sm font-medium",
              item.is_available
                ? "text-tg-text"
                : "text-tg-hint line-through",
            ].join(" ")}
          >
            {item.name}
          </span>
          {!item.is_available && (
            <span className="text-xs text-status-busy">
              {tx("нет в наличии")}
            </span>
          )}
          <span className="ml-auto whitespace-nowrap text-sm text-tg-text">
            {item.price_rub === null
              ? tx("по запросу")
              : `${item.price_rub} ₽`}
          </span>
        </div>
        {item.description && (
          <p className="mt-0.5 text-xs text-tg-hint">{item.description}</p>
        )}
      </div>
      {editable && (
        <div className="flex shrink-0 items-center gap-1">
          {onToggle && (
            <button
              type="button"
              disabled={busy}
              aria-busy={busy}
              onClick={() => onToggle(item)}
              aria-pressed={item.is_available}
              aria-label={
                item.is_available
                  ? tx("Убрать из меню на сегодня")
                  : tx("Вернуть в меню")
              }
              className="min-h-11 rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text disabled:opacity-50"
            >
              {item.is_available ? tx("Убрать") : tx("Вернуть")}
            </button>
          )}
          {onEdit && (
            <button
              type="button"
              disabled={busy}
              aria-busy={busy}
              onClick={() => onEdit(item)}
              aria-label={tx("Изменить позицию")}
              className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg text-tg-text disabled:opacity-50"
            >
              <Icon name="edit" size={16} />
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              disabled={busy}
              aria-busy={busy}
              onClick={() => onDelete(item)}
              aria-label={tx("Удалить позицию")}
              className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-status-busy/10 text-status-busy disabled:opacity-50"
            >
              {busy ? <Spinner size={16} /> : <Icon name="trash" size={16} />}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
