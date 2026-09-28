import type { Config } from "tailwindcss";

/**
 * DESIGN_SYSTEM §1.4: Telegram hands each theme as a plain hex, so the usual
 * `rgb(var(--x) / <alpha-value>)` recipe is unavailable. A bare `var(--x)`
 * string, however, makes Tailwind drop the `/NN` modifier entirely — the class
 * is never generated, so `bg-tg-secondary-bg/60` used to render *transparent*
 * and `border-tg-hint/10` fell back to Preflight's grey-200 (wrong in dark).
 * Emitting `color-mix()` instead makes the alpha steps real for any color
 * format. Older engines that lack color-mix simply ignore the declaration and
 * behave exactly as before, so this is a strict improvement.
 */
const themeColor =
  (name: string, fallback: string) =>
  ({ opacityValue }: { opacityValue?: string }) =>
    opacityValue === undefined || opacityValue === "1"
      ? `var(--tg-theme-${name}, ${fallback})`
      : `color-mix(in srgb, var(--tg-theme-${name}, ${fallback}) calc(${opacityValue} * 100%), transparent)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // DESIGN_SYSTEM §2: no 9px, no 1px-stepped sizes. `3xs`/`2xs` are the
      // small end of the scale (avatar initials, captions, ledger labels).
      fontSize: {
        "3xs": ["10px", { lineHeight: "1.2" }],
        "2xs": ["11px", { lineHeight: "1.25" }],
      },
      // DESIGN_SYSTEM §2: the "ledger" face. System mono only — the app ships
      // no webfonts (external CDNs are unreliable for this audience).
      fontFamily: {
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          '"SF Mono"',
          "Menlo",
          "Consolas",
          '"Liberation Mono"',
          "monospace",
        ],
      },
      colors: {
        // Telegram theme variables, mapped to Tailwind tokens (alpha-capable).
        "tg-bg": themeColor("bg-color", "#ffffff"),
        "tg-secondary-bg": themeColor("secondary-bg-color", "#f1f1f1"),
        "tg-text": themeColor("text-color", "#000000"),
        "tg-hint": themeColor("hint-color", "#999999"),
        "tg-link": themeColor("link-color", "#2481cc"),
        "tg-button": themeColor("button-color", "#2481cc"),
        "tg-button-text": themeColor("button-text-color", "#ffffff"),
        // DESIGN_SYSTEM §2: the one sanctioned "quieter text" token. Telegram's
        // own hint color fails AA on light surfaces (2.5:1), so secondary text
        // that still has to be *read* uses this instead: 62% of the theme's text
        // color -> ~5.9:1 on light, ~7.3:1 on dark. Never used with `/NN`.
        muted:
          "color-mix(in srgb, var(--tg-theme-text-color, #000000) 62%, transparent)",
        // Status colors for availability pills.
        "status-free": "#22c55e",
        "status-maybe": "#f59e0b",
        "status-busy": "#ef4444",
        // DESIGN_SYSTEM §1.3: our own "stamp inks" — the only non-theme colors
        // the UI introduces. `ink-stamp` marks the shame titles and the record
        // holder; `ink-moss` marks the cursed "червь".
        "ink-stamp": "#9b2c1f",
        "ink-moss": "#4e6b33",
      },
    },
  },
  plugins: [],
} satisfies Config;
