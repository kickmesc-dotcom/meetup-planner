import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./styles.css";
import { initTelegramWebApp, syncWebAppChrome } from "./tg/webapp";
import { initTheme } from "./store/theme";
import { captureAccessTokenFromUrl } from "./api/client";

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

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
