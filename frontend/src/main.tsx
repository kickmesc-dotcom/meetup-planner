import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./styles.css";
import { initTelegramWebApp, syncWebAppChrome } from "./tg/webapp";
import { initTheme } from "./store/theme";
import { captureAccessTokenFromUrl } from "./api/client";
import ResetPasswordScreen from "./features/auth/ResetPasswordScreen";
import { clearResetTokenFromUrl, resetTokenFromUrl } from "./features/auth/resetUrl";

// Прямая ссылка из `/app`: забираем токен в localStorage и чистим адресную
// строку ДО первых запросов — иначе первый же `GET /api/me` ушёл бы без него.
captureAccessTokenFromUrl();
initTelegramWebApp();
// GHG11(11): тему наносим до первого рендера — иначе видно вспышку чужой темы.
syncWebAppChrome(initTheme());

const qc = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
});

/**
 * Развилка до приложения.
 *
 * Ссылка из письма (`/reset?token=…`) открывает свой экран и не поднимает
 * `App`: сессии у человека в этот момент может не быть вовсе, и `GET /api/me`
 * только зря сходил бы в 401. После смены пароля адрес чистится — ссылка
 * одноразовая, оставаться в истории браузера ей незачем.
 */
function Root() {
  const [resetToken, setResetToken] = useState(() => resetTokenFromUrl());

  if (resetToken) {
    return (
      <ResetPasswordScreen
        token={resetToken}
        onDone={() => {
          clearResetTokenFromUrl();
          setResetToken(null);
        }}
      />
    );
  }

  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <Root />
    </QueryClientProvider>
  </React.StrictMode>,
);

/**
 * PWA (B2B_PLATFORM_PLAN, шаг 2.3): оболочка для установки и офлайн-старта.
 *
 * Только в сборке: в dev service worker кешировал бы модули Vite и правки
 * перестали бы доезжать до браузера. Ошибка регистрации ничего не ломает —
 * приложение просто работает как обычный сайт, поэтому `catch` молчит.
 */
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}
