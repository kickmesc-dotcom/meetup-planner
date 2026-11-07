// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearDraft, readDraft, writeDraft } from "./formDraft";

const KEY = "test.draft";

afterEach(() => {
  clearDraft(KEY);
  vi.restoreAllMocks();
});

describe("черновик формы", () => {
  it("возвращает записанное значение", () => {
    writeDraft(KEY, { step: 2, name: "Кафе" });
    expect(readDraft(KEY)).toEqual({ step: 2, name: "Кафе" });
  });

  it("после очистки черновика нет", () => {
    writeDraft(KEY, { step: 1 });
    clearDraft(KEY);
    expect(readDraft(KEY)).toBeNull();
  });

  it("битый JSON не роняет форму", () => {
    window.localStorage.setItem(KEY, "{не json");
    expect(readDraft(KEY)).toBeNull();
  });

  it("не падает, если хранилище недоступно", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => writeDraft(KEY, { step: 1 })).not.toThrow();
  });
});
