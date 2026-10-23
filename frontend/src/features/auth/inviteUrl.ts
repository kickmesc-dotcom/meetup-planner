/**
 * Разбор адреса приглашения: `<сайт>/invite?token=…`.
 *
 * Правило то же, что у сброса пароля: токен принимается только на своей
 * странице. Иначе любой `?token=` на главной открывал бы форму присоединения к
 * чужой организации — а это уже доступ к данным клиента.
 */

const INVITE_SEGMENT = "/invite";

function parse(href?: string): URL | null {
  const raw = href ?? (typeof window === "undefined" ? "" : window.location.href);
  if (!raw) return null;
  try {
    return new URL(raw);
  } catch {
    return null;
  }
}

/** Токен приглашения из адреса — или `null`, если это не `/invite`. */
export function inviteTokenFromUrl(href?: string): string | null {
  const url = parse(href);
  if (!url) return null;
  const path = url.pathname.replace(/\/+$/, "");
  if (path !== INVITE_SEGMENT && !path.endsWith(INVITE_SEGMENT)) return null;
  const token = url.searchParams.get("token");
  return token && token.trim() ? token.trim() : null;
}

/**
 * Убрать токен из адресной строки.
 *
 * Приглашение одноразовое: после принятия ссылке незачем оставаться в истории
 * браузера и в чужих логах.
 */
export function clearInviteTokenFromUrl(): void {
  if (typeof window === "undefined") return;
  const url = parse();
  if (!url) return;
  const path = url.pathname.replace(/\/+$/, "").replace(/\/invite$/, "") || "/";
  try {
    window.history.replaceState(null, "", `${path}${url.hash}`);
  } catch {
    // старый webview без history API — экран всё равно уже открыт
  }
}
