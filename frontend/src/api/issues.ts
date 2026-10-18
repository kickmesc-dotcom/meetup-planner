import { api } from "./client";

/**
 * Журнал операционных проблем.
 *
 * Отдельный модуль, а не продолжение `api/hr.ts`: журнал живёт дольше смены,
 * у него свои права и своя история. Подписи категорий/срочности тоже здесь:
 * сервер отдаёт коды, чтобы их можно было менять без миграции текста.
 */

export type IssueCategory =
  | "equipment"
  | "supplies"
  | "staffing"
  | "guest"
  | "cleanliness"
  | "safety"
  | "it"
  | "other";

export type IssueSeverity = "low" | "normal" | "high" | "critical";

export type IssueStatus = "open" | "in_progress" | "resolved" | "cancelled";

export const ISSUE_CATEGORY_LABEL: Record<IssueCategory, string> = {
  equipment: "Оборудование",
  supplies: "Расходники",
  staffing: "Нехватка людей",
  guest: "Гость",
  cleanliness: "Чистота",
  safety: "Безопасность",
  it: "Техника и системы",
  other: "Другое",
};

export const ISSUE_CATEGORY_ICON: Record<IssueCategory, string> = {
  equipment: "🔧",
  supplies: "📦",
  staffing: "👥",
  guest: "🙋",
  cleanliness: "🧽",
  safety: "🦺",
  it: "💻",
  other: "🛠",
};

export const ISSUE_SEVERITY_LABEL: Record<IssueSeverity, string> = {
  low: "Не срочно",
  normal: "Обычно",
  high: "Срочно",
  critical: "Авария",
};

export const ISSUE_STATUS_LABEL: Record<IssueStatus, string> = {
  open: "Открыта",
  in_progress: "В работе",
  resolved: "Решена",
  cancelled: "Снята",
};

export interface HrIssue {
  id: number;
  title: string;
  description: string | null;
  category: IssueCategory;
  zone: string | null;
  severity: IssueSeverity;
  status: IssueStatus;
  department_id: number | null;
  department_name: string | null;
  department_emoji: string | null;
  assignee_employee_id: number | null;
  assignee_name: string | null;
  created_by_employee_id: number | null;
  created_by_name: string | null;
  task_id: number | null;
  shift_date: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  age_hours: number;
  can_edit: boolean;
  can_close: boolean;
  can_reopen: boolean;
}

export interface HrIssueEvent {
  id: number;
  kind: "created" | "status" | "assignee" | "comment" | "edited";
  from_status: IssueStatus | null;
  to_status: IssueStatus | null;
  by_employee_id: number | null;
  by_name: string | null;
  comment: string | null;
  at: string;
}

export interface HrIssueDetail extends HrIssue {
  events: HrIssueEvent[];
  can_comment: boolean;
}

export interface HrIssueSummary {
  open: number;
  in_progress: number;
  resolved: number;
  cancelled: number;
  mine_open: number;
  attention: number;
  total_open: number;
}

export interface HrIssues {
  scope: "self" | "department" | "all";
  summary: HrIssueSummary;
  items: HrIssue[];
}

export const fetchIssues = (
  opts: {
    statuses?: IssueStatus[];
    includeClosed?: boolean;
    category?: IssueCategory | null;
    mine?: boolean;
    limit?: number;
  } = {},
) => {
  const params = new URLSearchParams();
  if (opts.statuses?.length) params.set("statuses", opts.statuses.join(","));
  if (opts.includeClosed) params.set("include_closed", "true");
  if (opts.category) params.set("category", opts.category);
  if (opts.mine) params.set("mine", "true");
  if (opts.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return api<HrIssues>(`/api/issues${qs ? `?${qs}` : ""}`);
};

export const fetchIssue = (issueId: number) =>
  api<HrIssueDetail>(`/api/issues/${issueId}`);

export const createIssue = (body: {
  title: string;
  description?: string | null;
  category?: IssueCategory;
  zone?: string | null;
  severity?: IssueSeverity;
  department_id?: number | null;
  assignee_employee_id?: number | null;
  task_id?: number | null;
}) =>
  api<HrIssueDetail>("/api/issues", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateIssue = (
  issueId: number,
  body: {
    title?: string;
    description?: string | null;
    category?: IssueCategory;
    zone?: string | null;
    severity?: IssueSeverity;
    assignee_employee_id?: number | null;
    assignee_set?: boolean;
  },
) =>
  api<HrIssueDetail>(`/api/issues/${issueId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const setIssueStatus = (
  issueId: number,
  status: IssueStatus,
  comment?: string,
) =>
  api<HrIssueDetail>(`/api/issues/${issueId}/status`, {
    method: "POST",
    body: JSON.stringify({ status, comment }),
  });

export const commentIssue = (issueId: number, text: string) =>
  api<HrIssueDetail>(`/api/issues/${issueId}/comments`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
