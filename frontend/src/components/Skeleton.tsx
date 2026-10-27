/**
 * Скелетоны загрузки: форма вместо надписи «Загрузка…».
 *
 * Правило одно (план, раздел 9): пока данные едут, экран показывает **каркас
 * той же формы**, что и будущий контент. Список — строки, карточки — карточки,
 * табель — плитки, таблица — строки с колонками. Человек на медленном канале
 * видит, где он и что сейчас появится, а не пустоту.
 *
 * Чего здесь сознательно нет:
 *
 * * спиннера на весь экран — он не объясняет, что грузится, и выглядит как
 *   зависание;
 * * произвольных цветов — только токены темы, иначе в тёмной теме скелетон
 *   «светится» ярче контента;
 * * анимации при `prefers-reduced-motion` (`motion-reduce:animate-none`) —
 *   мерцание на весь экран раздражает сильнее, чем помогает.
 */

interface Props {
  className?: string;
}

const PULSE = "animate-pulse motion-reduce:animate-none";

export function Skeleton({ className }: Props) {
  return (
    <div
      className={[PULSE, "rounded-tile bg-tg-bg/50", className ?? ""].join(" ")}
    />
  );
}

/**
 * Строки текста. Ширина «рваная» (100% / 90% / 70%), чтобы блок читался как
 * абзац, а не как таблица.
 */
export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  const widths = ["w-full", "w-11/12", "w-4/5", "w-2/3"];
  return (
    <div className={[PULSE, "space-y-2", className ?? ""].join(" ")}>
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className={[
            "h-3 rounded-tile bg-tg-bg/40",
            widths[index % widths.length],
          ].join(" ")}
        />
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className={[PULSE, "rounded-card bg-tg-secondary-bg/60 p-3 space-y-2"].join(" ")}>
      <div className="h-4 w-2/3 rounded-tile bg-tg-bg/60" />
      <div className="h-3 w-1/3 rounded-tile bg-tg-bg/40" />
      <div className="mt-2 flex gap-1.5">
        <div className="h-5 w-16 rounded-full bg-tg-bg/40" />
        <div className="h-5 w-16 rounded-full bg-tg-bg/40" />
        <div className="h-5 w-16 rounded-full bg-tg-bg/30" />
      </div>
      <div className="mt-2 flex gap-1.5">
        <div className="h-7 flex-1 rounded-tile bg-tg-bg/40" />
        <div className="h-7 flex-1 rounded-tile bg-tg-bg/40" />
        <div className="h-7 flex-1 rounded-tile bg-tg-bg/40" />
      </div>
    </div>
  );
}

export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className={[PULSE, "space-y-2"].join(" ")}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-tg-bg/50" />
          <div className="flex-1 h-4 rounded-tile bg-tg-bg/40" />
          <div className="w-7 h-4 rounded-tile bg-tg-bg/40" />
        </div>
      ))}
    </div>
  );
}

/**
 * Таблица: строки с `cols` колонками. Для админки, где ответ — набор строк, а
 * не карточек: скелетон обязан совпадать по сетке, иначе контент «прыгнет».
 */
export function SkeletonTable({
  rows = 4,
  cols = 3,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className={[PULSE, "space-y-2"].join(" ")}>
      {Array.from({ length: rows }).map((_, row) => (
        <div key={row} className="flex items-center gap-2">
          {Array.from({ length: cols }).map((_, col) => (
            <div
              key={col}
              className={[
                "h-4 rounded-tile bg-tg-bg/40",
                col === 0 ? "flex-1" : "w-16",
              ].join(" ")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * Плитки одной сеткой — табель, календарь, полоса дней. `aspect` держит высоту
 * такой же, как у настоящей плитки.
 */
export function SkeletonTiles({
  count = 7,
  className,
}: {
  count?: number;
  className?: string;
}) {
  return (
    <div className={[PULSE, "grid gap-2", className ?? "grid-cols-3"].join(" ")}>
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="h-12 rounded-tile bg-tg-bg/40" />
      ))}
    </div>
  );
}

/**
 * Ряд «таблеток» — выбор отделов, фильтры, теги. Ширины разные, потому что
 * настоящие подписи разной длины; одинаковые выглядели бы как полоса загрузки.
 */
export function SkeletonChips({
  count = 6,
  className,
}: {
  count?: number;
  className?: string;
}) {
  const widths = ["w-20", "w-16", "w-24", "w-14", "w-20", "w-16"];
  return (
    <div className={[PULSE, "flex flex-wrap gap-1.5", className ?? ""].join(" ")}>
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className={[
            "h-9 rounded-full bg-tg-secondary-bg",
            widths[index % widths.length],
          ].join(" ")}
        />
      ))}
    </div>
  );
}

/**
 * Плитки на горизонтальной ленте (день недели / слоты времени).
 */
export function SkeletonStrip({ tiles = 5 }: { tiles?: number }) {
  return (
    <div className={[PULSE, "flex gap-2 overflow-hidden"].join(" ")}>
      {Array.from({ length: tiles }).map((_, index) => (
        <div
          key={index}
          className="h-14 w-24 shrink-0 rounded-tile bg-tg-bg/40"
        />
      ))}
    </div>
  );
}
