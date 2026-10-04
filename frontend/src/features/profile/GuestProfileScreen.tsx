import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchGuestProfile,
  fetchMyGame,
  type GuestAchievement,
  type GuestTitleEvent,
} from "@/api/game";
import RankPlaque from "@/components/RankPlaque";
import { Spinner } from "@/components/Spinner";
import ErrorState from "@/components/ErrorState";
import { haptic } from "@/tg/webapp";

/**
 * Э19: чужой профиль «глазами гостя».
 *
 * Открывается кликом по аватарке участника на календаре. Здесь НЕТ ни настроек,
 * ни пояснений «куда зайти» — только факты: ранг, XP, сколько раз был лохом/
 * чуханом, место в чарте и собранные ачивки. Свой профиль (с редактированием и
 * справкой) остаётся на вкладке «Профиль».
 */
export default function GuestProfileScreen({
  userId,
  onClose,
}: {
  userId: number;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["guest-profile", userId],
    queryFn: () => fetchGuestProfile(userId),
  });
  // GHG11(3): свой процент открытых ачивок — чтобы сравнить в профиле гостя.
  const myQ = useQuery({
    queryKey: ["me-game"],
    queryFn: fetchMyGame,
    staleTime: 5 * 60 * 1000,
  });

  const p = q.data;
  const myPercent = (() => {
    const items = myQ.data?.achievements;
    if (!items || items.length === 0) return null;
    return Math.round((items.filter((a) => a.collected).length * 100) / items.length);
  })();

  return (
    <div className="absolute inset-0 z-40 flex flex-col bg-tg-bg">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2.5">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          aria-label="Закрыть профиль"
          className="rounded-lg bg-tg-secondary-bg/70 px-2.5 py-1.5 text-sm font-medium text-tg-text active:scale-[0.98]"
        >
          ← Назад
        </button>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">
            👤 {p?.name ? `Профиль участника ${p.name}` : "Профиль участника"}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-3">
        {q.isPending && (
          <div className="mt-4 flex items-center gap-2 text-sm text-tg-hint">
            <Spinner size={14} /> Считаем…
          </div>
        )}
        {q.isError && (
          <ErrorState error={q.error} onRetry={() => q.refetch()} title="Не удалось открыть профиль" />
        )}

        {p && !p.enabled && (
          <section className="rounded-xl bg-tg-secondary-bg/60 p-3 text-sm text-tg-hint">
            Игровая система сейчас выключена — профиль показывать нечего.
          </section>
        )}

        {p && p.enabled && (
          <div className="space-y-3">
            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full text-base font-medium text-white"
                  style={{ background: p.rank?.hex ?? "#6b7280" }}
                >
                  {p.avatar_url ? (
                    <img src={p.avatar_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    initials(p.name)
                  )}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-base font-semibold">{p.name}</div>
                  {p.rank && (
                    <div className="mt-0.5">
                      <RankPlaque hex={p.rank.hex} bold={p.rank.bold}>
                        {p.rank_name || p.rank.name}
                      </RankPlaque>
                    </div>
                  )}
                </div>
              </div>
              <div className="mt-2 text-xs text-tg-hint">
                Ур. {p.level} · {p.xp} XP
                {p.prestige > 0 ? ` · престиж ${p.prestige}` : ""}
              </div>
              {/* GHG11: сегодняшние звания с причинами — плашка над головой. */}
              {p.today && (p.today.loser || p.today.chukhan || p.today.worm) && (
                <div className="mt-2 space-y-0.5 text-[11px] text-tg-text">
                  {p.today.loser && (
                    <div>
                      👑 Сегодня лох дня
                      {p.today.loser_reason ? `: «${p.today.loser_reason}»` : ""}
                    </div>
                  )}
                  {p.today.chukhan && (
                    <div>
                      💩 Чухан недели
                      {p.today.chukhan_reason ? `: «${p.today.chukhan_reason}»` : ""}
                    </div>
                  )}
                  {p.today.worm && <div>🪱 Сейчас червь-пидор</div>}
                </div>
              )}
            </section>

            <section className="grid grid-cols-2 gap-2">
              <Stat label="🤡 Лох дня" value={`×${p.loser_count}`} />
              <Stat label="💩 Чухан недели" value={`×${p.chukhan_count}`} />
              <Stat
                label="🏆 Место в чарте"
                value={
                  p.rank_position != null && p.ranks_total > 0
                    ? `#${p.rank_position} из ${p.ranks_total}`
                    : "—"
                }
              />
              <Stat
                label="🪱 Держал червя"
                value={p.worm_total_days > 0 ? `${p.worm_total_days} дн.` : "—"}
              />
            </section>

            {/* GHG11(3): процент открытых ачивок + сравнение со своими. */}
            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">📊 Открыто ачивок</div>
                <div className="text-sm font-semibold tabular-nums text-tg-text">
                  {p.achievements_percent}%
                </div>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-tg-bg/70">
                <div
                  className="h-full rounded-full bg-tg-link"
                  style={{ width: `${Math.min(100, p.achievements_percent)}%` }}
                />
              </div>
              <div className="mt-1 text-[11px] text-tg-hint">
                {p.achievements_collected}/{p.achievements_total} ачивок
                {myPercent != null &&
                  ` · у тебя ${myPercent}% — ${
                    p.achievements_percent > myPercent
                      ? `${p.name} впереди`
                      : p.achievements_percent < myPercent
                        ? "ты впереди"
                        : "наравне"
                  }`}
              </div>
            </section>

            <TitleHistory
              title="🤡 История «лоха дня»"
              empty="Ни разу не был лохом дня."
              events={p.loser_history}
            />
            <TitleHistory
              title="💩 История «чухана недели»"
              empty="Ни разу не был чуханом недели."
              events={p.chukhan_history}
            />

            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <div className="text-sm font-semibold">Последние ачивки</div>
              {p.achievements.length === 0 ? (
                <div className="mt-1 text-xs text-tg-hint">Пока пусто — ни одной ачивки.</div>
              ) : (
                <ul className="mt-2 space-y-1">
                  {p.achievements.slice(0, 12).map((a) => (
                    <GuestAchievementRow key={a.code} a={a} />
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

/** GHG11(3): история звания — когда и за что. */
function TitleHistory({
  title,
  empty,
  events,
}: {
  title: string;
  empty: string;
  events: GuestTitleEvent[];
}) {
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="text-sm font-semibold">{title}</div>
      {events.length === 0 ? (
        <div className="mt-1 text-xs text-tg-hint">{empty}</div>
      ) : (
        <ul className="mt-2 space-y-1">
          {events.map((e, i) => (
            <li key={`${e.at}-${i}`} className="text-xs text-tg-text">
              <span className="text-tg-hint">{formatDate(e.at)}</span>
              {e.reason ? ` — «${e.reason}»` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** GHG11(3): ачивка гостя — по тапу раскрываются «когда» и «за что». */
function GuestAchievementRow({ a }: { a: GuestAchievement }) {
  const [open, setOpen] = useState(false);
  return (
    <li
      onClick={() => {
        haptic("light");
        setOpen((v) => !v);
      }}
      className="cursor-pointer rounded-lg bg-tg-bg/40 px-2 py-1.5"
    >
      <div className="flex items-center gap-2 text-xs text-tg-text">
        <span className="w-5 shrink-0 text-center text-sm">{a.icon}</span>
        <span className="min-w-0 flex-1 truncate">{a.title}</span>
        <span className="shrink-0 text-tg-hint">{open ? "▾" : "▸"}</span>
      </div>
      {open && (
        <div className="mt-1 space-y-0.5 pl-7 text-[11px] text-tg-hint">
          {a.description && <div>За что: {a.description}</div>}
          {a.unlocked_at && <div>Когда: {formatDate(a.unlocked_at)}</div>}
          {typeof a.points === "number" && a.points > 0 && (
            <div>Награда: +{a.points} XP</div>
          )}
        </div>
      )}
    </li>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-tg-secondary-bg/60 px-3 py-2">
      <div className="text-[10px] text-tg-hint">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-tg-text">{value}</div>
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
