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
    // UI_UX_PRO_MAX §7 `breakpoint-consistency`: одна шкала на всё приложение.
    // `xs` — узкий телефон (375), `sm` — планшет в портрете, где 560-й контейнер
    // уже получает поля, `md` — планшет, `lg` — десктоп. `xl`/`2xl` убраны:
    // приложение живёт в 560 px, и «две колонки только с 1280» означало, что на
    // ноутбуке 1024 они так и не включались. Тест `styles.breakpoints.test.ts`
    // держит шкалу и запрещает произвольные `min-[...]px:`.
    screens: {
      xs: "375px",
      sm: "640px",
      md: "768px",
      lg: "1024px",
    },
    extend: {
      // DESIGN_SYSTEM §2: no 9px, no 1px-stepped sizes. `3xs`/`2xs` are the
      // small end of the scale (avatar initials, captions, ledger labels).
      fontSize: {
        "3xs": ["10px", { lineHeight: "1.2" }],
        "2xs": ["11px", { lineHeight: "1.25" }],
        // Роли, а не «размер плюс вес по месту». Заголовок экрана и заголовок
        // секции — разные роли с одинаковым набором свойств на всех экранах;
        // `text-title`/`text-heading` держат размер, интерлиньяж и вес вместе.
        display: ["24px", { lineHeight: "1.1", fontWeight: "600" }],
        "title-lg": ["20px", { lineHeight: "1.15", fontWeight: "600" }],
        title: ["18px", { lineHeight: "1.15", fontWeight: "600" }],
        heading: ["14px", { lineHeight: "1.25", fontWeight: "600" }],
      },
      // VISUAL_AUDIT P1.6: два радиуса вместо «по настроению». Карточка — 12px
      // (`rounded-card`), всё внутри неё — 8px (`rounded-tile`): плитки, поля,
      // кнопки, бейджи. Пиллюли остаются `rounded-full`. Старые `md/lg/xl/2xl`
      // запрещены тестом `styles.radius.test.ts`: до прохода `rounded-md` (6px)
      // и `rounded-lg` (8px) обозначали одну и ту же роль, а `rounded-2xl`
      // выпадал из шкалы вовсе.
      borderRadius: {
        card: "12px",
        tile: "8px",
      },
      // UI_UX_PRO_MAX §4 `elevation-consistent`: три роли тени вместо четырёх
      // ступеней Tailwind по месту. `raised` — элемент приподнят над потоком
      // (пилюли, кнопки), `floating` — плавающий над контентом (тост,
      // «Наверх», skip-link), `sheet` — поверхность поверх страницы (шиты,
      // попапы). Старые `shadow-sm/md/lg/xl/2xl` запрещены тестом
      // `styles.elevation.test.ts`: до прохода одна и та же роль встречалась
      // на трёх соседних ступенях, и глубина читалась как случайная.
      boxShadow: {
        raised: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        floating:
          "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
        sheet:
          "0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
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
      // UI_UX_PRO_MAX §7 `duration-timing` / `motion-consistency`: три роли
      // движения вместо чисел по месту. `press` — отклик на касание, `fade` —
      // смена состояния (шеврон, подсказка), `exit` — уход быстрее появления:
      // человек уже принял решение, и ждать анимацию ему незачем.
      transitionDuration: {
        press: "120ms",
        fade: "150ms",
        exit: "100ms",
      },
      // UI_UX_PRO_MAX §9 `z-index-management`: слои — это шкала, а не числа
      // «по месту». `sheet` — фон/экран поверх вкладок, `overlay` — панель или
      // тост над ним, `lightbox` — просмотр фото поверх всего. Локальные
      // `z-10`/`z-20` остаются для sticky-строк внутри своей прокрутки: это не
      // слои приложения, а порядок внутри одного контейнера.
      zIndex: {
        sheet: "40",
        overlay: "50",
        lightbox: "100",
      },
      colors: {
        // Telegram theme variables, mapped to Tailwind tokens (alpha-capable).
        "tg-bg": themeColor("bg-color", "#ffffff"),
        "tg-secondary-bg": themeColor("secondary-bg-color", "#f1f1f1"),
        "tg-text": themeColor("text-color", "#000000"),
        "tg-hint": themeColor("hint-color", "#999999"),
        "tg-link": themeColor("link-color", "#1c6fb8"),
        "tg-button": themeColor("button-color", "#1c6fb8"),
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
