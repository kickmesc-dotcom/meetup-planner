/**
 * GHG10 Э5: игровые поверхности профиля.
 *
 * `GameDetails` — уведомление о левел-апе + что открылось + история дня +
 * кнопка «за что дают опыт» + кастомизация. Ранг, аватарка и шкала опыта
 * переехали в карточку персонажа (`ProfileScreen`), чтобы опыт не жил «где-то
 * ниже» отдельным блоком. `AchievementsScreen` — лист ачивок и чарты.
 *
 * Рубильник: при `enabled=false` сервер отвечает «пусто», а мы просто не
 * рисуем игровые блоки — остальной профиль работает как раньше.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ackLevelUp,
  fetchAchievementStats,
  fetchMyGame,
  fetchRanksChart,
  updateGameProfile,
  type GameAchievement,
  type GameLevelUp,
  type GameProfile,
} from "@/api/game";
import type { User } from "@/types";
import RankPlaque from "@/components/RankPlaque";
import ProgressBar from "@/components/ProgressBar";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import { useUI, type Tab } from "@/store/ui";

const FEATURE_TABS: readonly string[] = [
  "feed",
  "calendar",
  "meetings",
  "profile",
  "admin",
];

/**
 * GHG11(4): переход из анонса фичи туда, где её сразу можно применить.
 *
 * Переключаем вкладку мини-аппа и доскроллим до якоря (id DOM-элемента).
 * Якорь может ещё не отрисоваться после смены вкладки — поэтому несколько
 * ретраев с небольшой паузой, потом молча сдаёмся.
 */
function goToFeature(tab?: string, anchor?: string) {
  if (!tab || !FEATURE_TABS.includes(tab)) return;
  haptic("light");
  // Просим целевой экран раскрыть нужный блок (лента — «Действия»).
  useUI.getState().setFeedAnchor(anchor ?? null);
  useUI.getState().setTab(tab as Tab);
  if (!anchor) return;
  // Экран может ещё дорисовываться (раскрытие блока, подгрузка данных) —
  // поэтому водим прокрутку несколько раз, пока элемент не окажется в поле
  // зрения, но не дольше ~2.4с.
  let ticks = 0;
  const scroll = () => {
    ticks += 1;
    const el = document.getElementById(anchor);
    if (el) {
      const r = el.getBoundingClientRect();
      const visible = r.top >= 0 && r.bottom <= window.innerHeight;
      if (!visible) el.scrollIntoView({ behavior: "smooth", block: "center" });
      else if (ticks > 3) return; // уже видно и поздно перескакивать
    }
    if (ticks < 20) window.setTimeout(scroll, 120);
  };
  window.setTimeout(scroll, 80);
}

const LIMIT_LABELS: Record<string, string> = {
  day: "раз в день",
  week: "раз в неделю",
  year: "раз в год",
  once: "один раз",
};

export function GameDetails({ profile }: { profile: GameProfile | undefined }) {
  const qc = useQueryClient();
  const [showRules, setShowRules] = useState(false);
  const ack = useMutation({
    mutationFn: ackLevelUp,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["game", "me"] });
    },
    onError: () => haptic("error"),
  });

  if (!profile) {
    return (
      <section className="rounded-xl bg-tg-secondary-bg/60 p-4">
        <ListSkeleton rows={2} />
      </section>
    );
  }
  const g = profile;
  if (!g.enabled || !g.rank) return null;

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-4 space-y-3">
      {g.level_up && (
        <LevelUpNotice
          levelUp={g.level_up}
          onAck={() => ack.mutate()}
          pending={ack.isPending}
        />
      )}

      {g.unlocked.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] text-tg-hint">Что уже открыто</div>
          <div className="flex flex-wrap gap-1">
            {g.unlocked.map((f) =>
              f.tab ? (
                <button
                  key={f.code}
                  type="button"
                  title={f.description || undefined}
                  onClick={() => goToFeature(f.tab, f.anchor)}
                  className="rounded-md bg-tg-button/10 px-2 py-0.5 text-[11px] text-tg-link active:scale-[0.97]"
                >
                  {f.title} →
                </button>
              ) : (
                <span
                  key={f.code}
                  title={f.description || undefined}
                  className="rounded-md bg-tg-bg/50 px-2 py-0.5 text-[11px] text-tg-hint"
                >
                  {f.title}
                </span>
              ),
            )}
          </div>
          {g.unlocked.some((f) => f.description) && (
            <details className="text-[11px]">
              <summary className="cursor-pointer text-tg-link">
                Что это значит
              </summary>
              <ul className="mt-1 space-y-1.5">
                {g.unlocked
                  .filter((f) => f.description)
                  .map((f) => (
                    <li key={f.code} className="text-tg-hint">
                      <span className="font-medium text-tg-text">{f.title}</span>{" "}
                      — {f.description}
                    </li>
                  ))}
              </ul>
            </details>
          )}
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
    <div id="profile-custom" className="space-y-2 border-t border-tg-bg/40 pt-3">
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
        <ul className="mt-2 space-y-1.5">
          {levelUp.unlocked.map((f) => (
            <li key={f.code} className="text-xs text-tg-text">
              <div className="font-medium">• {f.title}</div>
              {f.description && (
                <div className="mt-0.5 pl-3 text-[11px] text-tg-hint">
                  {f.description}
                </div>
              )}
              {f.tab && (
                <button
                  type="button"
                  onClick={() => goToFeature(f.tab, f.anchor)}
                  className="mt-1 ml-3 rounded-md bg-tg-button/15 px-2 py-0.5 text-[11px] font-medium text-tg-link active:scale-[0.97]"
                >
                  Открыть и применить →
                </button>
              )}
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
  const stats = useQuery({
    queryKey: ["game", "achievements"],
    queryFn: fetchAchievementStats,
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
            собрано {collected}/{achievements.length}
          </span>
        </div>
        {/* Тот же `10/25`, что раньше висел голым числом — теперь с полосой,
            чтобы было ясно: это прогресс коллекции, а не что-то ещё. */}
        {achievements.length > 0 && (
          <ProgressBar
            className="mt-2"
            size="sm"
            value={collected}
            total={achievements.length}
          />
        )}
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
                    <span className="min-w-0 truncate text-sm font-medium text-tg-text">
                      {a.title}
                      <span className="ml-1.5 rounded bg-tg-hint/15 px-1 py-0.5 align-middle text-[10px] font-normal text-tg-hint">
                        {a.tiers.length > 0
                          ? "разовая + юбилеи"
                          : a.kind === "threshold"
                            ? "порог"
                            : "разово"}
                      </span>
                    </span>
                    {a.collected && (
                      <span className="shrink-0 text-[11px] font-medium text-status-free tabular-nums">
                        ✅ +{a.points} XP
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-tg-hint line-clamp-2">
                    {a.description}
                  </div>
                  {/* Разделение «разовая» vs «юбилейные ×N» прямым текстом:
                      для накопителей это ДВЕ разные ачивки, а не «прогресс до 20».
                      Иначе «С почином 18/20» читается как «нужно стать лохом 20 раз». */}
                  {a.tiers.length > 0 ? (
                    <div className="mt-1.5 space-y-1">
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10px] text-tg-hint">
                        <span className="rounded bg-tg-hint/15 px-1 py-0.5">разовая</span>
                        <span className={a.collected ? "text-status-free" : ""}>
                          {a.collected ? "✅ взята" : "▫️ пока нет"}
                        </span>
                        <span>
                          · случаев:{" "}
                          <span className="tabular-nums text-tg-text">
                            {a.progress ?? 0}
                          </span>
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10px] text-tg-hint">
                        <span>юбилейные:</span>
                        {a.tiers.map((t) => {
                          const got = (a.collected_tiers ?? []).includes(t);
                          return (
                            <span key={t} className={got ? "text-status-free" : ""}>
                              ×{t} {got ? "✅" : "▫️"}
                            </span>
                          );
                        })}
                      </div>
                      {achievementProgress(a) && (
                        <ProgressBar
                          size="sm"
                          tone="muted"
                          {...achievementProgress(a)!}
                        />
                      )}
                    </div>
                  ) : achievementProgress(a) ? (
                    <ProgressBar
                      className="mt-1.5"
                      size="sm"
                      tone="muted"
                      {...achievementProgress(a)!}
                    />
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Вместо списка имён «кто сколько собрал» — сводка «сколько % участников
          имеют такую»: имена для этой задачи не нужны, а сравнимость лучше. */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <h2 className="text-base font-semibold">🏆 Редкость ачивок</h2>
        <div className="text-xs text-tg-hint mb-2">Сколько % участников её имеют</div>
        {stats.isPending ? (
          <ListSkeleton rows={4} />
        ) : !stats.data?.length ? (
          <div className="text-xs text-tg-hint py-2">Игровая система сейчас выключена.</div>
        ) : (
          <ul className="space-y-1.5">
            {[...stats.data]
              .sort(
                (a, b) =>
                  b.percent - a.percent || a.title.localeCompare(b.title),
              )
              .map((s) => (
                <li key={s.code} className="flex items-center gap-2">
                  <span className="shrink-0 text-base">{s.icon}</span>
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {s.title}
                  </span>
                  <span className="shrink-0 text-xs font-medium tabular-nums text-tg-text">
                    {s.percent}%
                  </span>
                  <span className="w-10 shrink-0 text-right text-[11px] tabular-nums text-tg-hint">
                    {s.holders}/{s.total}
                  </span>
                </li>
              ))}
          </ul>
        )}
      </section>

      {/* GHG11: праздники переехали в админку («Настройки») — из профиля убраны. */}

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

/** Ближайший непройденный юбилей (10/20/30/50/100). */
function nextTier(progress: number, tiers: number[]): number | null {
  return tiers.find((t) => t > progress) ?? null;
}

/**
 * Прогресс ачивки в виде отношения, а не текста.
 *
 * Раньше тут жила строка «12 → 25», где левое число — счётчик, правое — юбилей:
 * по виду не отличить от дроби и совсем не понятно, что это прогресс. Теперь
 * всегда отношение `X/Y` с полосой, а смысл `Y` вынесен в подпись.
 *
 * `null` — у ачивки нет измеримого прогресса (разовые: «самострел», «кэшбэк»).
 */
function achievementProgress(a: GameAchievement): {
  value: number;
  total: number;
  label: string;
} | null {
  const progress = a.progress ?? 0;
  if (a.threshold !== null && a.threshold > 0) {
    return {
      value: Math.min(progress, a.threshold),
      total: a.threshold,
      label: "прогресс",
    };
  }
  if (a.tiers.length > 0) {
    // Вторая сущность той же ачивки: базовая берётся за первый раз, а каждая
    // строка ниже — ОТДЕЛЬНАЯ ачивка-юбилей. Подпись говорит это прямым
    // текстом, иначе «С почином 18/20» читается как «нужно 20 раз».
    const tier = nextTier(progress, a.tiers);
    if (tier === null) return null;
    return {
      value: Math.min(progress, tier),
      total: tier,
      label: `до юбилея ×${tier}`,
    };
  }
  return null;
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

