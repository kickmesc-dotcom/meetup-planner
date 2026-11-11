import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    target: "es2022",
    /**
     * Карты исходников в прод не уезжают: Pages раздаёт `dist` целиком, и
     * `sourcemap: true` выкладывал рядом с бандлом 32 `.map` (одна карта
     * `AdminScreen` — 941 КБ) вместе с исходниками. Отладку ведём в `vite dev`,
     * где карты строит сам Vite; если понадобятся карты для разбора
     * прод-ошибок — собирать их отдельным артефактом CI, а не в `dist`.
     */
    sourcemap: false,
    /**
     * Разделение вендоров (этап 4, DoD «главный чанк ≤ 300 КБ raw»).
     *
     * Зачем. Главный чанк был 500 КБ, и в нём лежал не наш код, а библиотеки:
     * React, `framer-motion`, иконки, даты и `@twa-dev/sdk`. Браузер грузит
     * такие чанки параллельно, поэтому смысл не в «переложить байты», а в том,
     * чтобы наш код не ждал и не пересобирал весь вендорный вес при каждой
     * правке экрана. Порядок проверок важен: `date-fns-tz` тоже содержит
     * подстроку `date-fns` и обязан попасть в один чанк с ним, иначе Rollup
     * предупредит о двух копиях.
     */
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("date-fns")) return "vendor-dates";
          if (id.includes("framer-motion")) return "vendor-motion";
          if (id.includes("iconoir")) return "vendor-icons";
          if (id.includes("@tanstack")) return "vendor-query";
          if (id.includes("@twa-dev")) return "vendor-twa";
          return "vendor";
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    /**
     * GHG11(11): локальная разработка без CORS и без VITE_API_BASE.
     *
     * Бэкенд отдаёт `Access-Control-Allow-Origin` только для боевого происхождения
     * мини-аппа, поэтому запрос со `localhost` падал на preflight'е. Проксируем
     * `/api` на живой Amvera: браузер видит СВОЙ origin (preflight не нужен), а
     * сервер-сервер CORS не проверяет. Адрес можно переопределить переменной
     * `VITE_DEV_API_PROXY` (например, если проверяем другой хост).
     *
     * На сборку это никак не влияет — секция читается только `vite dev`.
     */
    proxy: {
      "/api": {
        target:
          process.env.VITE_DEV_API_PROXY ??
          "https://meetup-planner-youmakemefry.waw0.amvera.tech",
        changeOrigin: true,
        secure: true,
      },
    },
  },
});
