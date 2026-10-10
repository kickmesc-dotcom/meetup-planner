import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchGuestProfile,
  fetchMyGame,
  type GuestAchievement,
  type GuestProfile,
  type GuestRecent,
  type GuestTitleEvent,
} from "@/api/game";
import { fetchMe, fetchUiPrefs, updateUiPrefs } from "@/api/availability";
import { apiPublicUrl } from "@/api/client";
import MediaLightbox from "@/components/MediaLightbox";
import RankPlaque from "@/components/RankPlaque";
import { Spinner } from "@/components/Spinner";
import ErrorState from "@/components/ErrorState";
import { Switch } from "@/components/Checkbox";
import { haptic } from "@/tg/webapp";

/**
 * Э19: чужой профиль «глазами гостя».
 *
 * Открывается кликом по аватарке участника на календаре и из ленты. Здесь НЕТ
 * ни настроек, ни пояснений «куда зайти» — только факты о человеке.
 *
 * GHG11(7): порядок блоков задан прод-фидбеком (сверху вниз):
 *  1. главная плашка — имя, ранг, уровень и «сколько до следующего», а в этой же
 *     карточке — активные состояния (лох/чухан/червь) с короткой причиной;
 *  2. сетка из 4 подблоков — лох дня «N раз», чухан «N раз», место в чарте
 *     (с пояснением, ПО ЧЕМУ) и сколько держал червя;
 *  3. блок открытых ачивок с процентом: разворачивается, чтобы посмотреть какие
 *     именно открыты, и сразу сравнить со своими;
 *  4. сворачиваемые истории «лоха дня» и «чухана недели» — разнострочно
 *     (чередование фона), чтобы длинный мелкий текст не сливался;
 *  5. превью последней активности;
 *  6. САМЫЙ низ — малоакцентированный свитчер «не показывать события участника
 *     в моей ленте» (GHG11(13): раньше он стоял посреди карточки и мешал
 *     читать профиль).
 */
export default function GuestProfileScreen({
  userId,
  onClose,
}: {
  userId: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["guest-profile", userId],
    queryFn: () => fetchGuestProfile(userId),
  });
  // GHG11(3): свой процент открытых ачивок — чтобы сравнить в профиле гостя.
  const myGame = useQuery({
    queryKey: ["me-game"],
    queryFn: fetchMyGame,
    staleTime: 5 * 60 * 1000,
  });
  // GHG11(7): свой внутренний id — чтобы не предлагать скрыть себя.
  const meQ = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: 5 * 60 * 1000,
  });

  const p = q.data;
  const mineAchievements = myGame.data?.achievements ?? [];
  const myCollectedCount = mineAchievements.filter((a) => a.collected).length;
  const myPercent =
    mineAchievements.length > 0
      ? Math.round((myCollectedCount * 100) / mineAchievements.length)
      : null;
  // Сравниваем по БАЗОВОМУ коду: у гостя в списке есть и юбилейные тиры
  // (`code:10`), у меня в каталоге — базовая ачивка с `code`.
  const myBaseCodes = new Set(
    mineAchievements.filter((a) => a.collected).map((a) => a.code.split(":")[0]),
  );
  const isSelf = meQ.data?.id === p?.user_id;

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
          <ErrorState
            error={q.error}
            onRetry={() => q.refetch()}
            title="Не удалось открыть профиль"
          />
        )}

        {p && !p.enabled && (
          <section className="rounded-xl bg-tg-secondary-bg/60 p-3 text-sm text-tg-hint">
            Игровая система сейчас выключена — профиль показывать нечего.
          </section>
        )}

        {p && p.enabled && (
          <div className="space-y-3">
            <MainPlaque p={p} />
            <StatsGrid p={p} />
            <AchievementsBlock
              p={p}
              myPercent={myPercent}
              myBaseCodes={myBaseCodes}
            />
            <CollapsibleHistory
              title="🤡 История «лоха дня»"
              empty="Ни разу не был лохом дня."
              events={p.loser_history}
            />
            <CollapsibleHistory
              title="💩 История «чухана недели»"
              empty="Ни разу не был чуханом недели."
              events={p.chukhan_history}
            />

            {/* GHG11(10): превью последней активности. */}
            <RecentActivity recent={p.recent ?? []} />

            {/* GHG11(13): персональный фильтр ленты — в САМОМ низу профиля, а не
                посреди карточки (своя карточка не даёт «сломать ленту»:
                галочку себя отключить нельзя). */}
            {!isSelf && (
              <MuteFeedSwitch userId={p.user_id} name={p.name} onDone={() => qc.invalidateQueries({ queryKey: ["ui-prefs"] })} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** GHG11(7): главная плашка — имя, ранг, уровень и активные состояния. */
function MainPlaque({ p }: { p: GuestProfile }) {
  const hasState = !!(p.today?.loser || p.today?.chukhan || p.today?.worm);
  const total = p.xp_into_level + (p.xp_to_next ?? 0);
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-4">
      <div className="flex items-center gap-3">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full text-xl font-semibold text-white"
          style={{ background: p.rank?.hex ?? "#6b7280" }}
        >
          {p.avatar_url ? (
            <img src={p.avatar_url} alt="" className="h-full w-full object-cover" />
          ) : (
            initials(p.name)
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-lg font-semibold">{p.name}</div>
          {p.rank && (
            <div className="mt-1">
              <RankPlaque hex={p.rank.hex} bold={p.rank.bold || p.supreme}>
                {p.supreme ? "🏅 " : ""}
                {p.rank_name || p.rank.name}
              </RankPlaque>
            </div>
          )}
          <div className="mt-1 text-xs text-tg-hint">
            Ур. {p.level} из {p.max_level} · {p.xp} XP
            {p.prestige > 0 ? ` · престиж ${p.prestige}` : ""}
          </div>
        </div>
      </div>

      {/* «Сколько до следующего» — как в своём профиле. На максимуме — престиж. */}
      {p.at_max ? (
        <div className="mt-3 flex items-center justify-between rounded-lg bg-tg-bg/50 px-3 py-2">
          <span className="text-xs text-tg-hint">Максимальный ранг</span>
          <span className="text-sm text-tg-text">
            ✦ Престиж <span className="font-bold tabular-nums">{p.prestige}</span>
          </span>
        </div>
      ) : (
        <div className="mt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-tg-bg/70">
            <div
              className="h-full rounded-full bg-tg-link"
              style={{ width: `${total > 0 ? Math.min(100, (p.xp_into_level * 100) / total) : 0}%` }}
            />
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px] text-tg-hint">
            <span className="tabular-nums">
              {p.xp_into_level}/{total} XP
            </span>
            <span className="tabular-nums">
              до след. ранга: {p.xp_to_next ?? 0} XP
            </span>
          </div>
        </div>
      )}

      {/* GHG11(7): активные состояния — в этой же карточке, каждое со своей
          короткой причиной. */}
      {hasState && (
        <div className="mt-3 space-y-1">
          {p.today?.loser && (
            <StateRow icon="👑" label="Сегодня лох дня" reason={p.today.loser_reason} />
          )}
          {p.today?.chukhan && (
            <StateRow
              icon="💩"
              label="Чухан недели"
              reason={p.today.chukhan_reason}
            />
          )}
          {p.today?.worm && <StateRow icon="🪱" label="Сейчас червь-пидор" reason={null} />}
        </div>
      )}
    </section>
  );
}

/** Одна строка активного состояния: эмодзи, звание и причина. */
function StateRow({
  icon,
  label,
  reason,
}: {
  icon: string;
  label: string;
  reason: string | null;
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-tg-bg/40 px-2 py-1.5">
      <span className="shrink-0 text-sm leading-tight">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] font-semibold text-tg-text">{label}</div>
        {reason && (
          <div className="text-[11px] italic leading-snug text-tg-hint [word-break:break-word]">
            «{reason}»
          </div>
        )}
      </div>
    </div>
  );
}

/** GHG11(7): 4 подблока — лох/чухан «раз», место в чарте и червь. */
function StatsGrid({ p }: { p: GuestProfile }) {
  return (
    <section className="grid grid-cols-2 gap-2">
      <Stat
        label="🤡 Лох дня"
        value={`${p.loser_count} ${timesWord(p.loser_count)}`}
      />
      <Stat
        label="💩 Чухан недели"
        value={`${p.chukhan_count} ${timesWord(p.chukhan_count)}`}
      />
      <Stat
        label="🏆 Место в чарте"
        value={
          p.rank_position != null && p.ranks_total > 0
            ? `${p.rank_position} из ${p.ranks_total}`
            : "—"
        }
        hint="по опыту (XP) среди всех участников"
      />
      <Stat
        label="🪱 Держал червя"
        value={p.worm_total_days > 0 ? `${p.worm_total_days} дн.` : "—"}
      />
    </section>
  );
}

/**
 * GHG11(7): блок открытых ачивок.
 *
 * Свёрнут по умолчанию: сверху процент и полоса, ниже — сравнение со своими.
 * По тапу разворачивается список «какие именно открыты», где у каждой ачивки
 * видно, есть ли она у тебя (сравнение со своими).
 */
function AchievementsBlock({
  p,
  myPercent,
  myBaseCodes,
}: {
  p: GuestProfile;
  myPercent: number | null;
  myBaseCodes: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        className="w-full p-3 text-left"
      >
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold">📊 Открыто ачивок</div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tabular-nums text-tg-text">
              {p.achievements_percent}%
            </span>
            <span className="text-tg-hint">{open ? "▾" : "▸"}</span>
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
        <div className="mt-1 text-[10px] text-tg-hint">
          {open
            ? "Свернуть список"
            : "Разверни — посмотреть, какие именно, и сравнить со своими"}
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3">
          {p.achievements.length === 0 ? (
            <div className="text-xs text-tg-hint">Пока пусто — ни одной ачивки.</div>
          ) : (
            <ul className="space-y-1">
              {p.achievements.map((a) => (
                <GuestAchievementRow
                  key={a.code}
                  a={a}
                  mine={myBaseCodes.has(a.code.split(":")[0])}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * GHG11(7): история звания — «когда и за что», свёрнутая по умолчанию.
 *
 * Разнострочный вывод: соседние строки чередуют фон (тёмная/светлая), чтобы
 * длинный мелкий текст причин не сливался в одну простыню.
 */
function CollapsibleHistory({
  title,
  empty,
  events,
}: {
  title: string;
  empty: string;
  events: GuestTitleEvent[];
}) {
  const [open, setOpen] = useState(false);

  if (events.length === 0) {
    return (
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-sm font-semibold">{title}</div>
        <div className="mt-1 text-xs text-tg-hint">{empty}</div>
      </section>
    );
  }

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-2 p-3 text-left"
      >
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</span>
        <span className="shrink-0 text-[11px] tabular-nums text-tg-hint">
          {events.length} шт.
        </span>
        <span className="shrink-0 text-tg-hint">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          <ul className="space-y-0.5">
            {events.map((e, i) => (
              <li
                key={`${e.at}-${i}`}
                data-stripe={i % 2 === 0 ? "dark" : "light"}
                className={[
                  "rounded-md px-2 py-1 text-xs leading-snug text-tg-text [word-break:break-word]",
                  i % 2 === 0 ? "bg-tg-bg/60" : "bg-tg-hint/10",
                ].join(" ")}
              >
                <span className="text-tg-hint">{formatDate(e.at)}</span>
                {e.reason ? <> — «{e.reason}»</> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/**
 * GHG11(10): «не показывать события участника» — тихая, вполовину меньшая
 * настройка «хорошо иметь». Без карточки, без акцента, размер — `sm`.
 */
function MuteFeedSwitch({
  userId,
  name,
  onDone,
}: {
  userId: number;
  name: string;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: ["ui-prefs"], queryFn: fetchUiPrefs });
  const save = useMutation({
    mutationFn: (next: number[]) => updateUiPrefs({ muted_feed: next }),
    onSuccess: (out) => {
      haptic("success");
      qc.setQueryData(["ui-prefs"], out);
      void qc.invalidateQueries({ queryKey: ["game-feed"] });
      onDone();
    },
    onError: () => haptic("error"),
  });

  const muted = prefs.data?.muted_feed ?? [];
  const checked = muted.includes(userId);
  const toggle = (v: boolean) => {
    const next = v ? [...muted, userId] : muted.filter((i) => i !== userId);
    save.mutate(next);
  };

  return (
    <section
      data-testid="mute-feed-switch"
      className="flex items-center justify-between gap-2 px-2 py-1.5"
    >
      <div
        title={name}
        className="min-w-0 truncate text-[10px] leading-tight text-tg-hint/80"
      >
        🙈 Не показывать события участника в моей ленте
      </div>
      <Switch
        size="sm"
        checked={checked}
        disabled={save.isPending || !prefs.data}
        onChange={toggle}
      />
    </section>
  );
}

/**
 * GHG11(10): блок последней активности участника (низ профиля).
 *
 * Пять источников от бэкенда: последнее сообщение в чат, последняя ачивка,
 * последнее действие в мини-аппе, последнее медиа (с превью) и последний заход.
 * Порядок задаёт сервер; отсутствующие источники просто не приходят.
 */
function RecentActivity({ recent }: { recent: GuestRecent[] }) {
  const [lightbox, setLightbox] = useState<{
    postId: number;
    mediaType: string | null;
  } | null>(null);

  if (recent.length === 0) return null;

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="text-sm font-semibold">🕘 Последняя активность</div>
      <div className="mt-2 space-y-1.5">
        {recent.map((r) => (
          <div key={r.kind} className="rounded-lg bg-tg-bg/40 px-2 py-1.5">
            <div className="flex items-start gap-2">
              <span className="shrink-0 text-sm leading-tight">{r.icon}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[10px] text-tg-hint">{r.label}</div>
                {r.text && (
                  <div className="text-xs text-tg-text [word-break:break-word]">
                    {r.text}
                  </div>
                )}
                {r.at && (
                  <div className="text-[10px] tabular-nums text-tg-hint">
                    {formatDateTime(r.at)}
                  </div>
                )}
              </div>
            </div>
            {r.kind === "media" && r.post_id != null && (
              <MediaThumb
                postId={r.post_id}
                mediaType={r.media_type}
                onOpen={() =>
                  setLightbox({ postId: r.post_id!, mediaType: r.media_type })
                }
              />
            )}
          </div>
        ))}
      </div>

      {lightbox && (
        <MediaLightbox
          src={apiPublicUrl(`/api/media/${lightbox.postId}`)}
          alt=""
          onClose={() => setLightbox(null)}
        />
      )}
    </section>
  );
}

/** GHG11(10): мини-превью медиа; по клику открывается крупно (лайтбокс). */
function MediaThumb({
  postId,
  mediaType,
  onOpen,
}: {
  postId: number;
  mediaType: string | null;
  onOpen: () => void;
}) {
  const [failed, setFailed] = useState(false);
  // GHG11(13): превью у части старых постов нет вовсе (404) — тогда не
  // предлагаем «открыть» его в пустой лайтбокс, а честно показываем иконку типа.
  if (failed) {
    return (
      <div
        data-testid="media-thumb"
        title="Превью недоступно"
        className="mt-1.5 flex h-20 w-20 items-center justify-center rounded-lg bg-tg-bg/60 text-xl opacity-70"
      >
        {mediaIcon(mediaType)}
      </div>
    );
  }
  return (
    <button
      type="button"
      data-testid="media-thumb"
      onClick={() => {
        haptic("light");
        onOpen();
      }}
      className="mt-1.5 block h-20 w-20 overflow-hidden rounded-lg bg-tg-bg/60"
    >
      <img
        src={apiPublicUrl(`/api/media/${postId}`)}
        alt=""
        onError={() => setFailed(true)}
        className="h-full w-full object-cover"
      />
    </button>
  );
}

/** Иконка типа медиа — когда картинки-превью нет (видео без миниатюры и т.п.). */
function mediaIcon(mediaType: string | null): string {
  switch (mediaType) {
    case "video":
    case "video_note":
      return "🎬";
    case "animation":
      return "🖼";
    case "sticker":
      return "🏷";
    case "voice":
      return "🎙";
    case "audio":
      return "🎵";
    case "document":
      return "📄";
    default:
      return "📷";
  }
}

/**
 * GHG11(3/6/7): ачивка гостя — дата и время получения справа (ненавязчиво),
 * по тапу раскрывается «за что» и награда; значок сравнения — есть ли у тебя.
 */
function GuestAchievementRow({
  a,
  mine,
}: {
  a: GuestAchievement;
  mine: boolean;
}) {
  const [open, setOpen] = useState(false);
  const when = a.unlocked_at ? splitWhen(a.unlocked_at) : null;
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
        <span
          className="shrink-0 text-[10px]"
          title={mine ? "Такая ачивка есть и у тебя" : "У тебя её ещё нет"}
        >
          {mine ? "✓" : "·"}
        </span>
        {when && (
          <span className="shrink-0 text-right leading-tight">
            <span className="block text-[10px] tabular-nums text-tg-hint">
              {when.date}
            </span>
            <span className="block text-[10px] tabular-nums text-tg-hint opacity-70">
              {when.time}
            </span>
          </span>
        )}
        <span className="shrink-0 text-tg-hint">{open ? "▾" : "▸"}</span>
      </div>
      {open && (
        <div className="mt-1 space-y-0.5 pl-7 text-[11px] text-tg-hint">
          {a.description && <div>За что: {a.description}</div>}
          {when && (
            <div>
              Когда: {when.date}, {when.time}
            </div>
          )}
          {typeof a.points === "number" && a.points > 0 && (
            <div>Награда: +{a.points} XP</div>
          )}
          <div>{mine ? "✓ Такая ачивка есть и у тебя" : "· У тебя её ещё нет"}</div>
        </div>
      )}
    </li>
  );
}

/** GHG11(6): дата и время получения — в две приглушённые строки справа. */
function splitWhen(iso: string): { date: string; time: string } | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return {
    date: d.toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }),
    time: d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }),
  };
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

/** GHG11(10): дата и время одной строкой — для последней активности. */
function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Русская плюрализация: 1 раз / 2 раза / 5 раз. */
function timesWord(n: number): string {
  const abs = Math.abs(n);
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (mod10 === 1 && mod100 !== 11) return "раз";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "раза";
  return "раз";
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl bg-tg-secondary-bg/60 px-3 py-2">
      <div className="text-[10px] text-tg-hint">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-tg-text">{value}</div>
      {hint && <div className="mt-0.5 text-[10px] leading-tight text-tg-hint">{hint}</div>}
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
