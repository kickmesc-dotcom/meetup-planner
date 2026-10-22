import type { ReactElement, SVGProps } from "react";

/**
 * Единый набор иконок интерфейса (VISUAL_AUDIT P1.4).
 *
 * Почему свои SVG, а не эмодзи: один и тот же 🕒 на Windows, iOS и Android
 * рисуется по-разному (цветной/чёрно-белый/другой формы), поэтому «фирменный»
 * вид разваливался от устройства к устройству. Здесь один стиль: `currentColor`,
 * толщина 1.8, скруглённые концы, сетка 24×24.
 *
 * Почему без библиотеки: приложение принципиально не тянет внешние зависимости
 * ради иконок и не делает сетевых запросов за шрифтами (см. DESIGN_SYSTEM §2).
 * Набор сознательно маленький — только то, что реально используется в навигации
 * и шапках. Эмодзи остаются в игровых формулировках, статусах и текстах.
 *
 * Иконки декоративные: рядом всегда есть подпись (`aria-label` у кнопки или
 * текст), поэтому по умолчанию `aria-hidden`.
 */
export type IconName =
  | "tasks"
  | "shift"
  | "calendar"
  | "feed"
  | "profile"
  | "team"
  | "admin"
  | "alert"
  | "clipboard"
  | "bell"
  | "checklist"
  | "book"
  | "layout"
  | "award"
  | "cake"
  | "clock"
  | "repeat"
  | "globe"
  | "refresh"
  | "edit"
  | "search"
  | "send"
  | "back"
  | "chevron"
  | "close"
  | "check"
  | "plus"
  | "trash"
  | "camera"
  | "image"
  | "door"
  | "sun"
  | "moon"
  | "lock"
  // P1.4, проход по админке и сервисным экранам: ссылки, сохранение,
  // копирование, бот, закладка, почта, звезда, настройки, скорость и сигнал.
  | "link"
  | "save"
  | "copy"
  | "sparkles"
  | "bot"
  | "pin"
  | "inbox"
  | "star"
  | "settings"
  | "swap"
  | "signal"
  | "bolt";

interface Props extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  /** Размер в CSS px. По умолчанию 20 — строка навигации/шапки. */
  size?: number;
}

export default function Icon({ name, size = 20, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}

/**
 * Иконка внутри текстовой строки (метаданные карточки: срок, смена, фото).
 *
 * Отдельный компонент, потому что `inline-block align-[-2px]` повторялся бы
 * в каждой строке и разъезжался при правках. Эмодзи на этом месте рисовались
 * по-разному в зависимости от ОС (P1.4).
 */
export function InlineIcon({ name }: { name: IconName }) {
  return (
    <Icon
      name={name}
      size={13}
      className="mr-1 inline-block shrink-0 align-[-2px]"
    />
  );
}

const PATHS: Record<IconName, ReactElement> = {
  tasks: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.2 12.3 2.5 2.5 5.1-5.4" />
    </>
  ),
  shift: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 1.8" />
    </>
  ),
  calendar: (
    <>
      <rect x="3.8" y="5.2" width="16.4" height="15" rx="2" />
      <path d="M8 3.2v3.4M16 3.2v3.4M3.8 9.6h16.4" />
    </>
  ),
  feed: (
    <>
      <path d="M5 7h14M5 12h14M5 17h9" />
      <circle cx="3.2" cy="7" r="0.6" fill="currentColor" stroke="none" />
      <circle cx="3.2" cy="12" r="0.6" fill="currentColor" stroke="none" />
      <circle cx="3.2" cy="17" r="0.6" fill="currentColor" stroke="none" />
    </>
  ),
  profile: (
    <>
      <circle cx="12" cy="8.2" r="3.7" />
      <path d="M4.8 20c.7-3.5 3.6-5.6 7.2-5.6s6.5 2.1 7.2 5.6" />
    </>
  ),
  team: (
    <>
      <circle cx="9.2" cy="8.5" r="3.1" />
      <path d="M3.4 19c.6-3 2.9-4.9 5.8-4.9s5.2 1.9 5.8 4.9" />
      <path d="M16 6.1a3 3 0 0 1 0 5.8M17.3 14.4c2 .5 3.3 2.1 3.7 4.6" />
    </>
  ),
  admin: (
    <>
      <path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3" />
      <circle cx="15" cy="7" r="1.9" fill="currentColor" stroke="none" />
      <circle cx="9" cy="12" r="1.9" fill="currentColor" stroke="none" />
      <circle cx="15" cy="17" r="1.9" fill="currentColor" stroke="none" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4.2 21 19H3z" />
      <path d="M12 9.5v4.2M12 16.6v.2" />
    </>
  ),
  clipboard: (
    <>
      <rect x="5" y="4.5" width="14" height="16" rx="2" />
      <path d="M9 4.5V3.2h6v1.3M9 10h6M9 14h6" />
    </>
  ),
  bell: (
    <>
      <path d="M6.5 9.5a5.5 5.5 0 0 1 11 0c0 4 1.5 5.5 1.5 5.5H5s1.5-1.5 1.5-5.5Z" />
      <path d="M10 18.5a2.2 2.2 0 0 0 4 0" />
    </>
  ),
  checklist: (
    <>
      <path d="M8 6.5h12M8 12h12M8 17.5h12" />
      <path d="m3 11.6 1.4 1.4L7 10.4" />
    </>
  ),
  book: (
    <>
      <path d="M4 5.5c2.5-1 5.3-1 8 .8v13c-2.7-1.8-5.5-1.8-8-.8z" />
      <path d="M20 5.5c-2.5-1-5.3-1-8 .8v13c2.7-1.8 5.5-1.8 8-.8z" />
    </>
  ),
  layout: (
    <>
      <rect x="3.8" y="4.2" width="16.4" height="15.6" rx="2" />
      <path d="M3.8 9.5h16.4M10 9.5v10.3" />
    </>
  ),
  award: (
    <>
      <circle cx="12" cy="9" r="5.2" />
      <path d="m8.6 13.3-1.4 7 4.8-2.6 4.8 2.6-1.4-7" />
    </>
  ),
  cake: (
    <>
      <path d="M4 20h16v-6.5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2z" />
      <path d="M4 16.2c1.6-1.4 3.2-1.4 4.8 0s3.2 1.4 4.8 0 3.2-1.4 4.8 0M8.4 8.5V11M12 7V11M15.6 8.5V11" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 1.8" />
    </>
  ),
  repeat: (
    <>
      <path d="M5 9.5A6.5 6.5 0 0 1 17.6 7M19 14.5A6.5 6.5 0 0 1 6.4 17" />
      <path d="M17.5 3.8V7h-3.2M6.5 20.2V17h3.2" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.4 2.3 3.6 5.1 3.6 8.5s-1.2 6.2-3.6 8.5c-2.4-2.3-3.6-5.1-3.6-8.5S9.6 5.8 12 3.5Z" />
    </>
  ),
  refresh: (
    <>
      <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" />
      <path d="M19.8 4.2v4.1h-4.1" />
    </>
  ),
  edit: (
    <>
      <path d="M15.5 4.8 19.2 8.5 8.9 18.8l-4.6 1.1 1.1-4.6z" />
      <path d="m13.8 6.5 3.7 3.7" />
    </>
  ),
  search: (
    <>
      <circle cx="10.8" cy="10.8" r="6.3" />
      <path d="m15.5 15.5 4 4" />
    </>
  ),
  send: (
    <>
      <path d="M20.5 3.5 3.8 10.2l6.1 2.4 2.4 6.1z" />
      <path d="m9.9 12.6 4.4-4.4" />
    </>
  ),
  back: <path d="M14.5 5.5 8 12l6.5 6.5" />,
  chevron: <path d="m9.5 5.5 6.5 6.5-6.5 6.5" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  check: <path d="m4.8 12.6 4.6 4.6L19.2 7" />,
  plus: <path d="M12 5v14M5 12h14" />,
  trash: (
    <>
      <path d="M4.5 6.5h15M9.5 6.5V4.2h5v2.3M6.5 6.5l.9 13.3h9.2l.9-13.3" />
      <path d="M10.2 10.5v5.8M13.8 10.5v5.8" />
    </>
  ),
  camera: (
    <>
      <path d="M3.8 8.5h3l1.6-2.3h7.2l1.6 2.3h3v10.2H3.8z" />
      <circle cx="12" cy="13.3" r="3.4" />
    </>
  ),
  image: (
    <>
      <rect x="3.8" y="4.8" width="16.4" height="14.4" rx="2" />
      <circle cx="9" cy="9.6" r="1.6" />
      <path d="m4.5 17 5-5 3.4 3.4 2.6-2.6 4 4" />
    </>
  ),
  door: (
    <>
      <path d="M5 20.5h14M6.5 20.5V4.2L17.5 3v17.5" />
      <circle cx="14.6" cy="12" r="0.8" fill="currentColor" stroke="none" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6" />
    </>
  ),
  moon: <path d="M20 14.2A8.2 8.2 0 0 1 9.8 4a8.5 8.5 0 1 0 10.2 10.2Z" />,
  // Замок: подсказки «видно только тебе» и ограниченный доступ.
  lock: (
    <>
      <rect x="5" y="10.8" width="14" height="9.2" rx="2" />
      <path d="M8.2 10.8V7.9a3.8 3.8 0 0 1 7.6 0v2.9M12 14.4v2" />
    </>
  ),
  link: (
    <>
      <path d="M9.6 14.4l4.8-4.8" />
      <path d="M13.2 7.2 15 5.4a3.6 3.6 0 0 1 5.1 5.1L18.3 12.3" />
      <path d="M10.8 16.8 8.9 18.6a3.6 3.6 0 0 1-5.1-5.1l1.8-1.8" />
    </>
  ),
  save: (
    <>
      <path d="M5 4.5h11.2L19.5 8v11.5h-15z" />
      <path d="M8.5 4.5v5h7v-5M8.5 19.5v-5.2h7v5.2" />
    </>
  ),
  copy: (
    <>
      <rect x="8.5" y="8.5" width="11" height="11.5" rx="2" />
      <path d="M15.5 8.5V5.8a1.8 1.8 0 0 0-1.8-1.8H5.8A1.8 1.8 0 0 0 4 5.8v7.9a1.8 1.8 0 0 0 1.8 1.8h2.7" />
    </>
  ),
  sparkles: (
    <>
      <path d="M11 3.8 12.5 8l4.2 1.5L12.5 11 11 15.2 9.5 11 5.3 9.5 9.5 8z" />
      <path d="M17.8 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" />
    </>
  ),
  bot: (
    <>
      <rect x="4.2" y="8" width="15.6" height="11" rx="3" />
      <path d="M12 4.2V8M9 3h6" />
      <circle cx="9.2" cy="13" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="14.8" cy="13" r="1.1" fill="currentColor" stroke="none" />
      <path d="M9.5 16.4h5" />
    </>
  ),
  pin: (
    <>
      <path d="M12 21s6.2-5.6 6.2-10.2A6.2 6.2 0 0 0 5.8 10.8C5.8 15.4 12 21 12 21Z" />
      <circle cx="12" cy="10.4" r="2.4" />
    </>
  ),
  inbox: (
    <>
      <path d="M4 5.2h16v13.6H4z" />
      <path d="M4 13.2h4.2l1.3 2h5l1.3-2H20" />
    </>
  ),
  star: <path d="m12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4L4.2 9.7l5.4-.8z" />,
  // «Настройки» — ползунки: так иконка читается даже в 13 px, в отличие
  // от шестерёнки с мелкими зубцами.
  settings: (
    <>
      <path d="M4 7h6M14 7h6M4 12h10M18 12h2M4 17h4M12 17h8" />
      <circle cx="12" cy="7" r="1.9" fill="currentColor" stroke="none" />
      <circle cx="16" cy="12" r="1.9" fill="currentColor" stroke="none" />
      <circle cx="10" cy="17" r="1.9" fill="currentColor" stroke="none" />
    </>
  ),
  swap: (
    <>
      <path d="M7 4.5v15M7 4.5 4.2 7.3M7 4.5l2.8 2.8" />
      <path d="M17 19.5v-15M17 19.5l-2.8-2.8M17 19.5l2.8-2.8" />
    </>
  ),
  signal: <path d="M5 18.5V15M9.5 18.5v-6M14 18.5V9M18.5 18.5V6.5" />,
  bolt: <path d="M13.2 3.5 5.8 13h5l-1 7.5L17.4 11h-5.1z" />,
};
