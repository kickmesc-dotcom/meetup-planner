import type { ReactNode } from "react";
import { addDays, format, startOfDay } from "date-fns";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { AnimatePresence, LayoutGroup } from "framer-motion";
import type { AvailabilityRange, User } from "@/types";
import type { BirthdayCalendarEntry, CalendarMark, CurrentTitles } from "@/api/birthdays";
import { confidenceFillForDay, rangeToPillRect, statusLabel } from "./dateUtils";
import { useUI } from "@/store/ui";
import { createRange } from "@/api/availability";
import { haptic } from "@/tg/webapp";
import RangePill from "./RangePill";

interface Props {
  user: User;
  isMe: boolean;
  ranges: AvailabilityRange[];
  windowStart: Date;
  windowSpan: number;
  /** ДР этого участника в окне (после фильтра по user_id в StripView). */
  birthdays?: BirthdayCalendarEntry[];
  /** Отметки лох/чухан этого участника в окне. */
  marks?: CalendarMark[];
  /**
   * GHG7 P2.1: актуальные звания (общие для всех участников). Per-user флаги
   * вычисляются внутри по `user.id` → рисуются «шапкой» иконок над аватаркой.
   * Заменяет прежний булев `isWorm` (червь теперь часть общего стека).
   */
  titles?: CurrentTitles | null;
  /**
   * GHG6 CL1: фикс-ширина одной ячейки в пикселях. Если задано — строка не
   * растягивается на flex-1, а имеет ширину windowSpan × cellWidth. Используется
   * TimelineView для синхронизации сетки строк с горизонтальным скроллом и шапкой.
   * Если не задано — legacy-режим: 1fr (растягивается на доступную ширину).
   */
  cellWidth?: number;
  /**
   * GHG6 CL2: индексы видимого диапазона дней (включительно, с учётом OVERSCAN),
   * прокинутые из TimelineView. Дни за пределами схлопываются в два
   * grid-спейсера (`grid-column: span N`) — экономит full-cell DOM-узлы и тяжёлые
   * per-cell-расчёты (`confidenceFillForDay`, lookup ДР/marks, `ranges.some` для
   * `covered`). На 6 строк × 43 дня это ощутимый выигрыш при движении слайдера
   * зума и быстром горизонтальном скролле на старых iPhone. Если не заданы —
   * рендерим все ячейки (legacy StripView и unit-cовместимость).
   */
  visibleStart?: number;
  visibleEnd?: number;
}

export default function ParticipantRow({
  user,
  isMe,
  ranges,
  windowStart,
  windowSpan,
  birthdays = [],
  marks = [],
  titles = null,
  cellWidth,
  visibleStart,
  visibleEnd,
}: Props) {
  const setEditing = useUI((s) => s.setEditingRangeId);
  const setBirthdayPopover = useUI((s) => s.setBirthdayPopover);
  const setLoserReasonPopover = useUI((s) => s.setLoserReasonPopover);
  const qc = useQueryClient();

  const createMut = useMutation({
    mutationFn: createRange,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["ranges"] });
      setEditing(created.id);
    },
    onError: () => haptic("error"),
  });

  const onCellTap = (dayIndex: number) => {
    if (!isMe) return;
    haptic("light");
    const dayStart = startOfDay(addDays(windowStart, dayIndex));
    const dayEnd = addDays(dayStart, 1);
    const dayStartMs = dayStart.getTime();
    const dayEndMs = dayEnd.getTime();
    // GHG6 CL7: в timeline-режиме (cellWidth задан) пилюли RangePill не
    // рендерятся — поэтому тап по уже отмеченной ячейке должен открывать
    // редактор существующего range, а не создавать второй поверх первого.
    // Если на день несколько range — открываем worst-status (как и заливка).
    if (cellWidth) {
      const overlapping = ranges.filter((r) => {
        const s = new Date(r.starts_at).getTime();
        const e = new Date(r.ends_at).getTime();
        return s < dayEndMs && e > dayStartMs;
      });
      if (overlapping.length > 0) {
        const target = overlapping.reduce((a, b) =>
          b.status > a.status ? b : a,
        );
        setEditing(target.id);
        return;
      }
    }
    // GHG6 CL8: дефолт confidence по статусу — свободен/занят → 5 (полная
     // уверенность), может → 3 (срединный «под вопросом»). На creation статус=1
     // (свободен), значит confidence=5.
     createMut.mutate({
      starts_at: dayStart.toISOString(),
      ends_at: dayEnd.toISOString(),
      all_day: true,
      status: 1,
      confidence: 5,
    });
  };

  // GHG6 BD1/BD5: индексы по YYYY-MM-DD, чтобы не сканить массивы в каждой ячейке.
  // GHG6 J: для loser-меток храним множество источников ('auto'|'manual') —
  // в одном дне может быть и автолох, и ручной ролл, тогда рисуем 👑×2.
  const bdayByDate = new Map(birthdays.map((b) => [b.date, b]));
  const chukhanByDate = new Set<string>();
  const loserSourcesByDate = new Map<string, Set<string>>();
  for (const m of marks) {
    if (m.type === "chukhan") {
      chukhanByDate.add(m.date);
    } else if (m.type === "loser") {
      const src = m.source ?? "manual";
      const set = loserSourcesByDate.get(m.date) ?? new Set<string>();
      set.add(src);
      loserSourcesByDate.set(m.date, set);
    }
  }
  const todayKey = format(startOfDay(new Date()), "yyyy-MM-dd");

  // GHG7 P2.1.a/b: «шапка» актуальных званий поверх аватарки. Порядок в массиве
  // = порядок отрисовки слева-направо (приоритет): ДР > лох дня > главный лох >
  // чухан недели > червь. Несколько званий показываем стеком рядом.
  // Лох дня = 👑, главный лох = 🤡 (разные иконки — могут совпасть у разных
  // или у одного участника одновременно).
  const titleBadges: { key: string; icon: string; label: string }[] = [];
  if (titles) {
    if (titles.birthday_today_user_ids.includes(user.id)) {
      titleBadges.push({ key: "bday", icon: "🎂", label: "День рождения сегодня" });
    }
    if (titles.loser_today_user_id === user.id) {
      titleBadges.push({ key: "loser-today", icon: "👑", label: "Лох дня" });
    }
    if (titles.main_loser_user_id === user.id) {
      titleBadges.push({ key: "main-loser", icon: "🤡", label: "Главный лох" });
    }
    if (titles.chukhan_user_id === user.id) {
      titleBadges.push({ key: "chukhan", icon: "💩", label: "Чухан недели" });
    }
    if (titles.worm_user_id === user.id) {
      titleBadges.push({ key: "worm", icon: "🪱", label: "Червь-пидор" });
    }
  }

  return (
    <div className="relative flex items-center border-b border-tg-secondary-bg/60">
      {/* GHG6 CL1: sticky-left делает колонку аватара "вмороженной" при
          горизонтальном скролле TimelineView. В StripView (легаси) родитель
          горизонтально не скроллится, поэтому sticky здесь — no-op. */}
      <div className="w-[60px] flex flex-col items-center py-1.5 shrink-0 sticky left-0 z-10 bg-tg-bg">
        <div className="relative">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-medium overflow-hidden"
            style={{ background: user.color_hex }}
            title={
              titleBadges.length > 0
                ? `${user.display_name} — ${titleBadges.map((b) => b.label).join(", ")}`
                : user.display_name
            }
          >
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={user.display_name}
                className="w-full h-full object-cover"
              />
            ) : (
              initials(user.display_name)
            )}
          </div>
          {/* GHG7 P2.1.a/b: «шапка» актуальных званий — горизонтальный стек
              иконок поверх аватарки. z-20 выше кружка (z-10 колонки). Каждая
              иконка на фон-плашке bg-tg-bg для читаемости поверх любого аватара.
              -top-2 + центрирование по горизонтали — «сидит на макушке».
              P2.1.c (клик → попап-история) — отдельный подэтап, пока иконки
              информативные (title/aria-label). */}
          {titleBadges.length > 0 && (
            <div
              className="pointer-events-none absolute -top-2 left-1/2 -translate-x-1/2 z-20 flex gap-0.5"
              aria-hidden={false}
            >
              {titleBadges.map((b) => (
                <span
                  key={b.key}
                  aria-label={b.label}
                  title={b.label}
                  className="text-[12px] leading-none bg-tg-bg rounded-full px-0.5 shadow-sm"
                >
                  {b.icon}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="text-[10px] text-tg-hint truncate max-w-[60px] mt-0.5">
          {firstName(user.display_name)}
        </div>
      </div>

      {/* CAL1: overflow-hidden + contain жёстко удерживают пилюли в пределах
          разметки. Любая анимация framer-motion, выходящая за грань,
          клиппится контейнером.
          CL1: при заданном cellWidth — фикс-ширина (TimelineView), иначе
          1fr (legacy StripView). */}
      <div
        className={[
          "relative grid h-14 overflow-hidden [contain:layout_paint]",
          cellWidth ? "" : "flex-1",
        ].join(" ")}
        style={{
          gridTemplateColumns: cellWidth
            ? `repeat(${windowSpan}, ${cellWidth}px)`
            : `repeat(${windowSpan}, minmax(36px, 1fr))`,
          width: cellWidth ? windowSpan * cellWidth : undefined,
        }}
      >
        {(() => {
          // CL2: схлопываем невидимые края в grid-спейсеры через
          // `grid-column: span N` — экономим full-cell DOM-узлы и тяжёлые
          // per-cell-расчёты для невидимых дней. Активно только в timeline-
          // режиме (cellWidth задан) и когда TimelineView передал границы.
          // В legacy StripView (без cellWidth) границы не переданы — рендерим
          // всё, как раньше.
          const start = cellWidth !== undefined ? (visibleStart ?? 0) : 0;
          const end =
            cellWidth !== undefined
              ? (visibleEnd ?? windowSpan - 1)
              : windowSpan - 1;
          const leftSpan = Math.max(0, start);
          const rightSpan = Math.max(0, windowSpan - 1 - end);
          const cells: ReactNode[] = [];
          if (leftSpan > 0) {
            cells.push(
              <div
                key="spacer-left"
                aria-hidden
                style={{ gridColumn: `span ${leftSpan}` }}
              />,
            );
          }
          for (let i = start; i <= end; i++) {
            const dayStart = startOfDay(addDays(windowStart, i));
            const dayKey = format(dayStart, "yyyy-MM-dd");
            const dayEnd = addDays(dayStart, 1).getTime();
            const dayStartMs = dayStart.getTime();
            const covered = ranges.some((r) => {
              const s = new Date(r.starts_at).getTime();
              const e = new Date(r.ends_at).getTime();
              return s < dayEnd && e > dayStartMs;
            });
            // GHG6 CL7: confidence-заливка работает только в timeline-режиме
            // (когда cellWidth задан). В legacy StripView фон ячейки оставлен
            // как был — там визуальный язык строится на пилюлях, и переключение
            // на заливку ломает существующий UX вне фокуса P3.
            const fill = cellWidth ? confidenceFillForDay(dayStart, ranges) : null;
            const isLast = i === windowSpan - 1;
            const bday = bdayByDate.get(dayKey);
            // BD5: бейджи лох/чухан показываем только на прошедших днях, чтобы
            // в будущем не светить будущие записи (их там и не должно быть, но
            // на всякий случай защищаемся от часовых поясов и подмены даты).
            const isPast = dayKey < todayKey;
            const loserSources = isPast ? loserSourcesByDate.get(dayKey) : undefined;
            const loserCount = loserSources?.size ?? 0;
            const showChukhan = isPast && chukhanByDate.has(dayKey);
            // GHG6 J4: при узких ячейках (cellWidth<40) две короны рядом
            // не помещаются — складываем в 👑×2. В legacy StripView без cellWidth
            // — всегда рисуем подряд (там ширина ячейки растягивается на 1fr).
            const compactLoser = loserCount > 1 && cellWidth !== undefined && cellWidth < 40;
            // GHG6 CL9: при partial=null (или fill отсутствует) фон рисуем
            // на самой кнопке (как было). При partial — кнопка прозрачная, а
            // фон уходит в отдельный pointer-events-none div поверх (под
            // бейджами 👑/💩/🎂), занимающий только долю дня по top/height.
            const hasPartial = fill?.partial != null;
            const partialPct = fill?.partial
              ? {
                  top: `${(fill.partial.top * 100).toFixed(2)}%`,
                  height: `${(fill.partial.height * 100).toFixed(2)}%`,
                }
              : null;
            cells.push(
              <div
                key={i}
                className={[
                  "h-full relative",
                  isLast ? "" : "border-r border-tg-secondary-bg/70",
                ].join(" ")}
              >
                <button
                  type="button"
                  onClick={() => onCellTap(i)}
                  disabled={!isMe || createMut.isPending}
                  className={[
                    "absolute inset-0",
                    isMe ? "active:bg-tg-secondary-bg/50" : "",
                    // «Не отмечено» паттерн — только в legacy-режиме (без cellWidth)
                    // или в timeline-режиме когда нет ни одного range на день.
                    !covered
                      ? "bg-[repeating-linear-gradient(45deg,transparent_0_4px,rgba(239,68,68,0.08)_4px_8px)]"
                      : "",
                  ].join(" ")}
                  style={
                    fill && !hasPartial
                      ? { background: fill.background }
                      : undefined
                  }
                  aria-label={
                    fill
                      ? `${statusLabel(fill.status)}, уверенность ${fill.confidence}/5${hasPartial ? " (часть дня)" : ""}`
                      : `day ${i}`
                  }
                  title={
                    fill
                      ? `${statusLabel(fill.status)} · уверенность ${fill.confidence}/5${hasPartial ? " · часть дня" : ""}`
                      : !covered
                        ? "Не отмечено — считается занятым"
                        : undefined
                  }
                />
                {/* GHG6 CL9: частичная заливка по высоте worst-range при all_day=false.
                    Позиционируем top/height в процентах от ячейки (24h scale).
                    pointer-events-none — клик уходит на основную кнопку. */}
                {fill && partialPct && (
                  <div
                    aria-hidden
                    className="pointer-events-none absolute left-0 right-0"
                    style={{
                      top: partialPct.top,
                      height: partialPct.height,
                      background: fill.background,
                    }}
                  />
                )}
                {/* GHG6 CL9: индикатор «не на весь день» — 🕓 в левом-верхнем
                    углу ячейки. Только при partial-заливке. */}
                {hasPartial && (
                  <span
                    aria-hidden
                    className="pointer-events-none absolute top-0.5 left-0.5 text-[10px] leading-none opacity-70"
                  >
                    🕓
                  </span>
                )}
                {/* GHG6 BD5/J4: «прошедшие» бейджи лох/чухан в углу ячейки.
                    pointer-events-none — клик уходит на основную кнопку.
                    GHG6 J: автолох + ручной ролл в один день — две короны
                    подряд (👑👑), либо 👑×2 в узких ячейках. */}
                {(loserCount > 0 || showChukhan) && (
                  <div className="pointer-events-none absolute bottom-0.5 left-0.5 flex gap-0.5 text-[10px] leading-none">
                    {/* GHG7 P0.2.e: 👑 — кликабельная, открывает попап с
                        причиной ролла. pointer-events:auto точечно на
                        корону; родительский div остаётся none, чтобы клик
                        по фону ячейки уходил на основную кнопку. */}
                    {loserCount > 0 && (
                      compactLoser ? (
                        <button
                          type="button"
                          aria-label={`Был лохом ${loserCount} раза — причина`}
                          title="Показать причину"
                          className="pointer-events-auto active:scale-95"
                          onClick={(e) => {
                            e.stopPropagation();
                            haptic("selection");
                            setLoserReasonPopover({
                              userId: user.id,
                              date: dayKey,
                              displayName: user.display_name,
                            });
                          }}
                        >
                          👑×{loserCount}
                        </button>
                      ) : (
                        Array.from({ length: loserCount }).map((_, k) => (
                          <button
                            key={`crown-${k}`}
                            type="button"
                            aria-label="Был лохом — причина"
                            title="Показать причину"
                            className="pointer-events-auto active:scale-95"
                            onClick={(e) => {
                              e.stopPropagation();
                              haptic("selection");
                              setLoserReasonPopover({
                                userId: user.id,
                                date: dayKey,
                                displayName: user.display_name,
                              });
                            }}
                          >
                            👑
                          </button>
                        ))
                      )
                    )}
                    {showChukhan && <span aria-label="Был чуханом">💩</span>}
                  </div>
                )}
                {/* GHG6 BD1+BD3: 🎂 живёт в ячейке участника-именинника. Иконка —
                    отдельная кнопка с pointer-events:auto и stopPropagation,
                    чтобы тап по ячейке вне иконки работал как обычно. */}
                {bday && (
                  <button
                    type="button"
                    aria-label={`День рождения ${user.display_name}`}
                    title={`🎂 ${user.display_name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      haptic("selection");
                      setBirthdayPopover({
                        userId: user.id,
                        date: bday.date,
                        displayName: user.display_name,
                      });
                    }}
                    className="absolute top-0.5 right-0.5 z-10 text-[12px] leading-none rounded-sm bg-tg-bg/70 px-0.5 active:scale-95"
                  >
                    🎂
                  </button>
                )}
              </div>,
            );
          }
          if (rightSpan > 0) {
            cells.push(
              <div
                key="spacer-right"
                aria-hidden
                style={{ gridColumn: `span ${rightSpan}` }}
              />,
            );
          }
          return cells;
        })()}

        {/* GHG6 CL7: пилюли RangePill дублируют confidence-заливку ячейки в
            timeline-режиме (когда cellWidth задан) — заливка сама несёт status
            и уверенность, а пилюля поверх сжимает читаемость на узких ячейках
            (cellWidth=24..120px). Поэтому пилюли рендерятся только в legacy
            StripView (cellWidth=undefined). В timeline-режиме редактирование
            существующего range открывается тапом по самой ячейке —
            см. onCellTap-ветку ниже (CL8). */}
        {!cellWidth && (
          <LayoutGroup id={`row-${user.id}`}>
          <AnimatePresence>
            {ranges.map((r) => {
              const rect = rangeToPillRect(
                new Date(r.starts_at),
                new Date(r.ends_at),
                windowStart,
                windowSpan,
              );
              if (!rect) return null;
              return (
                <RangePill
                  key={r.id}
                  range={r}
                  rect={rect}
                  windowSpan={windowSpan}
                  isOwn={isMe}
                  onTap={() => {
                    if (isMe) {
                      haptic("light");
                      setEditing(r.id);
                    }
                  }}
                />
              );
            })}
          </AnimatePresence>
          </LayoutGroup>
        )}
      </div>
    </div>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function firstName(name: string): string {
  return name.split(/\s+/)[0];
}
