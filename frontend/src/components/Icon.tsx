import type { ComponentType, SVGProps } from "react";
import {
  Bell,
  BirthdayCake,
  Book,
  Calendar,
  Camera,
  ChatBubble,
  Check,
  CheckCircle,
  ClipboardCheck,
  Clock,
  Copy,
  DataTransferBoth,
  EditPencil,
  Flash,
  FloppyDisk,
  Globe,
  Group,
  HalfMoon,
  LayoutLeft,
  Link,
  List,
  Lock,
  LogOut,
  MailIn,
  MapPin,
  Medal,
  MediaImage,
  Microphone,
  NavArrowLeft,
  NavArrowRight,
  Network,
  Plus,
  Refresh,
  RefreshDouble,
  Search,
  Send,
  Settings,
  Sparks,
  Star,
  SunLight,
  TaskList,
  Tools,
  Trash,
  User,
  WarningTriangle,
  Xmark,
} from "iconoir-react";

/**
 * Единый набор иконок интерфейса (VISUAL_AUDIT P1.4).
 *
 * **Библиотека — Iconoir** (https://iconoir.com), лицензия MIT: разрешает
 * коммерческое использование, уведомление сохранено в `THIRD_PARTY_NOTICES.md`
 * и проверяется тестом `iconSet.test.ts`. Это единственный набор в проекте:
 * смешивать Iconoir с другими библиотеками нельзя, иначе в одном списке
 * встречаются две разные толщины линии и два скругления.
 *
 * Почему не эмодзи: один и тот же 🕒 на Windows, iOS и Android рисуется
 * по-разному (цветной/чёрно-белый, другой размер), и «фирменный» вид разваливался
 * от устройства к устройству.
 *
 * Почему компоненты пакета, а не свои SVG: набор из 46 иконок, нарисованный
 * руками, неизбежно расходится по пропорциям — у каждой иконки своя сетка,
 * радиус и оптическая толщина. Iconoir держит единую сетку 24×24 и единый
 * контурный стиль, близкий к Apple HIG, а пакет поставляет оригинальные файлы
 * библиотеки, а не их перерисовку.
 *
 * Толщина линии. У Iconoir по умолчанию 1.5; в проекте исторически 1.8, и
 * менять её «на глаз» по экранам нельзя. Здесь она задаётся одним параметром
 * на `<svg>` и наследуется контурами (`stroke="currentColor"` без своего
 * `stroke-width`), поэтому вся вёрстка остаётся с прежней оптической плотностью.
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
  | "bolt"
  | "mic";

interface Props extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  /** Размер в CSS px. По умолчанию 20 — строка навигации/шапки. */
  size?: number;
}

/**
 * Соответствие «имя в приложении → иконка Iconoir».
 *
 * Имена слева — часть публичного API `Icon`, поэтому они не меняются при
 * смене библиотеки: `shift` и `clock` намеренно ведут к одной и той же иконке
 * часов (это разные роли в интерфейсе, и переименование сломало бы 40 экранов
 * ради нуля пользы).
 */
const ICONS: Record<IconName, ComponentType<SVGProps<SVGSVGElement>>> = {
  tasks: CheckCircle,
  shift: Clock,
  calendar: Calendar,
  feed: List,
  profile: User,
  team: Group,
  admin: Tools,
  alert: WarningTriangle,
  clipboard: ClipboardCheck,
  bell: Bell,
  checklist: TaskList,
  book: Book,
  layout: LayoutLeft,
  award: Medal,
  cake: BirthdayCake,
  clock: Clock,
  repeat: RefreshDouble,
  globe: Globe,
  refresh: Refresh,
  edit: EditPencil,
  search: Search,
  send: Send,
  back: NavArrowLeft,
  chevron: NavArrowRight,
  close: Xmark,
  check: Check,
  plus: Plus,
  trash: Trash,
  camera: Camera,
  image: MediaImage,
  door: LogOut,
  sun: SunLight,
  moon: HalfMoon,
  lock: Lock,
  link: Link,
  save: FloppyDisk,
  copy: Copy,
  sparkles: Sparks,
  bot: ChatBubble,
  pin: MapPin,
  inbox: MailIn,
  star: Star,
  settings: Settings,
  swap: DataTransferBoth,
  signal: Network,
  bolt: Flash,
  mic: Microphone,
};

/**
 * Все имена набора в рантайме — для стража `iconSet.test.tsx`: он проверяет,
 * что каждая иконка действительно рисуется по сетке 24×24, а не только что
 * тип `IconName` компилируется.
 */
export const ICON_NAMES = Object.keys(ICONS) as IconName[];

export default function Icon({ name, size = 20, ...rest }: Props) {
  const Glyph = ICONS[name];
  return (
    <Glyph
      width={size}
      height={size}
      strokeWidth={1.8}
      aria-hidden="true"
      focusable="false"
      {...rest}
    />
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
