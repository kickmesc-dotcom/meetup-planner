/**
 * Адреса и тела запросов: админские операции, игровые ручки и кабинет.
 *
 * Проверяем контракт с сервером — метод, путь, тело. Такие ошибки не видит
 * `tsc`: неверный сегмент пути собирается и отвечает 404 только в проде.
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
  };
});
vi.mock("@/tg/webapp", () => ({ getInitData: () => "" }));

import {
  addEmployeeByTelegramId,
  cancelNotification,
  createRosterSnapshot,
  deleteRosterSnapshot,
  fetchEmployeesPool,
  fetchJournal,
  fetchNotificationsCenter,
  fetchRosterSnapshots,
  findEmployeeByTelegramId,
  fireEmployee,
  forceTaskDone,
  muteAllNotifications,
  patchEmployee,
  postponePendingNotification,
  resetEmployeeProgress,
  resetPendingNotification,
  restoreEmployee,
  restoreRosterSnapshot,
  sendNotification,
  skipPendingNotification,
} from "./hrOps";
import {
  ackLevelUp,
  addNomination,
  answerActivity,
  askAdvice,
  deleteFeedItem,
  fetchAchievementStats,
  fetchActivities,
  fetchFeed,
  fetchGuestProfile,
  fetchMyGame,
  fetchNominations,
  fetchRanksChart,
  fetchVoiceCurrent,
  fetchWorm,
  hideFeedItem,
  likeVoiceSubmission,
  markFeedItemSeen,
  restoreFeedItem,
  runPhrase,
  transferWorm,
  unhideFeedItem,
  updateGameProfile,
  voteNomination,
  withdrawVoice,
} from "./game";
import {
  fetchDepartmentOverview,
  fetchDepartments,
  fetchDigest,
  fetchEmployee,
  fetchEmployeeCard,
  fetchNotifyPrefs,
  fetchOrgSetup,
  fetchOrgSetupProgress,
  setMyName,
  setNotifyPref,
  setProfilePrivacy,
  setProfileVisibility,
} from "./hr";

beforeEach(() => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValue(undefined);
});

describe("hrOps: журнал и уведомления", () => {
  it("читает журнал с лимитом", async () => {
    await fetchJournal();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/journal?limit=100");
    await fetchJournal(10);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/journal?limit=10");
  });

  it("читает центр уведомлений и управляет напоминаниями", async () => {
    await fetchNotificationsCenter();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/notifications");
    await cancelNotification(3);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/notifications/3/cancel",
      { method: "POST" },
    );
    await sendNotification(4, "Проверь кассу");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/notifications/send", {
      method: "POST",
      body: JSON.stringify({ employee_id: 4, text: "Проверь кассу" }),
    });
    await postponePendingNotification(9, 30);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/notifications/pending/9/postpone",
      { method: "POST", body: JSON.stringify({ minutes: 30 }) },
    );
    await skipPendingNotification(9);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/notifications/pending/9/skip",
      { method: "POST" },
    );
    await resetPendingNotification(9);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/notifications/pending/9/reset",
      { method: "POST" },
    );
    await muteAllNotifications(2);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/notifications/mute", {
      method: "POST",
      body: JSON.stringify({ hours: 2 }),
    });
  });
});

describe("hrOps: пул сотрудников", () => {
  it("читает пул и правит карточку", async () => {
    await fetchEmployeesPool();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/employees-pool");
    await patchEmployee(3, { display_name: "Иван", role: "aup" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/employees/3", {
      method: "PATCH",
      body: JSON.stringify({ display_name: "Иван", role: "aup" }),
    });
  });

  it("ищет по Telegram-ID и заводит человека", async () => {
    await findEmployeeByTelegramId(123456);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/employees-pool/find?telegram_id=123456",
    );
    await addEmployeeByTelegramId({ telegram_id: 123456, display_name: "Анна" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/employees-pool/add", {
      method: "POST",
      body: JSON.stringify({ telegram_id: 123456, display_name: "Анна" }),
    });
  });

  it("сбрасывает прогресс, увольняет и возвращает", async () => {
    await resetEmployeeProgress(3);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/employees/3/reset-progress",
      { method: "POST" },
    );
    await fireEmployee(3, "trash");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/employees/3/fire", {
      method: "POST",
      body: JSON.stringify({ mode: "trash" }),
    });
    await restoreEmployee(3);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/employees/3/restore", {
      method: "POST",
    });
  });
});

describe("hrOps: снапшоты и принудительное закрытие", () => {
  it("снимает, восстанавливает и удаляет снимок состава", async () => {
    await fetchRosterSnapshots();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/roster-snapshots");
    await createRosterSnapshot("перед увольнением");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/roster-snapshots", {
      method: "POST",
      body: JSON.stringify({ label: "перед увольнением" }),
    });
    await restoreRosterSnapshot(2);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/admin/roster-snapshots/2/restore",
      { method: "POST" },
    );
    await deleteRosterSnapshot(2);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/roster-snapshots/2", {
      method: "DELETE",
    });
  });

  it("зачитывает поручение за человека", async () => {
    await forceTaskDone(7, 3, "сделано вживую");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/admin/tasks/7/force-done", {
      method: "POST",
      body: JSON.stringify({ employee_id: 3, comment: "сделано вживую" }),
    });
  });
});

describe("game: профиль и лента", () => {
  it("читает и правит профиль", async () => {
    await fetchMyGame();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/me/game");
    await updateGameProfile({ custom_name: "Червь" });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/me/game/profile", {
      method: "PATCH",
      body: JSON.stringify({ custom_name: "Червь" }),
    });
    await ackLevelUp();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/me/game/level-up/ack", {
      method: "POST",
    });
  });

  it("читает ачивки, рейтинг и чужой профиль", async () => {
    await fetchAchievementStats();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/achievements");
    await fetchRanksChart();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/ranks");
    await fetchGuestProfile(12);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/players/12");
  });

  it("собирает параметры ленты и не шлёт пустой фильтр типов", async () => {
    await fetchFeed();
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/game/feed?scope=all&limit=30&offset=0",
    );
    await fetchFeed({ scope: "mine", limit: 5, offset: 10, kinds: "voice,music" });
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/game/feed?scope=mine&limit=5&offset=10&kinds=voice%2Cmusic",
    );
  });

  it("модерирует записи ленты", async () => {
    await deleteFeedItem("achievement:1");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/feed/delete", {
      method: "POST",
      body: JSON.stringify({ item_id: "achievement:1" }),
    });
    await restoreFeedItem("achievement:1");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/feed/restore", {
      method: "POST",
      body: JSON.stringify({ item_id: "achievement:1" }),
    });
    await hideFeedItem("achievement:1");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/feed/hide", {
      method: "POST",
      body: JSON.stringify({ item_id: "achievement:1" }),
    });
    await unhideFeedItem("achievement:1");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/feed/unhide", {
      method: "POST",
      body: JSON.stringify({ item_id: "achievement:1" }),
    });
    await markFeedItemSeen("achievement:1");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/feed/seen", {
      method: "POST",
      body: JSON.stringify({ item_id: "achievement:1" }),
    });
  });
});

describe("game: активности и звания", () => {
  it("читает активности и отвечает на вопрос", async () => {
    await fetchActivities();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/activities");
    await answerActivity(5, "да");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/activities/5/answer", {
      method: "POST",
      body: JSON.stringify({ text: "да" }),
    });
  });

  it("лайкает голосовое и читает задание", async () => {
    await likeVoiceSubmission(8);
    expect(mocks.api).toHaveBeenLastCalledWith(
      "/api/game/voice/submissions/8/like",
      { method: "POST" },
    );
    await fetchVoiceCurrent();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/voice/current");
    await withdrawVoice();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/voice/submission", {
      method: "DELETE",
    });
  });

  it("магический шар обрезает вопрос и умеет молчать", async () => {
    await askAdvice("  что делать?  ");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/advice", {
      method: "POST",
      body: JSON.stringify({ question: "что делать?", target: "feed" }),
    });
    await askAdvice();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/advice", {
      method: "POST",
      body: JSON.stringify({ question: null, target: "feed" }),
    });
    await runPhrase();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/phrases", {
      method: "POST",
    });
  });

  it("номинации и червь-господин", async () => {
    await fetchNominations();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/nominations");
    await addNomination("Дартс");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/nominations", {
      method: "POST",
      body: JSON.stringify({ name: "Дартс" }),
    });
    await voteNomination(2);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/nominations/2/vote", {
      method: "POST",
    });
    await fetchWorm();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/worm");
    await transferWorm(4);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/game/worm/transfer", {
      method: "POST",
      body: JSON.stringify({ user_id: 4 }),
    });
  });
});

describe("hr: кабинет и сводка", () => {
  it("читает сотрудника, сводку и подписки", async () => {
    await fetchEmployee();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/me/employee");
    await fetchDigest();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/digest");
    await fetchNotifyPrefs();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/notify-prefs");
    await setNotifyPref("deadline", false);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/notify-prefs", {
      method: "PATCH",
      body: JSON.stringify({ kind: "deadline", enabled: false }),
    });
  });

  it("правит видимость профиля и имя", async () => {
    await setProfileVisibility(true);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/me/profile-visibility", {
      method: "POST",
      body: JSON.stringify({ is_public: true }),
    });
    await setMyName("Иван");
    expect(mocks.api).toHaveBeenLastCalledWith("/api/me/name", {
      method: "PATCH",
      body: JSON.stringify({ display_name: "Иван" }),
    });
    await setProfilePrivacy({ show_last_seen: false });
    expect(mocks.api).toHaveBeenLastCalledWith("/api/me/privacy", {
      method: "POST",
      body: JSON.stringify({ show_last_seen: false }),
    });
  });

  it("читает карточку, отделы и настройку организации", async () => {
    await fetchEmployeeCard(12);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/employees/12/card");
    await fetchDepartments();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/departments");
    await fetchDepartmentOverview(2);
    expect(mocks.api).toHaveBeenLastCalledWith("/api/departments/2/overview");
    await fetchOrgSetup();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org-setup");
    await fetchOrgSetupProgress();
    expect(mocks.api).toHaveBeenLastCalledWith("/api/org-setup/progress");
  });
});
