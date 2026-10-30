// @vitest-environment jsdom
/**
 * PWA (B2B_PLATFORM_PLAN, шаг 2.3): установка на домашний экран и офлайн-старт.
 *
 * Проверяем то, что легко потерять при правках `index.html` или сборки:
 *  • манифест подключён и содержит обязательные поля;
 *  • есть иконки 192/512 и отдельная maskable (Android обрезает «any» в круг);
 *  • service worker не кеширует `/api/*` — устаревшие данные смены опаснее
 *    честной ошибки;
 *  • стартовый адрес и scope — корень, иначе установленное приложение
 *    открывается на пустой странице.
 *
 * Файлы читаются через `?raw` (как страж эмодзи): так тест не тянет `node:fs`
 * и работает в той же сборке Vite, что и приложение.
 */
import { describe, expect, it } from "vitest";
import manifestRaw from "../public/manifest.webmanifest?raw";
import swRaw from "../public/sw.js?raw";
import indexHtml from "../index.html?raw";
import tabBarSource from "./features/nav/TabBar.tsx?raw";
import sheetSource from "./features/actions/BottomSheet.tsx?raw";
import lightboxSource from "./components/MediaLightbox.tsx?raw";
import appSource from "./App.tsx?raw";
import {
  SAFE_AREA_BOTTOM,
  SAFE_AREA_ROOT,
  SAFE_AREA_TOP_OFFSET,
} from "./tg/safeArea";

const manifest = JSON.parse(manifestRaw) as {
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  display: string;
  theme_color: string;
  background_color: string;
  icons: { src: string; sizes: string; purpose?: string }[];
};

describe("manifest", () => {
  it("ставится отдельным окном с корня", () => {
    expect(manifest.name).toContain("SemiTask");
    expect(manifest.short_name.length).toBeLessThanOrEqual(12);
    expect(manifest.start_url).toBe("/");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
  });

  it("цвета совпадают с темой приложения", () => {
    expect(manifest.theme_color).toBe("#1c6fb8");
    expect(manifest.background_color).toBe("#ffffff");
  });

  it("есть иконки 192, 512 и maskable", () => {
    const sizes = manifest.icons.map((icon) => icon.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
    expect(
      manifest.icons.some((icon) => icon.purpose === "maskable"),
    ).toBe(true);
    for (const icon of manifest.icons) {
      expect(icon.src.startsWith("/")).toBe(true);
    }
  });
});

describe("index.html", () => {
  it("подключает манифест и иконки для установки", () => {
    expect(indexHtml).toContain('rel="manifest"');
    expect(indexHtml).toContain("/manifest.webmanifest");
    expect(indexHtml).toContain('rel="apple-touch-icon"');
    expect(indexHtml).toContain("apple-mobile-web-app-capable");
    expect(indexHtml).toContain('name="theme-color"');
  });
});

/**
 * M1 плана [`MOBILE_PARALLEL.md`](../docs/MOBILE_PARALLEL.md): установленное
 * приложение (PWA, а позже нативная обёртка) не должно прятать интерфейс под
 * системные вырезы и не должно ждать чужой домен ради первого кадра.
 *
 * Это ровно те правила, которые легко потерять незаметно: `env()` выглядит
 * как случайный шум в классе, а `defer` в теге — как мелочь, и оба удаляются
 * при «чистке» вёрстки без единого падения тестов.
 *
 * Проверяем значения и применение, а не CSS-файл: vitest подменяет импорт
 * стилей пустой строкой, поэтому отступы вынесены в `tg/safeArea.ts`, где
 * страж их действительно видит.
 */
describe("мобильная оболочка (M1)", () => {
  it("константы безопасных зон заданы для всех четырёх сторон", () => {
    expect(SAFE_AREA_ROOT.paddingTop).toContain("env(safe-area-inset-top");
    expect(SAFE_AREA_ROOT.paddingLeft).toContain("env(safe-area-inset-left");
    expect(SAFE_AREA_ROOT.paddingRight).toContain("env(safe-area-inset-right");
    expect(SAFE_AREA_BOTTOM).toContain("env(safe-area-inset-bottom");
    // Фолбэк обязателен: без него старый браузер выкинул бы padding целиком.
    for (const value of [
      SAFE_AREA_ROOT.paddingTop,
      SAFE_AREA_BOTTOM,
      SAFE_AREA_TOP_OFFSET,
    ]) {
      expect(value).toContain("0px");
    }
  });

  it("зоны применены на корне, в шторке и в просмотре фото", () => {
    // Корень приложения: мобильный и широкий контейнеры.
    expect(appSource).toContain("SAFE_AREA_ROOT");
    expect(appSource).toContain("style={SAFE_AREA_ROOT}");
    // Низ — у поверхностей, которые доходят до края экрана.
    expect(tabBarSource).toContain("env(safe-area-inset-bottom");
    expect(sheetSource).toContain("SAFE_AREA_BOTTOM");
    // Верх полноэкранного просмотра фото — иначе кнопка под чёлкой.
    expect(lightboxSource).toContain("SAFE_AREA_TOP_OFFSET");
  });

  it("SDK Telegram не блокирует первый кадр", () => {
    // Вне Telegram этот скрипт не нужен, а в России его доступность не
    // гарантирована: блокирующий тег означал бы белый экран вместо входа.
    expect(indexHtml).toMatch(
      /<script\s+defer\s+src="https:\/\/telegram\.org\/js\/telegram-web-app\.js"/,
    );
    expect(/<script\s+src="https:\/\/telegram\.org/.test(indexHtml)).toBe(false);
  });
});

describe("service worker", () => {
  it("не кеширует данные смены", () => {
    expect(swRaw).toContain('"/api/"');
    expect(swRaw).toContain("request.method !== \"GET\"");
  });

  it("отдаёт оболочку при отсутствии сети", () => {
    expect(swRaw).toContain("networkFirst");
    expect(swRaw).toContain("/index.html");
    expect(swRaw).toContain("activate");
  });

  it("кладёт сборку в кеш при установке, а не после второго визита", () => {
    // Иначе офлайн-старт после первого визита показал бы HTML без скриптов.
    expect(swRaw).toContain("precacheBuild");
    expect(swRaw).toContain('startsWith("/assets/")');
  });

  it("показывает push и открывает приложение по клику", () => {
    // Без обработчика push подписка `userVisibleOnly` не работает: Chrome
    // отзывает её, если сообщение не превратилось в уведомление.
    expect(swRaw).toContain('addEventListener("push"');
    expect(swRaw).toContain("showNotification");
    expect(swRaw).toContain('addEventListener("notificationclick"');
    expect(swRaw).toContain("openWindow");
  });

  it("читает оболочку из того кеша, куда её положила установка", () => {
    // Кеши разные: промах по ASSET_CACHE для манифеста/иконок ломает офлайн.
    expect(swRaw).toContain("cacheFirst(request, SHELL_CACHE)");
    expect(swRaw).toContain("cacheFirst(request, ASSET_CACHE)");
  });
});
