/**
 * Разбор адреса подтверждения почты.
 *
 * Ссылка из письма ведёт на `<сайт>/verify?token=…` (`accounts.verify_link`).
 * Как и у сброса пароля, токен берём только на `/verify`: случайный `?token=`
 * на другой странице не должен запускать подтверждение чужого адреса.
 */

const VERIFY_SEGMENT = "/verify";

function parse(href?: string): URL | null {
  const raw = href ?? (typeof window === "undefined" ? "" : window.location.href);
  if (!raw) return null;
  try {
    return new URL(raw);
  } catch {
    return null;
  }
}

/** Токен из адреса — или `null`, если это не страница подтверждения. */
export function verifyTokenFromUrl(href?: string): string | null {
  const url = parse(href);
  if (!url) return null;
  const path = url.pathname.replace(/\/+$/, "");
  if (path !== VERIFY_SEGMENT && !path.endsWith(VERIFY_SEGMENT)) return null;
  const token = url.searchParams.get("token");
  return token && token.trim() ? token.trim() : null;
}

/**
 * Убрать токен из адресной строки, оставив корень.
 *
 * Ссылка одноразовая, но в истории браузера ей оставаться незачем: человек
 * поделится адресом или вернётся назад — и получит «ссылка не подходит».
 */
export function clearVerifyTokenFromUrl(): void {
  if (typeof window === "undefined") return;
  const url = parse();
  if (!url) return;
  const path = url.pathname.replace(/\/+$/, "").replace(/\/verify$/, "") || "/";
  try {
    window.history.replaceState(null, "", `${path}${url.hash}`);
  } catch {
    // старый webview без history API — экран всё равно уже открыт
  }
}
