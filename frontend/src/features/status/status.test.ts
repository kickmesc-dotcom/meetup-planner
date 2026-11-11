import { describe, expect, it } from "vitest";
import { isStatusPath, statusView, type Meta } from "./status";

const META: Meta = {
  status: "ok",
  code: { build: "abc123def456", source: "env" },
  db: { provider: "amvera", host: "db…amvera.tech", alembic_version: "0075" },
};

describe("статус-страница", () => {
  it("зелёный статус только когда живы и процесс, и база", () => {
    expect(statusView(META)).toMatchObject({
      ok: true,
      dbOk: true,
      build: "abc123def456",
      version: "0075",
      provider: "amvera",
    });
  });

  it("ошибка базы делает статус проблемным, даже если процесс отвечает", () => {
    const view = statusView({
      ...META,
      db: { ...META.db, error: "OperationalError" },
    });
    expect(view.ok).toBe(false);
    expect(view.dbOk).toBe(false);
    expect(view.dbError).toBe("OperationalError");
  });

  it("пустые поля не превращаются в пустую строку на экране", () => {
    const view = statusView({
      status: "degraded",
      code: {},
      db: { provider: null, alembic_version: null },
    });
    expect(view.build).toBe("—");
    expect(view.version).toBe("—");
    expect(view.provider).toBe("—");
    expect(view.ok).toBe(false);
  });

  it("распознаёт /status с хвостовым слешем и не путает с /statuses", () => {
    expect(isStatusPath("/status")).toBe(true);
    expect(isStatusPath("/status/")).toBe(true);
    expect(isStatusPath("/statuses")).toBe(false);
    expect(isStatusPath("/")).toBe(false);
  });
});
