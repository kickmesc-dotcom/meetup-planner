/**
 * UI_UX_PRO_MAX §3 `form-autosave`: черновик длинной формы переживает
 * перезагрузку страницы.
 *
 * Почему в `localStorage`, а не на сервере. Мастер настройки организации
 * проходят один раз и до первой сохранённой организации: черновик — это
 * «человек не потерял введённое», а не совместный документ. Серверная ручка
 * потребовала бы организации, которой на этом шаге ещё нет.
 *
 * Почему всё в try/catch. В приватном режиме Safari `localStorage` бросает при
 * записи, а в некоторых встроенных WebView доступ к нему запрещён политикой.
 * Черновик — удобство: без него форма должна работать, а не падать.
 */

export function readDraft<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function writeDraft<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* хранилище недоступно — форма работает без черновика */
  }
}

export function clearDraft(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* см. выше */
  }
}
