import { api } from "./client";

/**
 * «Спасибо коллеге» (план, 8.4).
 *
 * Сервер решает, кому можно сказать спасибо и сколько раз: фронтенд не
 * повторяет эти правила, чтобы они не разъехались. Ответ на «спасибо» — вся
 * неделя сразу, поэтому после нажатия не нужен второй запрос за топом: экран
 * показывает новое число тем же движением.
 */

export interface KudosTopRow {
  employee_id: number;
  display_name: string;
  department_id: number | null;
  count: number;
}

export interface KudosWeek {
  /** Начало и конец недели (Пн–вс) — тот же период, что у рейтинга опыта. */
  since: string;
  until: string;
  top: KudosTopRow[];
  received: number;
  given: number;
  my_place: number | null;
  /** Сколько благодарностей ещё можно отдать сегодня. */
  today_left: number;
  max_per_day: number;
  /** Скольким людям вообще доступно «спасибо». Ноль — коллег нет. */
  can_thank: number;
}

export interface KudosPerson {
  employee_id: number;
  display_name: string;
  department_id: number | null;
  position: string | null;
  badge: string | null;
}

export const fetchKudosWeek = () => api<KudosWeek>("/api/hr/kudos/week");

/** Кому можно сказать спасибо. Список считает сервер по тем же правилам. */
export const fetchKudosPeople = () =>
  api<KudosPerson[]>("/api/hr/kudos/people");

export const giveKudos = (toEmployeeId: number, message?: string) =>
  api<KudosWeek>("/api/hr/kudos", {
    method: "POST",
    body: JSON.stringify({
      to_employee_id: toEmployeeId,
      message: message?.trim() ? message.trim() : null,
    }),
  });

/**
 * Коды отказа сервера → фраза для человека.
 *
 * Сервер отвечает кодом (`self`, `daily_limit`), а не текстом: язык выбирает
 * клиент. Незнакомый код не молчит — показывается общий текст, иначе нажатие
 * выглядело бы «не сработавшим».
 *
 * Фразы лежат здесь, а не в компоненте: страж перевода считает русский текст
 * в разметке непереведённым экраном, и литерал внутри `.tsx` завёл бы файл в
 * список «ещё не переведённых» — а он переведён.
 */
const ERROR_KEYS: Record<string, string> = {
  self: "Себе спасибо не говорят — выбери коллегу.",
  out_of_scope: "Этому человеку сказать спасибо нельзя: он не в твоей команде.",
  already_today: "Сегодня ты уже благодарил(а) этого человека — завтра можно снова.",
  daily_limit: "На сегодня лимит благодарностей исчерпан. Вернись к этому завтра.",
  message_too_long: "Слишком длинная запись — хватит одной фразы.",
};

export function kudosErrorText(error: unknown): string {
  const detail =
    typeof error === "object" && error !== null && "detail" in error
      ? String((error as { detail?: unknown }).detail ?? "")
      : "";
  return ERROR_KEYS[detail] ?? "Не удалось сказать спасибо. Попробуй ещё раз.";
}
