/**
 * Группировка превью передачи смены (13.11.2026).
 *
 * Главное правило: проблема с категорией «гость» не должна остаться в общем
 * списке проблем. Иначе она тонет среди сломанного оборудования, хотя именно
 * её принимающий должен прочитать первой.
 */
import { describe, expect, it } from "vitest";
import type { HrHandoverItem } from "@/api/handovers";
import { groupPreview } from "./previewGroups";

function item(
  id: number,
  kind: "task" | "issue",
  title: string,
  category: string | null = null,
): HrHandoverItem {
  return {
    id,
    kind,
    ref_id: id,
    title,
    status: "open",
    meta: null,
    category,
  };
}

describe("groupPreview", () => {
  it("выносит гостей отдельно от остальных проблем", () => {
    const groups = groupPreview([
      item(1, "task", "Закрыть кассу"),
      item(2, "issue", "Сломался блендер", "equipment"),
      item(3, "issue", "Гость ждёт столик у окна", "guest"),
    ]);

    expect(groups.map((g) => [g.key, g.items.map((i) => i.title)])).toEqual([
      ["tasks", ["Закрыть кассу"]],
      ["issues", ["Сломался блендер"]],
      ["guests", ["Гость ждёт столик у окна"]],
    ]);
  });

  it("не дублирует гостя в проблемах и переживает пустой список", () => {
    const groups = groupPreview([item(1, "issue", "Жалоба на официанта", "guest")]);

    expect(groups[1].items).toEqual([]);
    expect(groups[2].items).toHaveLength(1);
    expect(groupPreview([]).every((g) => g.items.length === 0)).toBe(true);
  });

  it("задачи без категории остаются поручениями", () => {
    const groups = groupPreview([item(1, "task", "Проверить стоп-лист")]);
    expect(groups[0].items).toHaveLength(1);
    expect(groups[2].items).toEqual([]);
  });
});
