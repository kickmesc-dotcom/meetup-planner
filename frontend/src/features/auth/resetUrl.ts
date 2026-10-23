/**
 * Разбор адреса страницы сброса пароля.
 *
 * Ссылка в письме ведёт на `<сайт>/reset?token=…` (`accounts.reset_link`).
 * Отдельный модуль, а не код внутри экрана: правило «токен берём только с
 * /reset» должно проверяться тестом, иначе случайный `?token=` на любой
 * странице приложения открывал бы форму смены пароля.
 */

const RESET_SEGMENT = "/reset";

function parse(href?: string): URL | null {
  const raw = href ?? (typeof window === "undefined" ? "" : window.location.href);
  if (!raw) return null;
  try {
    return new URL(raw);
  } catch {
    return null;
  }
}

/** Токен из адреса — или `null`, если это не страница сброса. */
export function resetTokenFromUrl(href?: string): string | null {
  const url = parse(href);
  if (!url) return null;
  const path = url.pathname.replace(/\/+$/, "");
  if (path !== RESET_SEGMENT && !path.endsWith(RESET_SEGMENT)) return null;
  const token = url.searchParams.get("token");
  return token && token.trim() ? token.trim() : null;
}

/**
 * Убрать токен из адресной строки, оставив ту же страницу.
 *
 * Ссылка одноразовая, но оставаться в истории браузера ей незачем: человек
 * поделится адресом или вернётся назад — и получит «ссылка не подходит».
 */
export function clearResetTokenFromUrl(): void {
  if (typeof window === "undefined") return;
  const url = parse();
  if (!url) return;
  const path = url.pathname.replace(/\/+$/, "").replace(/\/reset$/, "") || "/";
  try {
    window.history.replaceState(null, "", `${path}${url.hash}`);
  } catch {
    // старый webview без history API — форма всё равно уже открыта
  }
}
