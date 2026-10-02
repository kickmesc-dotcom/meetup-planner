import { useQuery } from "@tanstack/react-query";
import { fetchGuestProfile } from "@/api/game";
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

  const p = q.data;

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
          <div className="truncate text-sm font-semibold">👤 Чужой профиль</div>
          <div className="text-[11px] text-tg-hint">Глазами гостя — только просмотр</div>
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
                label="🎖 Ачивки"
                value={`${p.achievements_collected}/${p.achievements_total}`}
              />
            </section>

            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <div className="text-sm font-semibold">Собранные ачивки</div>
              {p.achievements.length === 0 ? (
                <div className="mt-1 text-xs text-tg-hint">Пока пусто — ни одной ачивки.</div>
              ) : (
                <ul className="mt-2 space-y-1">
                  {p.achievements.map((a) => (
                    <li key={a.code} className="flex items-center gap-2 text-xs text-tg-text">
                      <span className="w-5 shrink-0 text-center text-sm">{a.icon}</span>
                      <span className="min-w-0 truncate">{a.title}</span>
                    </li>
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
