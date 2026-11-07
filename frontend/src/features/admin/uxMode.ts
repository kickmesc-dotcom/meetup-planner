import { useSyncExternalStore } from "react";

/**
 * Подробность интерфейса (11promt-TEACHER, §11).
 *
 * Зачем это вообще. У продукта один и тот же кабинет открывают два разных
 * человека: владелец в первый день («где пригласить людей?») и руководитель в
 * сотый («покажи очередь задач»). Первому 37 карточек мешают, второму
 * упрощённый экран мешает не меньше. Поэтому это не два продукта и не тариф,
 * а одна и та же навигация с разной степенью раскрытия.
 *
 * Почему по умолчанию «расширенный». Приложение уже работает у клиентов, и
 * молча спрятать половину разделов — регресс для тех, кто ими пользуется.
 * Промпт прямо запрещает переключать режим автоматически без причины:
 * упрощение — осознанный выбор в настройках, а не сюрприз.
 *
 * Почему localStorage, а не сервер. Это предпочтение вида, как тема, а не
 * данные организации. Оно не должно ждать сети и не требует миграции.
 */
export type UxMode = "simple" | "advanced";

const KEY = "ux.mode.v1";

/** Слушатели внутри вкладки: `storage` приходит только из других вкладок. */
const listeners = new Set<() => void>();

export function readUxMode(): UxMode {
  try {
    return localStorage.getItem(KEY) === "simple" ? "simple" : "advanced";
  } catch {
    // Приватный режим: показываем полный интерфейс, а не пустой.
    return "advanced";
  }
}

export function setUxMode(mode: UxMode): void {
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    // Запомнить не удалось — режим всё равно применится на этом экране.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useUxMode(): UxMode {
  return useSyncExternalStore(subscribe, readUxMode, () => "advanced");
}
