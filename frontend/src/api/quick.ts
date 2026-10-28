import { api } from "./client";

/**
 * «Сказал — стало поручением» (план, 8.5).
 *
 * Разбор фразы делает сервер: правила срока и исполнителя живут в одном месте
 * (`services/hr_quick.py`), а не дублируются в интерфейсе. Здесь — только типы
 * и запросы.
 *
 * Порядок ровно такой, каким его видит человек: пока он говорит, приходит
 * черновик (`parse` ничего не пишет и никого не будит), а создаётся поручение
 * отдельным нажатием. Поэтому «ввёл и передумал» не оставляет в чужом
 * колокольчике висящую задачу.
 */

export interface QuickPerson {
  id: number;
  name: string;
  position: string | null;
  department_id: number | null;
}

export type QuickDueKind = "time" | "day" | "hours" | "days" | "shift_close";

export interface QuickDraft {
  title: string;
  text: string;
  scope: "employee" | "department";
  assignee: QuickPerson | null;
  candidates: QuickPerson[];
  department_id: number | null;
  due_at: string | null;
  due_kind: QuickDueKind;
  priority: "low" | "normal" | "high";
  requires_photo: boolean;
  requires_review: boolean;
  /** Чего не хватило: `assignee` — не понял(а), кому; `department` — нет отдела. */
  unclear: string[];
}

export interface QuickTaskCreated {
  id: number;
  title: string;
  due_at: string | null;
  status: string;
  scope: string;
  assignee_name: string | null;
}

export interface QuickTaskBody {
  text: string;
  title?: string | null;
  assignee_employee_id?: number | null;
  department_id?: number | null;
  scope?: "employee" | "department";
  due_at?: string | null;
  priority?: "low" | "normal" | "high";
  requires_photo?: boolean;
  requires_review?: boolean;
}

export const fetchQuickPeople = () =>
  api<QuickPerson[]>("/api/hr/quick/people");

export const parseQuickText = (text: string) =>
  api<QuickDraft>("/api/hr/quick/parse", {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const createQuickTask = (body: QuickTaskBody) =>
  api<QuickTaskCreated>("/api/hr/quick/task", {
    method: "POST",
    body: JSON.stringify(body),
  });

/**
 * Коды отказа сервера → фраза для человека.
 *
 * Текст живёт здесь, а не в разметке: страж перевода считает русские строки в
 * `.tsx` непереведённым экраном, а этот экран переведён.
 */
const ERROR_KEYS: Record<string, string> = {
  assignee_required: "Выбери, кому поручить: без исполнителя поручение не создать.",
  assignee_out_of_scope:
    "Этому человеку поручить нельзя — он не в твоей команде. Выбери из списка.",
  department_required: "Не понял подразделение — выбери его в списке.",
  assignee_required_for_department: "В подразделении никого нет — выбери человека.",
  empty_title: "Не расслышал задачу. Скажи одной фразой, что нужно сделать.",
  aup_required: "Поручения выдаёт руководитель — эта кнопка не для сотрудника.",
  simulation_self_only:
    "В режиме проверки можно ставить задачи только себе — выйди из проверки.",
  bad_priority: "Не понял срочность. Выбери обычную.",
  bad_scope: "Не понял, кому адресовано. Выбери человека или отдел.",
};

export function quickErrorText(error: unknown): string {
  const detail =
    typeof error === "object" && error !== null && "detail" in error
      ? String((error as { detail?: unknown }).detail ?? "")
      : "";
  return ERROR_KEYS[detail] ?? "Не удалось создать поручение. Попробуй ещё раз.";
}
