import type { HrHandoverItem } from "@/api/handovers";

/**
 * Три блока превью сдачи: поручения, проблемы и гости.
 *
 * Правило живёт отдельной функцией, а не внутри экрана: «гость» — это проблема
 * категории `guest`, и если однажды появится вторая такая категория (например,
 * жалобы), менять её нужно в одном месте.
 *
 * Порядок блоков — тот, в котором их читает принимающий: сначала что не
 * доделано, потом что сломано, потом гости. Пустая группа остаётся в массиве,
 * чтобы экран сам решал, рисовать ли заголовок с нулём.
 */
export type PreviewGroupKey = "tasks" | "issues" | "guests";

export interface PreviewGroup {
  key: PreviewGroupKey;
  items: HrHandoverItem[];
}

export const GUEST_CATEGORY = "guest";

export function groupPreview(items: HrHandoverItem[]): PreviewGroup[] {
  return [
    {
      key: "tasks",
      items: items.filter((item) => item.kind === "task"),
    },
    {
      key: "issues",
      items: items.filter(
        (item) => item.kind === "issue" && item.category !== GUEST_CATEGORY,
      ),
    },
    {
      key: "guests",
      items: items.filter(
        (item) => item.kind === "issue" && item.category === GUEST_CATEGORY,
      ),
    },
  ];
}
