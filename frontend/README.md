# Frontend (Telegram Mini App)

React 18 + TypeScript + Vite. Использует Telegram WebApp SDK через
`@twa-dev/sdk` и шлёт `Authorization: tma <initData>` на бэкенд.

## Локально

```bash
cd frontend
npm install
cp .env.example .env             # VITE_API_BASE = адрес бэка
npm run dev
```

В обычном браузере `WebApp.initData` пуст → бэкенд вернёт 401.
Для разработки либо открывай Mini App в TG (через тестового бота с `/setdomain`),
либо на бэке временно отключай auth dependency.

## Сборка и деплой на Cloudflare Pages

```bash
npm run build
# подключи репо на pages.cloudflare.com → build command: `npm run build`,
# output: `frontend/dist`. Прокинь VITE_API_BASE в Pages env vars.
```

## Структура

- `src/tg/webapp.ts` — инициализация TG SDK, haptics, initData геттер
- `src/api/client.ts` — fetch-обёртка с авторизацией
- `src/features/calendar/` — основной grid, ParticipantRow, dateUtils
- `src/features/editor/` — bottom-sheet редактор статус/уверенность
- `src/store/ui.ts` — Zustand UI state (zoom, центр, открытый редактор)
