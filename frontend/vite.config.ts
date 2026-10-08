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
    sourcemap: true,
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
     * `VITE_DEV_API_PROXY` (например, если проверяем HF Space).
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
