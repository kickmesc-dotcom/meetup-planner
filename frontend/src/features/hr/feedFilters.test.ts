// @vitest-environment jsdom
/**
 * Сохранённые фильтры ленты: что переживает перезапуск, а что нет.
 *
 * Главный риск здесь — не «не сохранилось», а «сохранилось чужое»: мусор в
 * хранилище или фильтры предыдущего человека на этом телефоне привели бы к
 * пустой ленте или 403. Поэтому проверяем и восстановление, и отбрасывание
 * мусора, и то, что сброс не воскрешается.
 */
import { afterEach, describe, expect, it } from "vitest";
import {
  readFeedFilters,
  saveFeedFilters,
  type FeedFilterState,
} from "./feedFilters";

const EMPTY: FeedFilterState = { employeeId: null, departmentId: null, kinds: [] };

afterEach(() => window.localStorage.clear());

describe("feedFilters", () => {
  it("без сохранения возвращает пустой фильтр", () => {
    expect(readFeedFilters(1)).toEqual(EMPTY);
  });

  it("сохраняет и читает срез на сотрудника", () => {
    saveFeedFilters(7, {
      employeeId: 5,
      departmentId: 2,
      kinds: ["task_status", "task_issue"],
    });

    expect(readFeedFilters(7)).toEqual({
      employeeId: 5,
      departmentId: 2,
      kinds: ["task_status", "task_issue"],
    });
    // Другой человек на этом же устройстве среза не наследует.
    expect(readFeedFilters(8)).toEqual(EMPTY);
  });

  it("отбрасывает неизвестные типы, дубли и кривые id", () => {
    window.localStorage.setItem(
      "semitask.feed.filters.v1:3",
      JSON.stringify({
        employeeId: -1,
        departmentId: "2",
        kinds: ["kudos", "kudos", "made_up", 5],
      }),
    );

    expect(readFeedFilters(3)).toEqual({ employeeId: null, departmentId: null, kinds: ["kudos"] });
  });

  it("мусор вместо JSON — обычная лента, а не падение", () => {
    window.localStorage.setItem("semitask.feed.filters.v1:4", "{не json");
    expect(readFeedFilters(4)).toEqual(EMPTY);
  });

  it("сброс записывается и не воскрешает старый срез", () => {
    saveFeedFilters(9, { employeeId: 1, departmentId: 1, kinds: ["kudos"] });
    saveFeedFilters(9, EMPTY);

    expect(readFeedFilters(9)).toEqual(EMPTY);
  });
});
