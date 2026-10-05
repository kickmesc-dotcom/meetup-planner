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
  },
});
