import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Telegram theme variables, mapped to Tailwind tokens.
        "tg-bg": "var(--tg-theme-bg-color, #ffffff)",
        "tg-secondary-bg": "var(--tg-theme-secondary-bg-color, #f1f1f1)",
        "tg-text": "var(--tg-theme-text-color, #000000)",
        "tg-hint": "var(--tg-theme-hint-color, #999999)",
        "tg-link": "var(--tg-theme-link-color, #2481cc)",
        "tg-button": "var(--tg-theme-button-color, #2481cc)",
        "tg-button-text": "var(--tg-theme-button-text-color, #ffffff)",
        // Status colors for availability pills.
        "status-free": "#22c55e",
        "status-maybe": "#f59e0b",
        "status-busy": "#ef4444",
      },
    },
  },
  plugins: [],
} satisfies Config;
