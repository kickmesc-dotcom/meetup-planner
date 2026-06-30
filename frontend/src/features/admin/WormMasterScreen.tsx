import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchWormMasterSettings,
  updateWormMasterSettings,
  fetchWormMasterPools,
  updateWormMasterPool,
  type WormMasterSettings,
  type WormMasterPool,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";
import ReasonsEditor from "./ReasonsEditor";

interface Props {
  onBack: () => void;
}

const errAlert = (e: unknown) => {
  haptic("error");
  void showAlert(humanizeApiError(e));
};

/**
 * GHG8 T3.6.6: админка режима «червь-господин» (фидбек 13.06 #2). Носитель
 * звания «червь-пидор» на период владения становится «господином» бота.
 * Бэк-логика (анонс становления, подхалимаж лоху/чухану-господину, /punish)
 * уже в проде, но gated `worm_master.enabled` — здесь единственный UI-вход:
 * тоглы поведения (авто-save, как MediaReactionsScreen) + CRUD 6 пулов фраз
 * через универсальный ReasonsEditor.
 *
 * ⚠️ Поддакивание (agrees/nag + шанс + кулдаун) — поведение ещё в разработке
 * (T3.6.8), поэтому контролы помечены «скоро»: редактировать пулы можно, но бот
 * пока на них не реагирует.
 */
export default function WormMasterScreen({ onBack }: Props) {
  const qc = useQueryClient();

  // --- поведение (авто-save) ---
  const settingsQ = useQuery({
    queryKey: ["admin", "worm-master", "settings"],
    queryFn: fetchWormMasterSettings,
    staleTime: 30_000,
  });
  const [draft, setDraft] = useState<WormMasterSettings | null>(null);
  useEffect(() => {
    if (settingsQ.data) setDraft({ ...settingsQ.data });
  }, [settingsQ.data]);

  const saveSettings = useMutation({
    mutationFn: updateWormMasterSettings,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "worm-master", "settings"], data);
    },
    onError: errAlert,
  });

  const patch = (p: Partial<WormMasterSettings>) => {
    if (!draft) return;
    const next = { ...draft, ...p };
    setDraft(next);
    saveSettings.mutate(next);
  };

  // --- пулы ---
  const poolsQ = useQuery({
    queryKey: ["admin", "worm-master", "pools"],
    queryFn: fetchWormMasterPools,
    staleTime: 30_000,
  });

  const savePool = useMutation({
    mutationFn: ({ pool, phrases }: { pool: WormMasterPool; phrases: string[] }) =>
      updateWormMasterPool(pool, phrases),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "worm-master", "pools"], data);
    },
    onError: errAlert,
  });

  return (
    <SubScreen
      title="🪱 Червь-господин"
      subtitle="Подхалимаж · /punish · анонс"
      onBack={onBack}
    >
      {/* 1. Поведение */}
      {settingsQ.isPending || !draft ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={4} />
        </section>
      ) : (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
          <div className="text-xs text-tg-hint mb-1">
            Червь периода владения становится «господином»: при лохе/чухане бот
            добавляет подхалимский префикс/суффикс, расширяет анонс становления и
            принимает команду <b>/punish</b>.
          </div>

          <ToggleRow
            label="Режим господина включён"
            hint="Главный рубильник. Пока выключен — всё поведение червя молчит."
            checked={draft.enabled}
            onChange={(v) => patch({ enabled: v })}
          />

          <div
            className={[
              "space-y-2 transition-opacity",
              draft.enabled ? "" : "opacity-40 pointer-events-none",
            ].join(" ")}
          >
            <ToggleRow
              label="Команда /punish"
              hint="Господин может натравить бота: /punish @user, #punish, #наказать."
              checked={draft.punish_enabled}
              onChange={(v) => patch({ punish_enabled: v })}
            />

            {/* Поддакивание — поведение в разработке (T3.6.8). */}
            <div className="rounded-md bg-tg-bg/40 px-2 py-2 space-y-2">
              <div className="flex items-center gap-2">
                <div className="text-sm text-tg-text">🤫 Поддакивание</div>
                <span className="text-[10px] rounded bg-status-busy/15 px-1.5 py-0.5 text-status-busy">
                  ⏳ скоро
                </span>
              </div>
              <div className="text-[11px] text-tg-hint">
                Бот изредка одобрительно комментирует сообщения господина. Пулы
                фраз ниже уже можно редактировать, но реакция включится в
                следующем обновлении.
              </div>
              <ToggleRow
                label="Поддакивать сообщениям господина"
                checked={draft.yes_enabled}
                onChange={(v) => patch({ yes_enabled: v })}
              />
              <PctRow
                label="Шанс поддакнуть"
                hint="Вероятность реакции на сообщение господина."
                value={draft.yes_pct}
                onChange={(v) => patch({ yes_pct: v })}
              />
              <NumRow
                label="Кулдаун, мин"
                hint="Не чаще одного поддакивания раз в N минут (0–1440)."
                value={draft.yes_cooldown_min}
                min={0}
                max={1440}
                onChange={(v) => patch({ yes_cooldown_min: v })}
              />
            </div>
          </div>
        </section>
      )}

      {/* 2. Пулы фраз */}
      <PoolSection
        title="🙇 Подхалимские префиксы"
        hint="Ставятся ПЕРЕД анонсом лоха/чухана-господина. {username} — имя господина."
        placeholder="например: Мой господин {username}, вынужден вас расстроить…"
        pool="prefixes"
        data={poolsQ.data?.prefixes}
        isPending={poolsQ.isPending}
        saving={savePool.isPending}
        onSave={(phrases) => savePool.mutate({ pool: "prefixes", phrases })}
      />
      <PoolSection
        title="🙇 Подхалимские суффиксы"
        hint="Ставятся ПОСЛЕ анонса. {username} — имя господина."
        placeholder="например: Ваша неудача и моё личное поражение, милорд {username}."
        pool="suffixes"
        data={poolsQ.data?.suffixes}
        isPending={poolsQ.isPending}
        saving={savePool.isPending}
        onSave={(phrases) => savePool.mutate({ pool: "suffixes", phrases })}
      />
      <PoolSection
        title="👑 Анонс становления червём"
        hint="Описание «что даёт звание господина». {username} — имя, {chance} — шанс в %."
        placeholder="например: С данной минуты {username} — мой великий господин."
        pool="announce_lines"
        data={poolsQ.data?.announce_lines}
        isPending={poolsQ.isPending}
        saving={savePool.isPending}
        onSave={(phrases) => savePool.mutate({ pool: "announce_lines", phrases })}
      />
      <PoolSection
        title="🤬 Наказания /punish"
        hint="Рпг-наказание недруга. {target} — упоминание жертвы."
        placeholder="например: Влетаю с двух ног в грудину {target}."
        pool="punish"
        data={poolsQ.data?.punish}
        isPending={poolsQ.isPending}
        saving={savePool.isPending}
        onSave={(phrases) => savePool.mutate({ pool: "punish", phrases })}
      />
      <PoolSection
        title="🤫 Поддакивания"
        badge="⏳ скоро"
        hint="Короткие одобрения сообщений господина. {username} — имя господина."
        placeholder="например: Господин {username} не может ошибаться."
        pool="agrees"
        data={poolsQ.data?.agrees}
        isPending={poolsQ.isPending}
        saving={savePool.isPending}
        onSave={(phrases) => savePool.mutate({ pool: "agrees", phrases })}
      />
      <PoolSection
        title="🔔 Напоминания /отвали"
        badge="⏳ скоро"
        hint="Изредка напоминают господину, как заткнуть подхалима. {username} — имя."
        placeholder="например: Шепните /отвали, мой господин, и я умолкну."
        pool="nag"
        data={poolsQ.data?.nag}
        isPending={poolsQ.isPending}
        saving={savePool.isPending}
        onSave={(phrases) => savePool.mutate({ pool: "nag", phrases })}
      />
    </SubScreen>
  );
}

function PoolSection({
  title,
  badge,
  hint,
  placeholder,
  data,
  isPending,
  saving,
  onSave,
}: {
  title: string;
  badge?: string;
  hint: string;
  placeholder: string;
  pool: WormMasterPool;
  data: string[] | undefined;
  isPending: boolean;
  saving: boolean;
  onSave: (phrases: string[]) => void;
}) {
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 mt-3 space-y-2">
      <div className="flex items-center gap-2">
        <div className="text-sm font-semibold text-tg-text">{title}</div>
        {badge && (
          <span className="text-[10px] rounded bg-status-busy/15 px-1.5 py-0.5 text-status-busy">
            {badge}
          </span>
        )}
      </div>
      <div className="text-[11px] text-tg-hint">{hint}</div>
      {isPending || data === undefined ? (
        <ListSkeleton rows={3} />
      ) : (
        <ReasonsEditor
          initial={data}
          isPending={saving}
          placeholder={placeholder}
          emptyHint="Пусто — будет использован дефолт из кода."
          onSave={onSave}
        />
      )}
    </section>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
      <div className="min-w-0">
        <div className="text-sm text-tg-text">{label}</div>
        {hint && <div className="text-[11px] text-tg-hint">{hint}</div>}
      </div>
      <Switch
        checked={checked}
        onChange={(v) => {
          haptic("selection");
          onChange(v);
        }}
      />
    </div>
  );
}

function PctRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="text-sm text-tg-text">{label}</div>
        {hint && <div className="text-[11px] text-tg-hint">{hint}</div>}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <input
          type="number"
          min={0}
          max={100}
          value={value}
          onChange={(e) => {
            const n = Math.max(0, Math.min(100, Number(e.target.value) || 0));
            onChange(n);
          }}
          className="w-16 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text text-right outline-none border border-transparent focus:border-tg-link tabular-nums"
        />
        <span className="text-xs text-tg-hint">%</span>
      </div>
    </div>
  );
}

function NumRow({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="text-sm text-tg-text">{label}</div>
        {hint && <div className="text-[11px] text-tg-hint">{hint}</div>}
      </div>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          const n = Math.max(min, Math.min(max, Number(e.target.value) || min));
          onChange(n);
        }}
        className="w-16 shrink-0 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text text-right outline-none border border-transparent focus:border-tg-link tabular-nums"
      />
    </div>
  );
}

function Switch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={[
        "shrink-0 inline-flex h-6 w-11 items-center rounded-full transition-colors",
        checked ? "bg-tg-button" : "bg-tg-hint/30",
      ].join(" ")}
      role="switch"
      aria-checked={checked}
    >
      <span
        className={[
          "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5" : "translate-x-0.5",
        ].join(" ")}
      />
    </button>
  );
}
