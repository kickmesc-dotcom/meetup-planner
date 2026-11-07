import { useSyncExternalStore } from "react";

/**
 * Тост — короткое подтверждение успеха (11promt-TEACHER §7.3).
 *
 * Зачем отдельно от `showAlert`. Нативный алерт останавливает работу: человек
 * обязан нажать «ОК» даже когда ничего не сломалось. Для успеха это лишний шаг
 * на каждом действии. Алерт остаётся там, где нужен выбор (ошибка, риск
 * потери данных), а «Сохранено» должно просто появиться и уйти.
 *
 * Почему не контекст React. Тост зовут из обработчиков мутаций по всему
 * приложению, в том числе вне дерева провайдеров. Маленький внешний стор
 * дешевле и не заставляет прокидывать контекст через каждый экран.
 *
 * UI_UX_PRO_MAX §4 `undo-support`: у удаления есть действие «Отменить». Оно
 * живёт в том же тосте, а не в отдельном диалоге: человек уже подтвердил
 * удаление и не должен отвечать на второй вопрос.
 */
export type ToastKind = "success" | "info";

export interface ToastAction {
  label: string;
  run: () => void | Promise<void>;
}

export interface Toast {
  id: number;
  text: string;
  kind: ToastKind;
  action?: ToastAction;
}

/** Больше трёх одновременно — уже очередь, а не подтверждение. */
const MAX_VISIBLE = 3;

let items: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function showToast(
  text: string,
  kind: ToastKind = "success",
  action?: ToastAction,
): void {
  const clean = text.trim();
  if (!clean) return;
  items = [
    ...items,
    { id: nextId++, text: clean, kind, ...(action ? { action } : {}) },
  ].slice(-MAX_VISIBLE);
  emit();
}

export function dismissToast(id: number): void {
  const next = items.filter((item) => item.id !== id);
  if (next.length === items.length) return;
  items = next;
  emit();
}

/** Только для тестов: между кейсами не должно оставаться чужих сообщений. */
export function clearToasts(): void {
  if (items.length === 0) return;
  items = [];
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, () => items, () => items);
}
