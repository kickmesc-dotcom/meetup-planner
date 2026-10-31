# DESIGN SYSTEM

Single source of truth for the "Планер шестёрки" frontend (Telegram Mini App).
Derived from `tailwind.config.ts`, `src/styles.css` and the component source during the
2026-09-28 design audit. Every UI value must reference a token from this document — no
ad-hoc hexes, opacities or one-off sizes.

Stack: React 18 + Vite + Tailwind 3.4. No component library, no CSS-in-JS, no
`tailwindcss-animate` (do not use `animate-in`/`fade-in` — they resolve to nothing).

---

## 1. Color

### 1.1 Theme surface colors (Telegram-provided)

Defined in `tailwind.config.ts` as `tg-*`. These flip automatically with the user's
Telegram theme; never hardcode their equivalents.

| Token | CSS variable | Use |
|---|---|---|
| `bg-tg-bg` / `text-tg-text` | `--tg-theme-bg-color` / `--tg-theme-text-color` | page surface + body text |
| `bg-tg-secondary-bg` | `--tg-theme-secondary-bg-color` | cards, inputs, chips |
| `text-tg-hint` | `--tg-theme-hint-color` | secondary text, labels, placeholders |
| `text-tg-link` / `bg-tg-link` | `--tg-theme-link-color` | links, accents, selection |
| `bg-tg-button` / `text-tg-button-text` | `--tg-theme-button-color` / `--tg-theme-button-text-color` | primary actions |

**Rule:** on a *theme-colored* surface (`bg-tg-button`, `bg-tg-link`) the foreground is
`text-tg-button-text`. On the *fixed* `*-pill` status hexes (§1.2) the foreground is
white (`text-white`), because those backgrounds are theme-independent. Everywhere else,
prefer a token over `text-white`.

**Exception (§1.1.a, P0 accessibility):** the Telegram default button colors do not
pass WCAG AA with white text — `#5288c1` = 3.72:1 (dark), `#2481cc` = 4.12:1 (light).
The app's palettes in `store/theme.ts` use `#3b6ea5` (5.30:1) and `#1c6fb8` (5.24:1).
`store/theme.contrast.test.ts` enforces ≥ 4.5:1 for the button and hint tokens.

### 1.2 Availability status colors

Semantic scale for availability (`1=свободен`, `2=может`, `3=занят`). Fixed hexes, not
theme-dependent — they must read identically in light and dark.

| Token | Value | Use |
|---|---|---|
| `--status-free-fill` | `#22c55e` | cell fills, drag preview (large areas) |
| `--status-maybe-fill` | `#f59e0b` | cell fills |
| `--status-busy-fill` | `#ef4444` | cell fills, destructive text |
| `--status-free-pill` | `#15803d` | pill **background** (text on top) |
| `--status-maybe-pill` | `#b45309` | pill background |
| `--status-busy-pill` | `#b91c1c` | pill background |

`*-fill` values are for large tinted areas with no text. `*-pill` values are the
darkened shades that carry white text at 12px (≥ 4.5:1 WCAG AA, see §6).
Accessors: `statusColor()` (fill), `statusPillBg()` (pill) in
`src/features/calendar/dateUtils.ts`.

### 1.3 Own "stamp inks" (identity)

The only colors the product introduces on top of the Telegram theme. Used sparingly —
this is where the app's identity lives, so nothing else may claim an accent color.

| Token | Value | Meaning |
|---|---|---|
| `bg-ink-stamp` / `text-ink-stamp` | `#9b2c1f` | the shame titles (чухан недели, лох дня, главные лох/чухан) and the record holder in a table |
| `bg-ink-moss` / `text-ink-moss` | `#4e6b33` | the cursed «червь-пидор» |

Rule: the inks appear exactly twice per surface — on a **title's seal** and as the
**#1 row's fill** in a standings table. Never as decoration.

**The inks are backgrounds, never text.** As a foreground they fail contrast on the
dark theme (`#9b2c1f` on a dark surface). Where a leader needs emphasis in text, use
weight (`font-bold`), not ink.

### 1.4 Soft tints

For "quiet" variants (badges, bulk-action buttons, error cards) use the status/link
color at **15–18%** alpha over the current surface: `bg-status-busy/15`,
`bg-tg-link/15`, `bg-status-free/10`. Never below 10% (invisible) or above 20%
(competes with the fill).

### 1.5 Alpha modifiers on theme tokens (regression guard)

Telegram supplies each theme as a plain hex, so the usual
`rgb(var(--x) / <alpha-value>)` recipe is impossible. A bare `var(--x)` string makes
Tailwind **drop the `/NN` modifier silently** — the class is never generated. Until the
token layer was fixed, `bg-tg-secondary-bg/60` computed to `rgba(0,0,0,0)` (every card
borderless), `bg-tg-button/80` made primary buttons transparent, and `border-tg-hint/10`
fell back to Tailwind Preflight's `#e5e7eb` — a *light* grey that is wrong on the dark
theme.

The `tg-*` colors are therefore defined in `tailwind.config.ts` as **functions emitting
`color-mix()`**, which accepts any color format and keeps theme awareness. Verified:
`bg-tg-secondary-bg/60` → `color(srgb 0.945 0.945 0.945 / 0.6)`, `border-tg-hint/10` →
`color(srgb 0.6 0.6 0.6 / 0.1)` in both themes.

> ⚠️ **Changing `tailwind.config.ts` requires a dev-server restart.** Vite logs a page
> reload and the browser refetches, but Tailwind's PostCSS plugin keeps serving the old
> config — the change looks applied and is not. Restart before concluding anything.

### 1.6 Muted text

Telegram's own `tg-hint` is only **2.5:1** on a light `secondary_bg` (fails AA) while
being 7.6:1 on dark — i.e. a light/dark parity bug, not a taste question. Secondary text
that still has to be **read** (captions, ledger ranks, empty states) uses the semantic
**`text-muted`** token: 62% of the theme's text color → **5.96:1 light / 7.40:1 dark**
(measured). Reserve `text-tg-hint` for text that is decorative or duplicated elsewhere.

### 1.7 One accent per screen (VISUAL_AUDIT P3.16)

The accent is the theme's `tg-button`/`tg-link` pair. Only one thing on a screen may
wear a **filled** accent: the screen's main action ("Продолжить чек-лист",
"+ Сообщить", "Завести карточку").

| Role | Look |
|---|---|
| Main action | `bg-tg-button text-tg-button-text` — at most one per screen |
| Selection (segment tabs, filter chips) | `bg-tg-link/15 font-medium text-tg-text` — never filled |
| Secondary/inline action | `text-tg-link` on a neutral surface |
| State (done, overdue, error, warning) | `status-*` palette only, on the item's own pill |

Two rules follow from this and are easy to break:

1. **Status colors are semantics, not decoration.** A label like the test-pool `BOT`
   mark stays neutral (`bg-tg-hint/15 text-tg-hint`); otherwise amber/green on the same
   screen competes with real state.
2. **A selected filter is not a button.** Filling it with `bg-tg-button` made filters in
   the header look like the primary action and flattened the hierarchy.

The selection style deliberately uses `text-tg-text`, not `text-tg-link`: on a 15%
link tint the link color measures **3.07:1** in the light theme (AA needs 4.5:1 for
12px), while the body text color keeps **15.60:1 light / 10.33:1 dark**.
`theme.contrast.test.ts` checks the pair.

---

## 2. Typography

Body/display: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`.
Ledger/data: `font-mono` (system monospace stack, configured in `tailwind.config.ts`).

**No webfonts.** The app ships zero external font requests on purpose: the target
network is unreliable (see the project's RKN/host notes), so identity must come from
system faces, weight, tracking and case — never from a font CDN.

**Three roles:**
- *Display* — body face at `font-bold`, uppercase, `tracking-[0.08em]`; for section and
title headings only (the "stamped" register).
- *Body* — body face, weight 400–600, sentence case.
- *Ledger* — `font-mono` + `tabular-nums`; for **every number that is a counter**
(rank, count, `×N`). Counters are data, not prose.

| Token | Size | Line-height | Use |
|---|---|---|---|
| `text-3xs` | 10px | 1.2 | avatar initials, weekday/day headers, seal capture labels |
| `text-2xs` | 11px | 1.25 | badges, captions, secondary labels, chip text, ledger figures |
| `text-xs` | 12px | 1.4 | helper text, descriptions |
| `text-sm` | 14px | 1.45 | body, list rows, buttons |
| `text-base` | 16px | 1.4 | screen titles, card titles |
| `text-lg` | 18px | 1.3 | hero name, stat values |

**Rules:** minimum 10px anywhere; 8px and 9px are banned. Do not introduce sizes 1px
apart — use the scale. Weights: 400 body, 500 medium (buttons, values), 600 semibold
(titles). Uppercase + `tracking-wide` only for section-group labels (always
`text-2xs text-tg-hint`).

**`text-2xs` (11px) is a meta token, not body text.** It is allowed for timestamps,
counters, chip/badge text, avatar initials (with `text-3xs`) and day/weekday headers.
Descriptions, action captions and anything the user has to *read* start at `text-xs`
(12px). Before the 2026-10-20 typography pass, `text-[11px]` appeared 327 times and
`text-[10px]` 86 times, which read as "unfinished" on a phone (VISUAL_AUDIT P1.5).

**Arbitrary sizes are banned.** `text-[11px]`, `text-[9px]` and friends are not
allowed at all — the scale tokens are the only source of type sizes.
`src/styles.typeScale.test.ts` scans `src/**` and fails on any `text-[Npx]`, so a new
size cannot sneak back in.

---

## 3. Spacing

4px base scale. Permitted steps: `1(4) · 1.5(6) · 2(8) · 3(12) · 4(16) · 6(24) · 8(32)`.

| Context | Value |
|---|---|
| Inside chips/badges | `px-2 py-1` |
| Icon button padding | `min 44×44` (see §6) |
| Card padding | `p-3` (standard) · `p-4` (hero/profile only) |
| Gap between cards in a group | `space-y-2` |
| Gap between groups/sections | `space-y-4` or `pt-3` after a group divider |
| Screen content padding | `p-3` |

---

## 4. Radius

| Token | Value | Use |
|---|---|---|
| `rounded-card` | 12px | cards, sheets, screen sections |
| `rounded-tile` | 8px | inner tiles, inputs, buttons, badges, secondary surfaces |
| `rounded-full` | — | chips, pills, avatars, toggles |

**Rule:** one role → one token. Cards are never `rounded-tile`; fields and small
controls are never `rounded-card`. Side variants follow the same tokens
(`rounded-t-card`).

**Не `md`/`lg`/`xl`.** До 2026-10-20 в разметке жили четыре ступени Tailwind сразу:
`rounded-md` (6px) и `rounded-lg` (8px) обозначали одну и ту же роль, `rounded-xl`
(12px) был карточкой, `rounded-2xl` (16px) — редким исключением. Таблица выше
раньше называла неверные px (12/16/20 вместо реальных 6/8/12), и разметка
разъезжалась между соседними ступенями. Сейчас допустимы только `rounded-card`,
`rounded-tile`, `rounded-full` (и `rounded-none`); старые классы и произвольные
`rounded-[..]` ловит `src/styles.radius.test.ts`.

---

## 5. Elevation & borders

| Token | Definition | Use |
|---|---|---|
| `card` | `bg-tg-secondary-bg border border-tg-hint/10` | every card, section, sheet panel |
| `raised` | card + `shadow-sm` | elements lifted over content (pills, floating buttons) |
| separator | `border-tg-secondary-bg/60` (in-card) · `border-tg-hint/15` (between groups) | dividers |

**Rule:** cards use the **full-opacity** `bg-tg-secondary-bg` plus a hairline border —
NOT `/60` opacity, which is invisible on both themes. Shadows are for elements that
overlap other content, never for static cards.

---

## 6. Touch targets

Minimum interactive box: **44×44 CSS px** (`min-h-11 min-w-11`). Applies to icon buttons,
back buttons, close buttons, row actions and toggles' hit area. Destructive actions must
not sit flush against a frequent action at < 44px — separate them visually or reveal
destructive actions only in an edit/confirm state.

A **full-width row is still subject to the height minimum**: the greeting's collapse
toggle measured 334×**24** px — a wide but short target where taps just above/below the
text did nothing. It is now `min-h-11`, with the padding moved from the `header` into the
button so the banner's total height is unchanged.

Keyboard focus: `:focus-visible` draws `outline: 2px solid tg-link` with a 2px offset on
every interactive element (buttons, links, the custom `.chk-tg` / `.tgl-tg`). Declared
globally in `styles.css` **after** `@tailwind utilities` so it outranks `.outline-none`
by source order. Text inputs are exempt — they already signal focus via
`focus:border-tg-link`, and a second ring is noise in dense admin forms.

---

## 7. Motion

Primary spring: `{ type: "spring", stiffness: 500, damping: 32 }` (tab indicator, sheets).
Press feedback: `active:scale-[0.98]` (cards, buttons) with `transition-transform`.
Opacity/enter: 150ms. Defined with framer-motion — **do not** use Tailwind `animate-*`
utility classes for entrances (no plugin installed). Always honour
`prefers-reduced-motion` for scroll/transform animation, but keep functional motion (drag,
snap) intact.

**Tab change** (P3.17): `components/TabTransition.tsx` — 140ms `easeOut`, opacity
0→1 plus 4px rise. The key is applied by the caller (`key={tab}`), so the enter plays
per screen; under `prefers-reduced-motion` `initial={false}` and the screen appears in
its final state. No exit animation: navigation must not wait for the old screen.

---

## 8. Components

Shared primitives live in `src/components/`. Never re-declare them locally — duplication
is what caused the audit's consistency findings.

| Component | File | Notes |
|---|---|---|
| `Switch` | `components/Checkbox.tsx` | on/off toggle (`h-6 w-11`), haptic on change |
| `Toggle` | `components/Checkbox.tsx` | labelled toggle with active highlight (`.tgl-tg`) |
| `Checkbox` | `components/Checkbox.tsx` | `.chk-tg` |
| `Icon` | `components/Icon.tsx` | the only UI icon set: `currentColor`, 1.8px stroke, 24×24; names from `IconName` |
| `Card` | `components/Card.tsx` | icon tile + title + subtitle + optional badge + chevron |
| `ScreenHeader` | `components/ScreenHeader.tsx` | back button + title + optional subtitle |
| `ErrorState` | `components/ErrorState.tsx` | icon + humanized message + retry |
| `EmptyState` | `components/EmptyState.tsx` | icon + headline + hint |
| `Spinner` | `components/Spinner.tsx` | inline, `currentColor` |
| `Skeleton` / `CardSkeleton` / `ListSkeleton` | `components/Skeleton.tsx` | loading placeholders |

### 8.1 Signature: the seal

The one device this product should be remembered by. A title is a **stamp**, not a card:
a small fixed square (`h-7 w-7` inline, `h-8 w-8` section-level) filled with an ink from
§1.3, holding the title's glyph in white. `border-radius: 0` is **intentional** and is the
only place in the app where corners are square — the UI around it stays rounded. A seal
must not be resized per context, decorated, or given a gradient/shadow.

Where it appears: the звания blocks in `WelcomeBanner`, and the header of each standings
section in `LeaderboardScreen`. Nowhere else.

### 8.1.a Icons

UI chrome uses `Icon`, never an emoji: navigation, headers, admin cards, empty
states and controls. Emoji stay only in content — statuses (⏰ 📷), feed texts and
game phrasing — where they carry meaning, not layout. Icons are decorative
(`aria-hidden`); the accessible name comes from the button's `aria-label` or
visible text.

**Source: Iconoir** (`iconoir-react`, MIT, https://iconoir.com). One library for
the whole product — no mixing, no hand-drawn SVGs in screens (a single custom
icon next to Iconoir looks almost right and quietly shifts the row). The licence
notice lives in `frontend/THIRD_PARTY_NOTICES.md`, and `iconSet.test.tsx` fails if
the notice disappears or a `<svg>` appears outside `Icon.tsx`.

Fixed parameters, not per-screen choices: grid 24×24, outline style, line width
**1.8** (Iconoir's 1.5 is overridden once, on the `<svg>`), `currentColor` so a
single icon works in light and dark themes, `size` 20 by default and 13 for the
inline variant. Apple SF Symbols are not used in the web app — their licence does
not cover it.

### 8.2 Scoreboard fill

In a standings table, magnitude is shown as a **fill behind the row** (`absolute
inset-y-0 left-0`, width = share of the max), never as a rule under the name — a thin
bar directly beneath text reads as an underline, not as a value. Track opacity is 10%
(`bg-tg-hint/10`, leader: `bg-ink-stamp/10`); the fill is square, matching the seal's
geometry. Counts live in `font-mono tabular-nums`; the leader's count is `font-bold`.

---

## 9. Layout & responsiveness

Mobile-first. Content is a **centered column capped at 560px** (`max-w-[560px] mx-auto`)
so the app reads correctly from a 320px phone to Telegram Desktop; cell grids must not
stretch beyond that width. Beyond 560px the column sits on the page background with a
1px `border-tg-hint/10` on each side. The bottom tab bar shares the column width.

---

## 10. Localization

The UI language is Russian.
- `date-fns` `format()` must always receive `{ locale: ru }`, or use the `ruMonthShort`
  / `ruMonthFull` / `ruWeekdayShort` helpers in `features/calendar/dateUtils.ts`.
- Dates shown to humans use `toLocaleDateString("ru-RU")`.
- Pluralization goes through explicit helpers (e.g. `pluralVotes`), never English rules.

### 7.1 Press feedback (plan §10)

Every button responds to a press — it is a **base rule**, not a class someone has to
remember to add: 335 buttons exist, and the forgotten ones read as "dead" (headers, tab
bar, list rows).

| Where | Rule | Why |
|---|---|---|
| all `button`, `[role="button"]` | `scale: .97`, `opacity: .9`, 120 ms | compositor-only; layout never reflows, touch target (44 px) unchanged |
| `.press-icon` | `scale: .9` | small target needs a bigger cue |
| `.press-row` | tint + `opacity: .75`, no scale | a full-width row already got the finger; scaling it looks like a jump |
| `.lift` | `translate: 0 -1px` + soft shadow on hover | desktop only (`@media (hover: hover) and (pointer: fine)`) |
| `[data-no-press]` | opt out | gesture surfaces (tab bar, drag handles) where scaling reads as a layout jump |

Implementation notes that are easy to undo by accident:

* `scale` is the **individual property**, not `transform: scale()`. Half the overlays are
  centred with `-translate-*`; a transform-based squeeze would reset that and throw the
  element across the screen on touch.
* The selector is `button:not([data-no-press])`, not a bare `button`: a `transition-colors`
  utility (class specificity) would otherwise override our `transition-property` and the
  press would snap instantly instead of easing.
* `:disabled` / `aria-disabled="true"` cancel the reaction — a button that reacts but does
  nothing reads as a bug. Disabled opacity stays the component's own business.
* `prefers-reduced-motion` keeps the darkening and drops the movement.
* Raw `active:scale-*` in markup is forbidden (`press.guard.test.ts`): it bypasses
  reduced-motion, ignores `:disabled`, and drifted across 0.9/0.95/0.98/0.99.
* No ripple, no JS animation, no new dependency: the whole feature is ~40 lines of CSS
  already in the bundle, so it costs 0 kB of JS.
