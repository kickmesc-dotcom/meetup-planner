/**
 * Установленное приложение (M2, `docs/MOBILE_PARALLEL.md`).
 *
 * Зачем это знать. В браузере у страницы есть свой «хром»: адресная строка,
 * кнопка «назад», закладки. В режиме «на домашнем экране» ничего этого нет, и
 * человек находится в отдельном приложении — но экран входа об этом молчит,
 * хотя подсказка «внутри Telegram вход не нужен» в этом режиме бессмысленна.
 *
 * Где НЕ используем `display-mode: fullscreen`. Он совпадает и с полноэкранным
 * режимом браузера на компьютере (F11), и тогда владелец ПК увидел бы «вы в
 * приложении на телефоне». `standalone` и `minimal-ui` — только про установку.
 *
 * Подсказка показывается один раз. Флаг «уже видел» лежит в `localStorage`:
 * если его нельзя прочитать (приватный режим), показываем — лучше объяснить
 * второй раз, чем не объяснить вовсе.
 */

const HINT_KEY = "semitask.standalone_hint_seen";

const STANDALONE_QUERIES = [
  "(display-mode: standalone)",
  "(display-mode: minimal-ui)",
] as const;

/** Приложение открыто как установленное, а не как вкладка браузера. */
export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  // iOS Safari: единственный признак, который там работает — свойство
  // `navigator.standalone`, медиазапросы `display-mode` он не поддерживает.
  const nav = window.navigator as Navigator & { standalone?: boolean };
  if (nav?.standalone === true) return true;
  // jsdom (тесты) и очень старые браузеры: `matchMedia` может отсутствовать.
  if (typeof window.matchMedia !== "function") return false;
  return STANDALONE_QUERIES.some((query) => {
    try {
      return window.matchMedia(query)?.matches === true;
    } catch {
      return false;
    }
  });
}

/** Подсказку о режиме приложения стоит показать: мы в standalone и ещё не видели. */
export function shouldShowStandaloneHint(): boolean {
  if (!isStandalone()) return false;
  try {
    return localStorage.getItem(HINT_KEY) !== "1";
  } catch {
    return true;
  }
}

/**
 * Запомнить, что подсказка показана.
 *
 * Вызывается при показе, а не при закрытии: иначе человек, который просто
 * вошёл, видел бы её при каждом запуске до первого нажатия «Понятно».
 */
export function markStandaloneHintSeen(): void {
  try {
    localStorage.setItem(HINT_KEY, "1");
  } catch {
    // приватный режим — подсказка покажется ещё раз, это не поломка
  }
}
