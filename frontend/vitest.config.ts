import { defineConfig } from "vitest/config";
import path from "node:path";

// Отдельный конфиг для тестов: путь `@` — как в vite.config, окружение node
// (в логике конвертации нет DOM), тесты рядом с исходниками.
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    // По умолчанию node (чистая логика); компонентные тесты переключают
    // окружение на jsdom через docblock `@vitest-environment jsdom`.
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    // Покрытие считаем по продукту, а не по тестам и не по точке входа:
    // `main.tsx` — три строки склейки, и он бы раздувал процент.
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "json-summary"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/**/*.d.ts", "src/main.tsx"],
      /**
       * Пороги — это защита от регрессии, а не цель.
       *
       * Цель плана (60 % features / 80 % api) пока не достигнута: факт на
       * 08.11.2026 — 58,8 % и 39,3 % строк. Пороги стоят чуть ниже факта,
       * чтобы CI краснел на падении, а не на всём сразу; поднимать их нужно
       * вместе с тестами, а не заранее.
       */
      thresholds: {
        lines: 60,
        "src/features/**": { lines: 55 },
        "src/api/**": { lines: 35 },
      },
    },
  },
});
