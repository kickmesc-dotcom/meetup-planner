/**
 * «Новые с прошлого визита» — приём из соцсетей, который здесь уместен.
 *
 * Зачем: лента событий смены — это хронология, а не чат. Вернувшись после
 * обеда, человек не помнит, что уже читал, и заново просматривает вчерашние
 * строки. Отметка хранится локально (на устройстве и на сотрудника) по двум
 * причинам:
 *   • это не данные предприятия — синхронизировать «прочитано» между
 *     устройствами не нужно;
 *   • никакого нового запроса и записи в базу — лента остаётся чистой
 *     хронологией, а «новое» считается на клиенте.
 *
 * Метка ставится при уходе с экрана: пока лента открыта, новые события
 * продолжают помечаться как новые — иначе ответ коллеги во время чтения
 * «сгорал» бы без следа.
 */

const STORAGE_PREFIX = "semitask.feed.seen.v1";

/** Ключ на сотрудника: на одном устройстве могут заходить разные люди. */
export function feedSeenKey(employeeId: number): string {
  return `${STORAGE_PREFIX}:${employeeId}`;
}

/** Время последнего просмотра или `null`, если лента ещё ни разу не открывалась. */
export function readFeedSeen(employeeId: number): number | null {
  try {
    const raw = window.localStorage.getItem(feedSeenKey(employeeId));
    if (raw === null) return null;
    const value = Number(raw);
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    // Приватный режим/запрет хранилища: просто без разделителя.
    return null;
  }
}

/** Запомнить, что лента просмотрена (по умолчанию — сейчас). */
export function markFeedSeen(
  employeeId: number,
  at: number = Date.now(),
): void {
  try {
    window.localStorage.setItem(feedSeenKey(employeeId), String(at));
  } catch {
    // См. `readFeedSeen`: отсутствие хранилища не должно ломать экран.
  }
}

/**
 * Сколько верхних событий новее отметки.
 *
 * Лента приходит от новых к старым, поэтому достаточно считать подряд, пока
 * не встретилось событие не новее отметки (или битая дата — тогда дальше не
 * угадываем).
 */
export function countFreshItems(
  items: { at: string }[],
  seenAt: number | null,
): number {
  if (seenAt === null) return 0;
  let fresh = 0;
  for (const item of items) {
    const at = Date.parse(item.at);
    if (!Number.isFinite(at) || at <= seenAt) break;
    fresh += 1;
  }
  return fresh;
}
