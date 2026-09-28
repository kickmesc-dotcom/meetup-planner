/**
 * GHG10 Э5: игровые поверхности профиля.
 *
 * `GameRankCard` — ранг + шкала/престиж + уведомление о левел-апе + кнопка
 * «за что дают опыт» + история дня. `AchievementsScreen` — лист ачивок и чарты
 * (обладатели ачивок и ранги участников).
 *
 * Рубильник: при `enabled=false` сервер отвечает «пусто», а мы просто не
 * рисуем игровые блоки — остальной профиль работает как раньше.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ackLevelUp,
  fetchAchievementsChart,
  fetchMyGame,
  fetchRanksChart,
  updateGameProfile,
  type GameLevelUp,
  type GameProfile,
} from "@/api/game";
import type { User } from "@/types";
import RankPlaque, { RankBar } from "@/components/RankPlaque";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";

const LIMIT_LABELS: Record<string, string> = {
  day: "раз в день",
  week: "раз в неделю",
  year: "раз в год",
  once: "один раз",
};

export function GameRankCard() {
  const qc = useQueryClient();
  const [showRules, setShowRules] = useState(false);
  const game = useQuery({ queryKey: ["game", "me"], queryFn: fetchMyGame });
  const ack = useMutation({
    mutationFn: ackLevelUp,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["game", "me"] });
    },
    onError: () => haptic("error"),
  });

  if (game.isPending) {
    return (
      <section className="rounded-xl bg-tg-secondary-bg/60 p-4">
        <ListSkeleton rows={2} />
      </section>
    );
  }
  const g = game.data;
  if (!g || !g.enabled || !g.rank) return null;

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-4 space-y-3">
      {g.level_up && (
        <LevelUpNotice
          levelUp={g.level_up}
          onAck={() => ack.mutate()}
          pending={ack.isPending}
        />
      )}

      <header className="flex items-center justify-between gap-2">
        <RankPlaque hex={g.rank.hex} bold={g.rank.bold || g.supreme}>
          {g.supreme ? "🏅 " : ""}
          {g.rank_name}
        </RankPlaque>
        <span className="text-xs text-tg-hint tabular-nums">
          Ур. {g.level}/{g.max_level} · {g.xp} XP
        </span>
      </header>

      {g.at_max ? (
        // Э3.3: на максимуме шкала заменяется счётчиком престижа.
        <div className="flex items-center justify-between rounded-lg bg-tg-bg/50 px-3 py-2">
          <span className="text-sm text-tg-text">✦ Престиж</span>
          <span className="text-lg font-bold tabular-nums text-tg-text">
            {g.prestige}
          </span>
        </div>
      ) : (
        <RankBar
          value={g.xp_into_level}
          total={g.xp_into_level + (g.xp_to_next ?? 0)}
          label={`До ур. ${g.level + 1}`}
        />
      )}

      {g.unlocked.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {g.unlocked.map((f) => (
            <span
              key={f.code}
              className="rounded-md bg-tg-bg/50 px-2 py-0.5 text-[11px] text-tg-hint"
            >
              {f.title}
            </span>
          ))}
        </div>
      )}

      <TodayHistory profile={g} />

      <div>
        <button
          type="button"
          onClick={() => {
            haptic("selection");
            setShowRules((v) => !v);
          }}
          className="min-h-9 rounded-md text-xs text-tg-link"
          aria-expanded={showRules}
        >
          {showRules ? "▾ Скрыть" : "▸ За что дают опыт"}
        </button>
        {showRules && (
          <ul className="mt-1 divide-y divide-tg-bg/40">
            {g.xp_rules.map((r) => (
              <li
                key={r.code}
                className="flex items-center justify-between gap-2 py-1.5 text-xs"
              >
                <span className="min-w-0 truncate text-tg-text">{r.title}</span>
                <span className="shrink-0 text-tg-hint tabular-nums">
                  +{r.points}
                  {r.limit ? ` · ${LIMIT_LABELS[r.limit] ?? r.limit}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <CustomizeSection profile={g} />
    </section>
  );
}

/**
 * GHG10 Э8.5/8.7/10: своё имя (8), своя аватарка (6), своё название ранга (10).
 *
 * Поля показываются ТОЛЬКО когда ранг их открыл (`unlocked`), и отправляются по
 * одному — сервер гейтит каждое отдельно. Локальный стейт переинициализируем из
 * ответа сервера после сохранения.
 */
function CustomizeSection({ profile }: { profile: GameProfile }) {
  const qc = useQueryClient();
  const unlocked = new Set(profile.unlocked.map((f) => f.code));
  const canAvatar = unlocked.has("custom_avatar");
  const canName = unlocked.has("custom_name");
  const canRank = unlocked.has("custom_rank");

  const [name, setName] = useState(profile.custom_name ?? "");
  const [rank, setRank] = useState(profile.custom_rank_title ?? "");
  const [avatar, setAvatar] = useState(profile.avatar_manual_url ?? "");

  const save = useMutation({
    mutationFn: updateGameProfile,
    onSuccess: (out) => {
      haptic("success");
      setName(out.custom_name ?? "");
      setRank(out.custom_rank_title ?? "");
      setAvatar(out.avatar_manual_url ?? "");
      qc.setQueryData(["game", "me"], out);
      // Имя видно и в остальных экранах — обновляем справочники.
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  if (!canAvatar && !canName && !canRank) return null;

  const patch: Parameters<typeof updateGameProfile>[0] = {};
  if (canName && name !== (profile.custom_name ?? "")) patch.custom_name = name;
  if (canRank && rank !== (profile.custom_rank_title ?? ""))
    patch.custom_rank_title = rank;
  if (canAvatar && avatar !== (profile.avatar_manual_url ?? ""))
    patch.avatar_manual_url = avatar;
  const dirty = Object.keys(patch).length > 0;

  return (
    <div className="space-y-2 border-t border-tg-bg/40 pt-3">
      <div className="text-xs font-semibold text-tg-text">🎨 Кастомизация</div>
      {canAvatar && (
        <Field label="Ссылка на аватарку" value={avatar} onChange={setAvatar} placeholder="https://…" />
      )}
      {canName && (
        <Field label="Своё имя в приложении" value={name} onChange={setName} placeholder="Как звать" />
      )}
      {canRank && (
        <Field label="Своё название ранга" value={rank} onChange={setRank} placeholder="Напр. Сигма икона" />
      )}
      <button
        type="button"
        onClick={() => save.mutate(patch)}
        disabled={!dirty || save.isPending}
        className="min-h-9 w-full rounded-md bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
      >
        {save.isPending ? "Сохраняем…" : "Сохранить"}
      </button>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-tg-hint">{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full rounded-lg bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
      />
    </label>
  );
}

/** Э3.2: «какой сейчас ранг, какой был раньше, какие возможности открылись». */
function LevelUpNotice({
  levelUp,
  onAck,
  pending,
}: {
  levelUp: GameLevelUp;
  onAck: () => void;
  pending: boolean;
}) {
  return (
    <div className="rounded-lg border border-tg-button/40 bg-tg-button/10 p-3">
      <div className="text-sm font-semibold text-tg-text">🎉 Новый ранг!</div>
      <div className="mt-1 text-xs text-tg-hint">
        {levelUp.from_rank} → <span className="text-tg-text">{levelUp.to_rank}</span>
      </div>
      {levelUp.unlocked.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {levelUp.unlocked.map((f) => (
            <li key={f.code} className="text-xs text-tg-text">
              • {f.title}
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        onClick={onAck}
        disabled={pending}
        className="mt-2 min-h-9 rounded-md bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
      >
        Понятно
      </button>
    </div>
  );
}

function TodayHistory({ profile }: { profile: GameProfile }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-[11px] text-tg-hint">
        <span>Сегодня</span>
        <span className="tabular-nums">+{profile.today_total} XP</span>
      </div>
      {profile.today.length === 0 ? (
        <div className="mt-1 text-xs text-tg-hint">Пока пусто.</div>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {profile.today.map((e) => (
            <li
              key={e.event}
              className="flex items-center justify-between gap-2 text-xs"
            >
              <span className="min-w-0 truncate text-tg-text">
                {e.title}
                {e.count > 1 ? ` ×${e.count}` : ""}
              </span>
              <span className="shrink-0 tabular-nums text-tg-hint">
                +{e.points}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Э5.2/5.3: лист ачивок + чарты обладателей ачивок и рангов. */
export function AchievementsScreen({ users }: { users: User[] }) {
  const game = useQuery({ queryKey: ["game", "me"], queryFn: fetchMyGame });
  const holders = useQuery({
    queryKey: ["game", "achievements"],
    queryFn: fetchAchievementsChart,
  });
  const ranks = useQuery({ queryKey: ["game", "ranks"], queryFn: fetchRanksChart });
  const byId = Object.fromEntries(users.map((u) => [u.id, u] as const));

  const achievements = game.data?.achievements ?? [];
  const collected = achievements.filter((a) => a.collected).length;

  // Рубильник: экран может открыться по deep link и при выключенной игре —
  // не показываем пустой «реестр» как будто данных нет.
  if (game.data && !game.data.enabled) {
    return (
      <div className="flex-1 grid place-items-center p-6 text-center text-sm text-tg-hint">
        🏅 Игровая система сейчас выключена.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-semibold">🏅 Мои ачивки</h2>
          <span className="text-xs text-tg-hint tabular-nums">
            {collected}/{achievements.length}
          </span>
        </div>
        {game.isPending ? (
          <div className="mt-2">
            <ListSkeleton rows={5} />
          </div>
        ) : (
          <ul className="mt-3 space-y-1">
            {achievements.map((a) => (
              <li
                key={a.code}
                className={[
                  "flex items-start gap-2 rounded-lg px-2 py-1.5",
                  a.collected ? "bg-tg-bg/50" : "opacity-45",
                ].join(" ")}
              >
                <span className="mt-0.5 text-lg shrink-0">{a.icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium text-tg-text truncate">
                      {a.title}
                    </span>
                    <span className="shrink-0 text-[11px] text-tg-hint tabular-nums">
                      {a.collected
                        ? `+${a.points} XP`
                        : progressLabel(a.progress, a.threshold, a.tiers)}
                    </span>
                  </div>
                  <div className="text-[11px] text-tg-hint line-clamp-2">
                    {a.description}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <h2 className="text-base font-semibold">🏆 Обладатели ачивок</h2>
        <div className="text-xs text-tg-hint mb-2">Кто сколько собрал за всё время</div>
        {holders.isPending ? (
          <ListSkeleton rows={4} />
        ) : !holders.data?.length ? (
          <div className="text-xs text-tg-hint py-2">Ачивок пока ни у кого.</div>
        ) : (
          <Chart
            rows={holders.data.map((r) => ({
              user_id: r.user_id,
              value: r.count,
              right: String(r.count),
            }))}
            byId={byId}
            unit="ачивок"
          />
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <h2 className="text-base font-semibold">📈 Ранги участников</h2>
        <div className="text-xs text-tg-hint mb-2">Опыт и ранг каждого</div>
        {ranks.isPending ? (
          <ListSkeleton rows={4} />
        ) : !ranks.data?.length ? (
          <div className="text-xs text-tg-hint py-2">Ещё никто не прокачался.</div>
        ) : (
          <ul className="space-y-1.5">
            {ranks.data.map((r) => {
              const u = byId[r.user_id];
              return (
                <li key={r.user_id} className="flex items-center gap-2">
                  <Avatar user={u} fallback={r.user_id} />
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {u?.display_name ?? `id=${r.user_id}`}
                  </span>
                  <span className="shrink-0 text-[11px] tabular-nums text-tg-hint">
                    {r.xp} XP
                  </span>
                  <RankPlaque hex={r.hex} bold={r.bold || r.supreme}>
                    {r.rank_name}
                  </RankPlaque>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function progressLabel(
  progress: number | null,
  threshold: number | null,
  tiers: number[],
): string {
  if (threshold !== null) return `${progress ?? 0}/${threshold}`;
  if (tiers.length > 0) {
    const next = tiers.find((t) => t > (progress ?? 0));
    const cur = progress ?? 0;
    return next ? `${cur} → ${next}` : `${cur} раз`;
  }
  return "";
}

function Avatar({ user, fallback }: { user?: User; fallback: number }) {
  return (
    <div
      className="flex h-6 w-6 shrink-0 items-center justify-center overflow-hidden rounded-full text-[10px] text-white"
      style={{ background: user?.color_hex ?? "#888" }}
    >
      {user?.avatar_url ? (
        <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
      ) : (
        (user?.display_name[0] ?? String(fallback))
      )}
    </div>
  );
}

/** Простой чарт-бар: заливка строки пропорциональна величине. */
function Chart({
  rows,
  byId,
  unit,
}: {
  rows: { user_id: number; value: number; right: string }[];
  byId: Record<number, User>;
  unit: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ol className="space-y-1.5">
      {rows.map((r) => {
        const u = byId[r.user_id];
        return (
          <li
            key={r.user_id}
            className="relative flex items-center gap-2 overflow-hidden rounded-md px-1.5 py-1"
            title={`${u?.display_name ?? r.user_id}: ${r.value} ${unit}`}
          >
            <span
              aria-hidden
              className="absolute inset-y-0 left-0 bg-tg-hint/10"
              style={{ width: `${(r.value / max) * 100}%` }}
            />
            <Avatar user={u} fallback={r.user_id} />
            <span className="relative min-w-0 flex-1 truncate text-sm">
              {u?.display_name ?? `id=${r.user_id}`}
            </span>
            <span className="relative shrink-0 font-semibold tabular-nums text-tg-text">
              {r.right}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
