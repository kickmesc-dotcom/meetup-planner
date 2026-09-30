/**
 * GHG10 Э5.5: экран игровой системы в админке.
 *
 * Зачем он нужен: рубильник `game.enabled` до этого жил только в БД, а проверить
 * новый ранг/ачивку можно было лишь SQL'ем. Здесь три вещи:
 *
 * 1. рубильник + список отладочных TG-id (кому гейтинг не указ);
 * 2. карточка игрока: ранг, опыт, собранные ачивки и накопители;
 * 3. отладка — ручная выдача ачивки, сброс (в т.ч. накопителей) и установка
 *    опыта абсолютным числом («поставь 800» → проверь иммунитет 9 ранга).
 *
 * Гейтинга по рангам тут нет: админ — это админ. Ручной опыт НЕ выставляет
 * уведомление о левел-апе, поэтому отладка не всплывает у игрока в профиле.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchGameAdmin,
  fetchGameMusic,
  fetchGamePlayer,
  fetchGameSocial,
  flushGameDigest,
  grantGameAchievement,
  removeMusicTrack,
  resetGameAchievements,
  setGamePlayerXp,
  updateGameAdmin,
  updateGameMusic,
  updateGameSocial,
  type GameContrabandWord,
  type GamePlayerState,
} from "@/api/admin";
import type { User } from "@/types";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { humanizeApiError, isEndpointMissing } from "@/api/client";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

interface Props {
  users: User[];
  onBack: () => void;
}

const QUERY_KEY = ["admin", "game"] as const;
const SOCIAL_KEY = ["admin", "game", "social"] as const;

/** Ползунок-тумблер: одинаковый во всех четырёх блоках Э13. */
function Toggle({
  label,
  hint,
  on,
  busy,
  onClick,
}: {
  label: string;
  hint: string;
  on: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="text-sm font-semibold">{label}</div>
        <div className="text-[11px] text-tg-hint">{hint}</div>
      </div>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className={[
          "shrink-0 rounded-lg px-3 py-2 text-sm font-medium active:scale-[0.98] disabled:opacity-60",
          on ? "bg-status-busy/20 text-status-busy" : "bg-tg-button text-tg-button-text",
        ].join(" ")}
      >
        {busy ? "…" : on ? "Выключить" : "Включить"}
      </button>
    </div>
  );
}

/** Числовое поле с черновиком: сохраняется кнопкой «Сохранить», а не на каждый символ. */
function NumberRow({
  label,
  value,
  onSave,
  busy,
}: {
  label: string;
  value: number;
  onSave: (next: number) => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? String(value);
  return (
    <div className="flex gap-2">
      <input
        value={shown}
        onChange={(e) => setDraft(e.target.value.replace(/\D/g, "").slice(0, 4))}
        inputMode="numeric"
        placeholder={label}
        className="min-w-0 flex-1 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
      />
      <button
        type="button"
        onClick={() => {
          onSave(Number(shown));
          setDraft(null);
        }}
        disabled={draft === null || busy}
        className="shrink-0 rounded-lg bg-tg-secondary-bg px-3 py-2 text-xs font-medium disabled:opacity-60"
      >
        Сохранить
      </button>
    </div>
  );
}

/**
 * Фраза → регэксп-вариант для «ловим любые формулировки».
 *
 * Спецсимволы экранируем, а пробелы делаем гибкими (`\s+`), чтобы «я ебал»
 * ловилось и как «я   ебал». Хвост `\w*` — «я ебала/ебал-то» тоже попадают.
 */
function phraseToVariant(phrase: string): string {
  const escaped = phrase
    .trim()
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return `\\b${escaped.replace(/\s+/g, "\\s+")}\\w*`;
}

export default function GameScreen({ users, onBack }: Props) {
  const queryClient = useQueryClient();
  const state = useQuery({ queryKey: QUERY_KEY, queryFn: fetchGameAdmin });
  const social = useQuery({ queryKey: SOCIAL_KEY, queryFn: fetchGameSocial });
  const [selected, setSelected] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [xpDraft, setXpDraft] = useState("");
  const [debugDraft, setDebugDraft] = useState<string | null>(null);
  // Реестр слов правим локально и отправляем целиком: он заменяется, а не мержится.
  const [wordsDraft, setWordsDraft] = useState<GameContrabandWord[] | null>(null);
  // Черновики «добавить фразу», по одному на участника (ключ — tg-id).
  const [phraseDraft, setPhraseDraft] = useState<Record<string, string>>({});
  const words = wordsDraft ?? social.data?.contraband_words ?? [];

  // Группируем реестр ПО УЧАСТНИКАМ: править фразы удобнее рядом с их владельцем,
  // а не в общем списке, где непонятно, чьи они.
  const wordGroups = (() => {
    const groups = new Map<
      string,
      { key: string; telegramId: number | null; items: { word: GameContrabandWord; idx: number }[] }
    >();
    words.forEach((w, idx) => {
      const key = w.owner_tg_id != null ? String(w.owner_tg_id) : "__none__";
      const group =
        groups.get(key) ?? { key, telegramId: w.owner_tg_id ?? null, items: [] };
      group.items.push({ word: w, idx });
      groups.set(key, group);
    });
    return [...groups.values()];
  })();

  const ownerName = (telegramId: number | null) =>
    users.find((u) => u.telegram_id === telegramId)?.display_name ??
    (telegramId == null ? "— без владельца —" : `tg=${telegramId}`);

  const addPhrase = (telegramId: number | null, key: string) => {
    const text = (phraseDraft[key] ?? "").trim();
    if (!text) return;
    haptic("selection");
    setWordsDraft([
      ...words,
      {
        word: text,
        owner: telegramId != null ? ownerName(telegramId) : null,
        owner_tg_id: telegramId,
        variants: [phraseToVariant(text)],
        labels: [text],
        xp: 5,
        note: null,
        enabled: true,
        chance: null,
      },
    ]);
    setPhraseDraft((draft) => ({ ...draft, [key]: "" }));
  };

  const player = useQuery({
    queryKey: ["admin", "game", "player", selected],
    queryFn: () => fetchGamePlayer(selected as number),
    enabled: selected !== null,
  });

  const refreshPlayer = (data: GamePlayerState) => {
    queryClient.setQueryData(["admin", "game", "player", selected], data);
  };

  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) => updateGameAdmin({ enabled }),
    onSuccess: () => {
      haptic("success");
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const debugMut = useMutation({
    mutationFn: (ids: number[]) => updateGameAdmin({ enabled: true, debug_tg_ids: ids }),
    onSuccess: () => {
      haptic("success");
      setDebugDraft(null);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const grantMut = useMutation({
    mutationFn: () =>
      grantGameAchievement(selected as number, code.trim()),
    onSuccess: (data) => {
      haptic("success");
      setCode("");
      refreshPlayer(data);
      void showAlert(`Выдал: ${data.achievements.length} ачивок у игрока.`);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const resetMut = useMutation({
    mutationFn: (opts: { code?: string; counters?: boolean }) =>
      resetGameAchievements(
        selected as number,
        opts.code ? { code: opts.code, counters: opts.counters } : opts,
      ),
    onSuccess: (data) => {
      haptic("success");
      refreshPlayer(data);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const xpMut = useMutation({
    mutationFn: () => setGamePlayerXp(selected as number, Number(xpDraft)),
    onSuccess: (data) => {
      haptic("success");
      setXpDraft("");
      refreshPlayer(data);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const socialMut = useMutation({
    mutationFn: updateGameSocial,
    onSuccess: (data) => {
      haptic("success");
      queryClient.setQueryData(SOCIAL_KEY, data);
      setWordsDraft(null);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const flushMut = useMutation({
    mutationFn: flushGameDigest,
    onSuccess: (data) => {
      haptic("success");
      void showAlert(
        data.sent > 0 ? `Улетело в чат записей: ${data.sent}` : "В журнале пусто",
      );
      void queryClient.invalidateQueries({ queryKey: SOCIAL_KEY });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const onToggle = async () => {
    if (!state.data || toggleMut.isPending) return;
    haptic("selection");
    const next = !state.data.enabled;
    const ok = await showConfirm(
      next
        ? "Включить игровую систему? Пойдут начисления опыта, ачивки и гейтинг по рангам."
        : "Выключить игровую систему? Опыт и ачивки перестанут начисляться, гейтинг по рангам снимется.",
    );
    if (!ok) return;
    toggleMut.mutate(next);
  };

  const onResetAll = async () => {
    haptic("selection");
    const ok = await showConfirm(
      "Сбросить ВСЕ ачивки игрока (и накопители)? Опыт останется как есть.",
    );
    if (!ok) return;
    resetMut.mutate({ counters: true });
  };

  const debugIds = state.data?.debug_tg_ids ?? [];

  // GHG10-ops: экран приехал во фронте раньше, чем ручка на живом бэкенде.
  // Без этой ветки UI показывал бы «игра выключена, 0 профилей» — то есть
  // выглядел бы как работоспособный, но врал бы.
  if (state.isError && isEndpointMissing(state.error)) {
    return (
      <SubScreen title="🎮 Игровая система" subtitle="Рубильник, ачивки, отладка" onBack={onBack}>
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
          <div className="text-sm font-semibold">Сервер ещё не обновился</div>
          <div className="text-[12px] text-tg-hint">
            Живая сборка бэкенда пока не знает ручку /api/admin/game — этот экран
            включится сам, как только сервер пересоберётся. Чинить вручную нечего.
          </div>
        </section>
      </SubScreen>
    );
  }

  return (
    <SubScreen title="🎮 Игровая система" subtitle="Рубильник, ачивки, отладка" onBack={onBack}>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm font-semibold">Рубильник</div>
            <div className="text-[11px] text-tg-hint">
              Выключенный модуль молчит целиком: ни опыта, ни ачивок, ни гейтинга
            </div>
          </div>
          <button
            type="button"
            onClick={() => void onToggle()}
            disabled={state.isPending || toggleMut.isPending}
            className={[
              "shrink-0 rounded-lg px-3 py-2 text-sm font-medium active:scale-[0.98] disabled:opacity-60",
              state.data?.enabled
                ? "bg-status-busy/20 text-status-busy"
                : "bg-tg-button text-tg-button-text",
            ].join(" ")}
          >
            {toggleMut.isPending ? "…" : state.data?.enabled ? "Выключить" : "Включить"}
          </button>
        </div>
        <div className="text-[11px] text-tg-hint">
          Сейчас: {state.data?.enabled ? "включена" : "выключена"} ·{" "}
          {state.data?.players ?? 0} профилей · ачивок в каталоге:{" "}
          {state.data?.achievements_total ?? 0} · максимум {state.data?.max_level ?? 10} рангов
        </div>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-sm font-semibold">Отладочные TG-id</div>
        <div className="text-[11px] text-tg-hint">
          Им ранговый гейтинг не указ (по умолчанию добавь свой id, иначе
          проверять новые функции придётся с 1 ранга)
        </div>
        <input
          value={debugDraft ?? debugIds.join(", ")}
          onChange={(e) => setDebugDraft(e.target.value)}
          placeholder="123456, 789012"
          inputMode="numeric"
          className="w-full rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
        />
        <button
          type="button"
          onClick={() => {
            haptic("selection");
            const ids = (debugDraft ?? debugIds.join(", "))
              .split(/[,\s]+/)
              .map((s) => s.trim())
              .filter(Boolean)
              .map(Number)
              .filter((n) => Number.isFinite(n));
            debugMut.mutate(ids);
          }}
          disabled={debugDraft === null || debugMut.isPending}
          className="w-full rounded-lg bg-tg-button px-3 py-2 text-sm font-medium text-tg-button-text active:scale-[0.98] disabled:opacity-60"
        >
          Сохранить список
        </button>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-sm font-semibold">Отладка игрока</div>
        <select
          value={selected ?? ""}
          onChange={(e) => {
            haptic("selection");
            setSelected(e.target.value ? Number(e.target.value) : null);
          }}
          className="w-full rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
        >
          <option value="">— выбери участника —</option>
          {users.map((u) => (
            <option key={u.id} value={u.telegram_id}>
              {u.display_name}
            </option>
          ))}
        </select>

        {player.isPending && selected !== null && (
          <div className="text-xs text-tg-hint">
            <Spinner size={12} /> Считаем…
          </div>
        )}

        {player.data && (
          <>
            <div className="rounded-lg bg-tg-bg/50 p-2 text-xs">
              <div className="text-sm font-medium">
                {player.data.name} — {player.data.level}-й «{player.data.rank_name}»
              </div>
              <div className="text-tg-hint">
                {player.data.xp} XP
                {player.data.prestige > 0 ? ` · престиж ${player.data.prestige}` : ""} ·
                ачивок: {player.data.achievements.length}
              </div>
              {Object.keys(player.data.counters).length > 0 && (
                <div className="text-tg-hint">
                  накопители:{" "}
                  {Object.entries(player.data.counters)
                    .map(([k, v]) => `${k}=${v}`)
                    .join(", ")}
                </div>
              )}
              {player.data.achievements.length > 0 && (
                <div className="mt-1 break-words text-tg-hint">
                  {player.data.achievements.join(", ")}
                </div>
              )}
            </div>

            <div className="flex gap-2">
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="код ачивки (chin_up)"
                className="min-w-0 flex-1 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
              />
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  grantMut.mutate();
                }}
                disabled={!code.trim() || grantMut.isPending}
                className="shrink-0 rounded-lg bg-tg-button px-3 py-2 text-xs font-medium text-tg-button-text disabled:opacity-60"
              >
                Выдать
              </button>
            </div>

            <div className="flex gap-2">
              <input
                value={xpDraft}
                onChange={(e) => setXpDraft(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                placeholder="XP всего (напр. 800)"
                className="min-w-0 flex-1 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
              />
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  xpMut.mutate();
                }}
                disabled={!xpDraft.trim() || xpMut.isPending}
                className="shrink-0 rounded-lg bg-tg-secondary-bg px-3 py-2 text-xs font-medium disabled:opacity-60"
              >
                Поставить
              </button>
            </div>

            <button
              type="button"
              onClick={() => void onResetAll()}
              disabled={resetMut.isPending}
              className="w-full rounded-lg bg-status-busy/15 px-3 py-2 text-xs font-medium text-status-busy active:scale-[0.98] disabled:opacity-60"
            >
              🧹 Сбросить ачивки и накопители
            </button>
          </>
        )}
      </section>

      {/* GHG10 Э13: четыре социальные фичи. Задание просило выключаемость и
          «процент срабатываний» — здесь и то, и другое, без похода в SQL. */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-sm font-semibold">📣 Социальные фичи</div>
        <div className="text-[11px] text-tg-hint">
          Всё это пишет в чат само. Сводка — противоядие от спама: вместо
          отдельных сообщений бот копит события в журнал и вываливает пачкой.
        </div>

        {social.isError && isEndpointMissing(social.error) && (
          <div className="text-[12px] text-tg-hint">
            Сервер ещё не знает ручку /api/admin/game/social — обновится сам после
            пересборки бэкенда.
          </div>
        )}

        {social.data && (
          <>
            <div className="space-y-2 rounded-lg bg-tg-bg/40 p-2">
              <Toggle
                label="Режим сводки"
                hint={
                  social.data.digest_enabled
                    ? `Копится в журнал: ${social.data.digest_pending} записей`
                    : "Сейчас бот пишет про ачивки сразу"
                }
                on={social.data.digest_enabled}
                busy={socialMut.isPending}
                onClick={() => {
                  haptic("selection");
                  socialMut.mutate({ digest_enabled: !social.data?.digest_enabled });
                }}
              />
              <div className="flex flex-wrap gap-1">
                {[1, 6, 12, 24].map((hours) => (
                  <button
                    key={hours}
                    type="button"
                    onClick={() => {
                      haptic("selection");
                      socialMut.mutate({ digest_interval_hours: hours });
                    }}
                    disabled={socialMut.isPending}
                    className={[
                      "rounded-lg px-2.5 py-1 text-xs font-medium disabled:opacity-60",
                      social.data?.digest_interval_hours === hours
                        ? "bg-tg-button text-tg-button-text"
                        : "bg-tg-secondary-bg/80 text-tg-text",
                    ].join(" ")}
                  >
                    раз в {hours} ч
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  flushMut.mutate();
                }}
                disabled={flushMut.isPending}
                className="w-full rounded-lg bg-tg-secondary-bg px-3 py-2 text-xs font-medium disabled:opacity-60"
              >
                Отправить сводку сейчас
              </button>
            </div>

            <div className="space-y-2 rounded-lg bg-tg-bg/40 p-2">
              <Toggle
                label="Поминовения"
                hint="Молчишь N дней — бот поминает; вернёшься — «ОН ЗДЕСЬ»"
                on={social.data.memorial_enabled}
                busy={socialMut.isPending}
                onClick={() => {
                  haptic("selection");
                  socialMut.mutate({ memorial_enabled: !social.data?.memorial_enabled });
                }}
              />
              <NumberRow
                label="дней тишины"
                value={social.data.memorial_silence_days}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ memorial_silence_days: n || 1 })}
              />
              <div className="text-[11px] text-tg-hint">
                первое число — порог тишины в днях (21 = «3 недели»), второе —
                как часто повторять поминовение
              </div>
              <NumberRow
                label="дней между повторами"
                value={social.data.memorial_repeat_days}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ memorial_repeat_days: n || 1 })}
              />
            </div>

            <div className="space-y-2 rounded-lg bg-tg-bg/40 p-2">
              <Toggle
                label="Случайные события"
                hint={`Ждут ответа сейчас: ${social.data.events_open}. Первый ответивший забирает XP`}
                on={social.data.events_enabled}
                busy={socialMut.isPending}
                onClick={() => {
                  haptic("selection");
                  socialMut.mutate({ events_enabled: !social.data?.events_enabled });
                }}
              />
              <div className="text-[11px] text-tg-hint">
                вероятность выпадения, потолок в сутки и пауза между событиями
              </div>
              <NumberRow
                label="вероятность, %"
                value={social.data.events_chance_percent}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ events_chance_percent: Math.min(100, n) })}
              />
              <NumberRow
                label="событий в сутки"
                value={social.data.events_max_per_day}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ events_max_per_day: n })}
              />
              <NumberRow
                label="пауза, часов"
                value={social.data.events_min_gap_hours}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ events_min_gap_hours: n })}
              />
            </div>

            <div className="space-y-2 rounded-lg bg-tg-bg/40 p-2">
              <Toggle
                label="Контрабанда слов"
                hint="Опыт за кодовое слово уходит ВЛАДЕЛЬЦУ слова, не тому, кто написал"
                on={social.data.contraband_enabled}
                busy={socialMut.isPending}
                onClick={() => {
                  haptic("selection");
                  socialMut.mutate({ contraband_enabled: !social.data?.contraband_enabled });
                }}
              />
              <div className="text-[11px] text-tg-hint">
                вероятность срабатывания и потолок срабатываний в сутки на слово
              </div>
              <NumberRow
                label="вероятность, %"
                value={social.data.contraband_chance_percent}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ contraband_chance_percent: Math.min(100, n) })}
              />
              <NumberRow
                label="срабатываний в сутки"
                value={social.data.contraband_daily_cap}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ contraband_daily_cap: n })}
              />

              {social.data.unresolved_owners.length > 0 && (
                <div className="rounded bg-status-busy/15 p-2 text-[11px] text-status-busy">
                  Некому начислять: {social.data.unresolved_owners.join(", ")} — выбери
                  владельца из участников, иначе слово молчит
                </div>
              )}

              <div className="space-y-2">
                {wordGroups.map((group) => (
                  <div key={group.key} className="rounded bg-tg-bg/50 p-2 space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-xs font-semibold">
                        {ownerName(group.telegramId)}
                      </span>
                      <span className="shrink-0 text-[11px] text-tg-hint tabular-nums">
                        фраз: {group.items.length}
                      </span>
                    </div>
                    {group.items.map(({ word: w, idx }) => (
                      <div key={`${w.word}-${idx}`} className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-xs">
                            «{w.word}»
                          </span>
                          <input
                            type="number"
                            value={w.xp}
                            onChange={(e) =>
                              setWordsDraft(
                                words.map((it, i) =>
                                  i === idx
                                    ? { ...it, xp: Math.max(0, Number(e.target.value) || 0) }
                                    : it,
                                ),
                              )
                            }
                            className="w-12 rounded bg-tg-bg/60 px-1 py-0.5 text-right text-[11px] tabular-nums text-tg-text"
                            aria-label="XP за фразу"
                          />
                          <button
                            type="button"
                            onClick={() =>
                              setWordsDraft(
                                words.map((it, i) =>
                                  i === idx ? { ...it, enabled: !it.enabled } : it,
                                ),
                              )
                            }
                            className={[
                              "rounded px-2 py-0.5 text-[11px] font-medium",
                              w.enabled ? "bg-status-free/20" : "bg-tg-secondary-bg/80",
                            ].join(" ")}
                          >
                            {w.enabled ? "в игре" : "выкл"}
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setWordsDraft(words.filter((_, i) => i !== idx))
                            }
                            className="rounded bg-status-busy/15 px-2 py-0.5 text-[11px] text-status-busy"
                            aria-label="Удалить фразу"
                          >
                            ×
                          </button>
                        </div>
                        <select
                          value={w.owner_tg_id ?? ""}
                          onChange={(e) =>
                            setWordsDraft(
                              words.map((it, i) =>
                                i === idx
                                  ? {
                                      ...it,
                                      owner_tg_id: e.target.value
                                        ? Number(e.target.value)
                                        : null,
                                      owner: e.target.value
                                        ? ownerName(Number(e.target.value))
                                        : null,
                                    }
                                  : it,
                              ),
                            )
                          }
                          className="w-full rounded bg-tg-bg/60 px-2 py-1 text-[11px] text-tg-text"
                        >
                          <option value="">— без владельца —</option>
                          {users.map((u) => (
                            <option key={u.id} value={u.telegram_id}>
                              {u.display_name}
                            </option>
                          ))}
                        </select>
                      </div>
                    ))}
                    <div className="flex gap-1 pt-1">
                      <input
                        value={phraseDraft[group.key] ?? ""}
                        onChange={(e) =>
                          setPhraseDraft((draft) => ({
                            ...draft,
                            [group.key]: e.target.value,
                          }))
                        }
                        placeholder="новая фраза"
                        className="min-w-0 flex-1 rounded bg-tg-bg/60 px-2 py-1 text-xs text-tg-text"
                      />
                      <button
                        type="button"
                        onClick={() => addPhrase(group.telegramId, group.key)}
                        disabled={!(phraseDraft[group.key] ?? "").trim()}
                        className="rounded-lg bg-tg-secondary-bg px-3 py-1 text-xs font-medium text-tg-text active:scale-[0.98] disabled:opacity-60"
                      >
                        + фраза
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  socialMut.mutate({ contraband_words: words });
                }}
                disabled={wordsDraft === null || socialMut.isPending}
                className="w-full rounded-lg bg-tg-button px-3 py-2 text-xs font-medium text-tg-button-text active:scale-[0.98] disabled:opacity-60"
              >
                Сохранить реестр слов
                {social.data.contraband_custom_registry ? "" : " (сейчас действуют дефолты)"}
              </button>
            </div>

            {/* Э14: голосовые задания. Опрос по умолчанию выключен (по заданию). */}
            <div className="space-y-2 rounded-lg bg-tg-bg/40 p-2">
              <Toggle
                label="Голосовые задания"
                hint="Бот ставит творческую задачу; ответ — голосовым реплаем или боту в личку"
                on={social.data.voice_enabled}
                busy={socialMut.isPending}
                onClick={() => {
                  haptic("selection");
                  socialMut.mutate({ voice_enabled: !social.data?.voice_enabled });
                }}
              />
              <Toggle
                label="Опрос «чей вариант лучше»"
                hint="После сводки бот ставит опрос, победитель забирает бонусный XP"
                on={social.data.voice_poll_enabled}
                busy={socialMut.isPending}
                onClick={() => {
                  haptic("selection");
                  socialMut.mutate({ voice_poll_enabled: !social.data?.voice_poll_enabled });
                }}
              />
              <NumberRow
                label="пауза между заданиями, ч"
                value={social.data.voice_min_gap_hours}
                busy={socialMut.isPending}
                onSave={(n) => socialMut.mutate({ voice_min_gap_hours: Math.max(1, n) })}
              />
              <div className="text-[11px] text-tg-hint">
                Открытых заданий сейчас: {social.data.voice_open}. Задания ставятся
                только днём (10:00–20:00 по времени чата), окно сбора — часы.
              </div>
            </div>
          </>
        )}
      </section>

      <MusicSection users={users} />
    </SubScreen>
  );
}

const MUSIC_WEEKDAYS = [
  "Пн",
  "Вт",
  "Ср",
  "Чт",
  "Пт",
  "Сб",
  "Вс",
];

/**
 * Э15: музыкальная предложка. Настройки (день/час публикации, вкл, подпись
 * автора), превью пула с удалением и история подборок — то, что просил H.7.
 */
function MusicSection({ users }: { users: User[] }) {
  const queryClient = useQueryClient();
  const key = ["admin", "game", "music"] as const;
  const state = useQuery({ queryKey: key, queryFn: fetchGameMusic });
  const save = useMutation({
    mutationFn: updateGameMusic,
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });
  const drop = useMutation({
    mutationFn: removeMusicTrack,
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });
  const byId = Object.fromEntries(users.map((u) => [u.id, u] as const));
  const data = state.data;
  if (!data) return null;
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold">🎧 Музыкальная предложка</h2>
        <span className="text-xs text-tg-hint tabular-nums">
          в пуле: {data.pool.length}
        </span>
      </div>
      <Toggle
        label="Включена"
        hint="Раз в неделю бот выкладывает подборку из присланного в личку"
        on={data.enabled}
        busy={save.isPending}
        onClick={() => {
          haptic("selection");
          save.mutate({ enabled: !data.enabled });
        }}
      />
      <Toggle
        label="Подписывать автора"
        hint="В подборке будет «(от Митяна)»"
        on={data.attribute}
        busy={save.isPending}
        onClick={() => {
          haptic("selection");
          save.mutate({ attribute: !data.attribute });
        }}
      />
      <div className="flex items-center gap-2">
        <span className="text-xs text-tg-hint">день публикации</span>
        <select
          value={data.weekday}
          onChange={(e) => save.mutate({ weekday: Number(e.target.value) })}
          className="rounded bg-tg-bg/60 px-2 py-1 text-xs text-tg-text"
        >
          {MUSIC_WEEKDAYS.map((label, index) => (
            <option key={label} value={index}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <NumberRow
        label="час публикации"
        value={data.hour}
        busy={save.isPending}
        onSave={(n) => save.mutate({ hour: Math.min(23, Math.max(0, n)) })}
      />
      <div className="text-[11px] text-tg-hint">
        В подборке {data.min_tracks}–{data.max_tracks} треков, лимит
        {` ${data.per_user_weekly} `}на участника в неделю.
      </div>

      {/* Э16: мьюзик-гейм «угадай, кто предложил трек». */}
      <div className="mt-2 space-y-2 border-t border-tg-bg/40 pt-2">
        <div className="flex items-baseline justify-between">
          <span className="text-xs font-semibold text-tg-text">
            🎵 Мьюзик-гейм
          </span>
          <span className="text-[11px] text-tg-hint">«кто предложил трек»</span>
        </div>
        <Toggle
          label="Авто-вызов"
          hint="Раз в неделю бот берёт случайный трек и запускает опрос. По умолчанию выкл; вручную — /musicgame"
          on={data.game_enabled}
          busy={save.isPending}
          onClick={() => {
            haptic("selection");
            save.mutate({ game_enabled: !data.game_enabled });
          }}
        />
        <div className="flex items-center gap-2">
          <span className="text-xs text-tg-hint">день игры</span>
          <select
            value={data.game_weekday}
            onChange={(e) =>
              save.mutate({ game_weekday: Number(e.target.value) })
            }
            className="rounded bg-tg-bg/60 px-2 py-1 text-xs text-tg-text"
          >
            {MUSIC_WEEKDAYS.map((label, index) => (
              <option key={label} value={index}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <NumberRow
          label="час игры"
          value={data.game_hour}
          busy={save.isPending}
          onSave={(n) => save.mutate({ game_hour: Math.min(23, Math.max(0, n)) })}
        />
      </div>
      {data.pool.length > 0 && (
        <ul className="space-y-1">
          {data.pool.map((track) => (
            <li
              key={track.id}
              className="flex items-center gap-2 rounded bg-tg-bg/50 px-2 py-1"
            >
              <span className="min-w-0 flex-1 truncate text-xs">
                {track.title || track.performer || track.url || "трек"}
              </span>
              <span className="shrink-0 text-[11px] text-tg-hint">
                {byId[track.user_id]?.display_name ?? track.user_id}
              </span>
              <button
                type="button"
                onClick={() => drop.mutate(track.id)}
                className="rounded bg-status-busy/15 px-2 py-0.5 text-[11px] text-status-busy"
                aria-label="Убрать трек"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {data.history.length > 0 && (
        <div className="text-[11px] text-tg-hint">
          Последнее: {data.history[0].note === "shortfall"
            ? "недобор"
            : `подборка из ${data.history[0].track_count}`}
        </div>
      )}
    </section>
  );
}
