// @vitest-environment jsdom
/**
 * Экран «Данные и приватность» (шаг 5.5).
 *
 * Проверяем то, что ломается незаметно:
 *  - сроки берутся с сервера, а не из текста на экране;
 *  - скачивание действительно собирает файл;
 *  - удаление нельзя запросить без точного кода организации;
 *  - запланированное удаление можно отменить.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PrivacyScreen from "./PrivacyScreen";
import {
  cancelOrgDeletion,
  fetchAudit,
  fetchOrgExport,
  fetchPrivacy,
  requestOrgDeletion,
  rotateOrgLinks,
  saveExportFile,
  type PrivacyState,
} from "@/api/privacy";

vi.mock("@/api/privacy", () => ({
  fetchPrivacy: vi.fn(),
  fetchAudit: vi.fn(),
  fetchOrgExport: vi.fn(),
  requestOrgDeletion: vi.fn(),
  cancelOrgDeletion: vi.fn(),
  rotateOrgLinks: vi.fn(),
  saveExportFile: vi.fn(),
}));

const privacyMock = vi.mocked(fetchPrivacy);
const auditMock = vi.mocked(fetchAudit);
const exportMock = vi.mocked(fetchOrgExport);
const deleteMock = vi.mocked(requestOrgDeletion);
const cancelMock = vi.mocked(cancelOrgDeletion);
const rotateMock = vi.mocked(rotateOrgLinks);
const saveMock = vi.mocked(saveExportFile);

const STATE: PrivacyState = {
  slug: "salon-a",
  retention: {
    audit_days: 180,
    deletion_grace_days: 30,
    fired_trash_days: 30,
    backup_artifact_days: 14,
  },
  deletion: {
    deleted: false,
    deleted_at: null,
    purge_after: null,
    days_left: null,
  },
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PrivacyScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  privacyMock.mockReset();
  auditMock.mockReset();
  exportMock.mockReset();
  deleteMock.mockReset();
  cancelMock.mockReset();
  rotateMock.mockReset();
  saveMock.mockReset();
  privacyMock.mockResolvedValue(STATE);
  auditMock.mockResolvedValue([]);
  exportMock.mockResolvedValue({ organization: { slug: "salon-a" } });
  deleteMock.mockResolvedValue({ ...STATE.deletion, deleted: true, days_left: 30 });
  cancelMock.mockResolvedValue(STATE.deletion);
  rotateMock.mockResolvedValue({
    rotated_at: "2026-11-11T12:00:00+00:00",
    previous_valid_until: "2026-12-11T12:00:00+00:00",
  });
});

describe("PrivacyScreen", () => {
  it("показывает сроки хранения с сервера", async () => {
    renderScreen();

    expect(await screen.findByText("Сроки хранения")).toBeTruthy();
    expect(screen.getByText("Журнал доступа")).toBeTruthy();
    expect(screen.getByText("180 дней")).toBeTruthy();
    expect(screen.getByText("14 дней")).toBeTruthy();
  });

  it("скачивает копию данных и сохраняет файл", async () => {
    renderScreen();

    fireEvent.click(await screen.findByText("Скачать копию данных"));

    await vi.waitFor(() => expect(exportMock).toHaveBeenCalled());
    expect(saveMock).toHaveBeenCalledWith("salon-a", {
      organization: { slug: "salon-a" },
    });
  });

  it("не даёт запросить удаление без точного кода организации", async () => {
    renderScreen();

    const button = (await screen.findByText("Запросить удаление")) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    const input = screen.getByLabelText("Код организации") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "salon" } });
    expect(button.disabled).toBe(true);

    fireEvent.change(input, { target: { value: "salon-a" } });
    expect(button.disabled).toBe(false);

    fireEvent.click(button);
    await vi.waitFor(() => expect(deleteMock).toHaveBeenCalledWith("salon-a"));
  });

  it("отзывает ссылки организации только после подтверждения", async () => {
    renderScreen();

    fireEvent.click(await screen.findByText("Отозвать ссылки"));
    expect(rotateMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Да, отозвать"));
    await vi.waitFor(() => expect(rotateMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Старые работают до/)).toBeTruthy();
  });

  it("отменяет запланированное удаление", async () => {
    privacyMock.mockResolvedValue({
      ...STATE,
      deletion: {
        deleted: true,
        deleted_at: "2026-11-04T09:00:00+00:00",
        purge_after: "2026-12-04T09:00:00+00:00",
        days_left: 30,
      },
    });
    renderScreen();

    expect(
      await screen.findByText("Удаление запланировано: данные исчезнут через 30 дн."),
    ).toBeTruthy();
    fireEvent.click(screen.getByText("Отменить удаление"));

    await vi.waitFor(() => expect(cancelMock).toHaveBeenCalled());
  });
});
