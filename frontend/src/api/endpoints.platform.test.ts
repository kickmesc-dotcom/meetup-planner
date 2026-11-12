// @vitest-environment jsdom
/**
 * Адреса и тела запросов: фото, смены, организации, быстрые поручения,
 * приватность, платформа и план обучения.
 *
 * Здесь же — две ветки, которые видит человек: повтор загрузки фото на 5xx и
 * отказ «файл слишком большой даже после сжатия».
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));

vi.mock("./client", () => {
  class ApiError extends Error {
    status: number;
    detail: string;
    constructor(status: number, detail: string) {
      super(`${status}: ${detail}`);
      this.status = status;
      this.detail = detail;
    }
  }
  return {
    api: (...args: unknown[]) => mocks.api(...args),
    ApiError,
    apiPublicUrl: (path: string) => `https://api.test${path}`,
    getApiBase: () => "",
  };
});
vi.mock("@/tg/webapp", () => ({ getInitData: () => "" }));

import { ApiError } from "./client";
import {
  MAX_UPLOAD_BYTES,
  mediaUrl,
  shrinkImage,
  telegramPhotoUrl,
  uploadPhoto,
} from "./media";
import {
  applyShiftTemplate,
  bulkSaveShifts,
  clearShiftCells,
  copyShiftWeek,
  deleteShift,
  deleteShiftTemplate,
  fetchShiftTemplates,
  fetchShiftWeek,
  moveShift,
  saveShift,
  saveShiftTemplate,
} from "./shifts";
import {
  acceptInvitation,
  cancelInvoice,
  createBranch,
  createInvitation,
  createInvoice,
  createOrganization,
  fetchBranches,
  fetchBranchEmployees,
  fetchCurrentOrg,
  fetchInvitations,
  fetchOrgBilling,
  fetchOrgDomain,
  fetchOrgMembers,
  fetchOrgPlan,
  fetchInvitations as _unused,
  joinOrganization,
  previewInvitation,
  requestInvoicePaid,
  revokeInvitation,
  saveOrgDomain,
  transferEmployee,
  updateOrgMemberRole,
  verifyOrgDomain,
  clearOrgDomain,
} from "./orgs";
import {
  createQuickTask,
  fetchQuickPeople,
  parseQuickText,
  quickErrorText,
} from "./quick";
import {
  cancelOrgDeletion,
  fetchAudit,
  fetchOrgExport,
  fetchPrivacy,
  requestOrgDeletion,
  saveExportFile,
} from "./privacy";
import { applyImport, previewImport, sampleCsv } from "./imports";
import {
  cancelPlatformInvoice,
  confirmPlatformInvoice,
  fetchPlatformInvoices,
  fetchPlatformMe,
  fetchPlatformOrgs,
  fetchPlatformSummary,
  patchPlatformOrg,
} from "./platform";
import { translateTexts } from "./translate";
import {
  exitSimulation,
  fetchActiveSimulation,
  startSimulation,
} from "./simulation";
import {
  clearTrainingDay,
  fetchTrainingPlan,
  patchTrainingPlan,
  setTrainingDay,
} from "./hrTrainingPlan";

beforeEach(() => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValue(undefined);
  // jsdom не умеет blob-ссылки и декодирование картинок, а `shrinkImage` без
  // них падает до canvas. Заглушки повторяют браузер: маленький файл
  // возвращается как есть, большой упирается в лимит.
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: vi.fn(() => "blob:test"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLImageElement.prototype, "decode", {
    configurable: true,
    value: () => Promise.resolve(),
  });
});

describe("media", () => {
  it("mediaUrl: null и абсолютный адрес остаются как есть", () => {
    expect(mediaUrl(null)).toBeNull();
    expect(mediaUrl(undefined)).toBeNull();
    expect(mediaUrl("https://cdn.test/a.jpg")).toBe("https://cdn.test/a.jpg");
  });

  it("mediaUrl: относительный путь идёт через apiPublicUrl", () => {
    expect(mediaUrl("/api/media/1")).toBe("https://api.test/api/media/1");
    expect(telegramPhotoUrl("/api/media/2")).toBe("https://api.test/api/media/2");
  });

  it("не-картинку и gif не трогает", async () => {
    const pdf = new File(["x"], "a.pdf", { type: "application/pdf" });
    expect(await shrinkImage(pdf)).toBe(pdf);
    const gif = new File(["x"], "a.gif", { type: "image/gif" });
    expect(await shrinkImage(gif)).toBe(gif);
  });

  it("загружает фото через свой домен и ставит FormData", async () => {
    mocks.api.mockResolvedValueOnce({ id: 1 });
    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    await uploadPhoto(file);
    const [path, init, options] = mocks.api.mock.calls[0];
    expect(path).toBe("/api/media");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
    expect(options).toEqual({ sameOrigin: true, timeoutMs: 90_000 });
  });

  it("повторяет загрузку на 503 и не повторяет на 400", async () => {
    vi.useFakeTimers();
    try {
      mocks.api
        .mockRejectedValueOnce(new ApiError(503, "unavailable"))
        .mockResolvedValueOnce({ id: 2 });
      const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
      const pending = uploadPhoto(file);
      await vi.advanceTimersByTimeAsync(900);
      await expect(pending).resolves.toEqual({ id: 2 });
      expect(mocks.api).toHaveBeenCalledTimes(2);

      mocks.api.mockReset();
      mocks.api.mockRejectedValueOnce(new ApiError(400, "not_an_image"));
      await expect(uploadPhoto(file)).rejects.toBeInstanceOf(ApiError);
      expect(mocks.api).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("отказывает до отправки, если файл больше лимита даже после сжатия", async () => {
    const big = new File([new Uint8Array(MAX_UPLOAD_BYTES + 1)], "big.jpg", {
      type: "image/jpeg",
    });
    await expect(uploadPhoto(big)).rejects.toThrow(/8 МБ/);
    expect(mocks.api).not.toHaveBeenCalled();
  });
});

describe("shifts", () => {
  it("читает неделю с днями и филиалом", async () => {
    await fetchShiftWeek("2026-11-09");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts?start=2026-11-09&days=7");
    await fetchShiftWeek("2026-11-09", { days: 14, departmentId: 3 });
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/shifts?start=2026-11-09&days=14&department_id=3",
    );
  });

  it("правит одну смену", async () => {
    const body = { status: "worked" as const, starts_at: "10:00", ends_at: "18:00" };
    await saveShift(4, "2026-11-09", body);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/4/2026-11-09", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    await moveShift(8, "2026-11-10");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/8/move", {
      method: "POST",
      body: JSON.stringify({ day: "2026-11-10" }),
    });
    await deleteShift(8);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/8", {
      method: "DELETE",
    });
  });

  it("массовые операции и копия недели", async () => {
    const bulk = { employee_ids: [1, 2], days: ["2026-11-09"], status: "planned" as const };
    await bulkSaveShifts(bulk);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/bulk", {
      method: "POST",
      body: JSON.stringify(bulk),
    });
    await copyShiftWeek({ from_start: "2026-11-02", to_start: "2026-11-09" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/copy-week", {
      method: "POST",
      body: JSON.stringify({ from_start: "2026-11-02", to_start: "2026-11-09" }),
    });
    await clearShiftCells({ employee_ids: [1], days: ["2026-11-09"] });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/clear", {
      method: "POST",
      body: JSON.stringify({ employee_ids: [1], days: ["2026-11-09"] }),
    });
  });

  it("шаблоны: список, создание, применение, удаление", async () => {
    await fetchShiftTemplates();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/templates");
    const tpl = {
      name: "5/2",
      days: [{ weekday: 0, status: "planned" as const }],
    };
    await saveShiftTemplate(tpl);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/templates", {
      method: "POST",
      body: JSON.stringify(tpl),
    });
    await applyShiftTemplate(2, { employee_ids: [1], week_start: "2026-11-09" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/templates/2/apply", {
      method: "POST",
      body: JSON.stringify({ employee_ids: [1], week_start: "2026-11-09" }),
    });
    await deleteShiftTemplate(2);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/shifts/templates/2", {
      method: "DELETE",
    });
  });
});

describe("orgs", () => {
  it("приглашения: список, создание, отзыв, превью, принятие", async () => {
    await fetchInvitations();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/invitations");
    const invite = { email: "a@b.ru", role: "staff" as const, days: 7 };
    await createInvitation(invite);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/invitations", {
      method: "POST",
      body: JSON.stringify(invite),
    });
    await revokeInvitation(3);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/invitations/3", {
      method: "DELETE",
    });
    await previewInvitation("tok en");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/invitations/tok%20en");
    await acceptInvitation("tok");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/invitations/tok/accept", {
      method: "POST",
    });
  });

  it("вход по коду и создание организации обрезают пробелы", async () => {
    await joinOrganization("  ZAL-1 ");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/join", {
      method: "POST",
      body: JSON.stringify({ code: "ZAL-1" }),
    });
    await createOrganization("  Кофейня ", "cafe");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/create", {
      method: "POST",
      body: JSON.stringify({ name: "Кофейня", industry: "cafe" }),
    });
  });

  it("читает организацию, участников, тариф", async () => {
    await fetchCurrentOrg();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/current");
    await fetchOrgMembers();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/members");
    await updateOrgMemberRole(5, "manager");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/members/5", {
      method: "PATCH",
      body: JSON.stringify({ role: "manager" }),
    });
    await fetchOrgPlan();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/plan");
  });

  it("счета: витрина, создание, «оплатил», отмена", async () => {
    await fetchOrgBilling();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/billing");
    await createInvoice({ plan: "team", period: "month" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/invoices", {
      method: "POST",
      body: JSON.stringify({ plan: "team", period: "month" }),
    });
    await requestInvoicePaid(4);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/invoices/4/paid", {
      method: "POST",
    });
    await cancelInvoice(4);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/invoices/4/cancel", {
      method: "POST",
    });
  });

  it("домен: чтение, сохранение, проверка, сброс", async () => {
    await fetchOrgDomain();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/domain");
    await saveOrgDomain("zal.example.com");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/domain", {
      method: "PUT",
      body: JSON.stringify({ domain: "zal.example.com" }),
    });
    await verifyOrgDomain();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/domain/verify", {
      method: "POST",
    });
    await clearOrgDomain();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/domain", {
      method: "DELETE",
    });
  });

  it("филиалы: список, создание, сотрудники, перевод", async () => {
    await fetchBranches();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/branches");
    await createBranch("Север");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/branches", {
      method: "POST",
      body: JSON.stringify({ name: "Север" }),
    });
    await fetchBranchEmployees();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/branches/employees");
    const transfer = { employee_id: 1, target_org_id: 2, move_shifts: true };
    await transferEmployee(transfer);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/branches/transfer", {
      method: "POST",
      body: JSON.stringify(transfer),
    });
  });
});

describe("quick", () => {
  it("читает людей, разбирает фразу и создаёт поручение", async () => {
    await fetchQuickPeople();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/hr/quick/people");
    await parseQuickText("помыть пол к вечеру");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/hr/quick/parse", {
      method: "POST",
      body: JSON.stringify({ text: "помыть пол к вечеру" }),
    });
    await createQuickTask({ text: "помыть пол", priority: "high" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/hr/quick/task", {
      method: "POST",
      body: JSON.stringify({ text: "помыть пол", priority: "high" }),
    });
  });

  it("переводит коды отказа в понятный текст", () => {
    expect(quickErrorText({ detail: "empty_title" })).toContain("Не расслышал");
    expect(quickErrorText({ detail: "неизвестно" })).toContain("Попробуй ещё раз");
    expect(quickErrorText(null)).toContain("Попробуй ещё раз");
  });
});

describe("privacy", () => {
  it("читает состояние, экспорт и журнал", async () => {
    await fetchPrivacy();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/privacy");
    await fetchOrgExport();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/export");
    await fetchAudit();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/audit?limit=20");
    await fetchAudit(5);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/audit?limit=5");
  });

  it("запрашивает и отменяет удаление организации", async () => {
    await requestOrgDeletion("zal");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org", {
      method: "DELETE",
      body: JSON.stringify({ confirm: "zal" }),
    });
    await cancelOrgDeletion();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org/restore", {
      method: "POST",
    });
  });

  it("сохраняет экспорт файлом и отпускает blob-ссылку", () => {
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    saveExportFile("zal", { ok: true });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test");
    click.mockRestore();
    vi.unstubAllGlobals();
  });
});

describe("imports", () => {
  it("превью и применение идут на /api/import/*", async () => {
    const body = { text: "имя;должность" };
    await previewImport(body);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/import/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    await applyImport(body);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/import/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  });

  it("пример CSV подходит под свой вид импорта", () => {
    expect(sampleCsv("people")).toContain("telegram_id");
    expect(sampleCsv("shifts")).toContain("статус");
  });
});

describe("platform", () => {
  it("читает доступ, сводку и организации с поиском", async () => {
    await fetchPlatformMe();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/platform/me");
    await fetchPlatformSummary();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/platform/summary");
    await fetchPlatformOrgs("зал 1");
    expect(mocks.api).toHaveBeenLastCalledWith(
      `/api/platform/orgs?q=${encodeURIComponent("зал 1")}`,
    );
  });

  it("правит организацию и счета", async () => {
    await patchPlatformOrg(3, { is_active: false });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/platform/orgs/3", {
      method: "PATCH",
      body: JSON.stringify({ is_active: false }),
    });
    await fetchPlatformInvoices();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/platform/invoices");
    await fetchPlatformInvoices("awaiting");
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/platform/invoices?status=awaiting",
    );
    await confirmPlatformInvoice(2);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/platform/invoices/2/confirm",
      { method: "POST" },
    );
    await cancelPlatformInvoice(2);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/platform/invoices/2/cancel",
      { method: "POST" },
    );
  });
});

describe("translate, simulation, training plan", () => {
  it("перевод уходит на /api/hr/translate", async () => {
    await translateTexts(["Помыть пол"], "en");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/hr/translate", {
      method: "POST",
      body: JSON.stringify({ target: "en", texts: ["Помыть пол"] }),
    });
  });

  it("сеанс проверки: старт, выход, активный", async () => {
    await startSimulation(4, "new");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/simulation", {
      method: "POST",
      body: JSON.stringify({ employee_id: 4, mode: "new" }),
    });
    await exitSimulation(9);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/simulation/9/exit", {
      method: "POST",
    });
    await fetchActiveSimulation();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/simulation/active");
  });

  it("план обучения: чтение, ставка, учебный день", async () => {
    await fetchTrainingPlan();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/training-plan?days=14");
    await patchTrainingPlan(4, { rate_type: "partial" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/training-plan/4", {
      method: "PATCH",
      body: JSON.stringify({ rate_type: "partial" }),
    });
    await setTrainingDay(4, "2026-11-09", true);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/training-plan/4/days/2026-11-09",
      { method: "PUT", body: JSON.stringify({ is_training: true }) },
    );
    await clearTrainingDay(4, "2026-11-09");
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/training-plan/4/days/2026-11-09",
      { method: "DELETE" },
    );
  });
});
