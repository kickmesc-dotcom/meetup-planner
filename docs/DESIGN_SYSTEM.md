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
darkened shades that carry white text at 11px (≥ 4.5:1 WCAG AA, see §6).
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

**Rules:** minimum 10px anywhere; 9px is banned. Do not introduce sizes 1px apart —
use the scale. Weights: 400 body, 500 medium (buttons, values), 600 semibold (titles).
Uppercase + `tracking-wide` only for section-group labels (always `text-2xs text-tg-hint`).

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
| `rounded-md` | 12px | buttons, inputs, small controls |
| `rounded-lg` | 16px | inner tiles, secondary surfaces, sheets' inner blocks |
| `rounded-xl` | 20px | cards, sheets, screen sections |
| `rounded-full` | — | chips, pills, avatars, toggles |

**Rule:** one role → one token. Cards are never `rounded-md`; buttons are never
`rounded-xl`. (Legacy code mixes these; migrate on touch.)

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

---

## 8. Components

Shared primitives live in `src/components/`. Never re-declare them locally — duplication
is what caused the audit's consistency findings.

| Component | File | Notes |
|---|---|---|
| `Switch` | `components/Checkbox.tsx` | on/off toggle (`h-6 w-11`), haptic on change |
| `Toggle` | `components/Checkbox.tsx` | labelled toggle with active highlight (`.tgl-tg`) |
| `Checkbox` | `components/Checkbox.tsx` | `.chk-tg` |
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
