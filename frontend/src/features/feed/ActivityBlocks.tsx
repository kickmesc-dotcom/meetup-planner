/**
 * GHG11(8): участие в активностях из мини-аппа.
 *
 * Изначально (Э21) это была отдельная панель над лентой: «Событие» с кнопками и
 * голосовое задание с записью. Оператор попросил другого: анонс задания сам
 * висит в ленте — значит, по тапу по нему и должен открываться интерфейс
 * участия (текст → инпут, голос → запись, выбор → кнопки).
 *
 * Поэтому панель распалась на переиспользуемые блоки, которые живут внутри
 * карточки записи ленты (`FeedDetailPanel`), а этот файл остался их домом:
 *
 *  - `ActivityResponse` — ответ на призыв: варианты кнопками и/или поле ввода;
 *  - `VoiceTaskAction` — сдать/убрать голосовое прямо у задания;
 *  - `VoiceRecorder` — запись и отправка;
 *  - `OrphanActivities` — страховка: открытый призыв, у которого нет анонса в
 *    загруженной странице ленты (режим «только чат»), всё равно доступен.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  answerActivity,
  fetchActivities,
  fetchVoiceCurrent,
  uploadVoice,
  withdrawVoice,
  type ActivityOption,
} from "@/api/game";
import { haptic, showAlert } from "@/tg/webapp";
import {
  pickRecorderFormat,
  prepareVoiceBlob,
  type RecorderFormat,
} from "@/lib/voiceFormat";

export const QUERY_ACT = ["game-activities"] as const;
export const QUERY_VOICE = ["game-voice"] as const;

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: QUERY_ACT });
  void qc.invalidateQueries({ queryKey: QUERY_VOICE });
  void qc.invalidateQueries({ queryKey: ["game-feed"] });
  void qc.invalidateQueries({ queryKey: ["me"] });
}

/** Минимум полей, нужный блоку участия. У анонса в ленте есть не всё. */
export interface ActivityLike {
  id: number;
  options: ActivityOption[];
  needs_text: boolean;
  expires_at: string | null;
  answered_by_me: boolean;
  /** GHG11(8.a): задание уже закрыто — ввод/кнопки не показываем. */
  closed?: boolean;
}

/** Коды отказа, которые означают «задание закрылось», а не «ответ не подошёл». */
const CLOSED_STATUSES = new Set(["closed", "expired", "not_found"]);

// ---------------------------------------------------------------------------
// Ответ на призыв (варианты кнопками и/или свободный текст)
// ---------------------------------------------------------------------------

/**
 * Интерфейс участия в задании-призыве.
 *
 * Ответ уходит тем же путём, что и сообщение в чате (`events.try_answer`),
 * поэтому правило «первый подходящий забирает XP» сохраняется.
 */
export function ActivityResponse({ activity }: { activity: ActivityLike }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState<{ ok: boolean } | null>(null);
  // Код отказа с сервера: «closed/expired/not_found» — задание закрылось, пока
  // карточка висела в ленте. Тогда сворачиваем ввод до следующего рефетча.
  const [blocked, setBlocked] = useState<string | null>(null);

  const send = useMutation({
    mutationFn: (value: string) => answerActivity(activity.id, value),
    onSuccess: (res) => {
      setAnswer({ ok: res.ok });
      if (!res.ok && CLOSED_STATUSES.has(res.status)) setBlocked(res.status);
      haptic(res.ok ? "success" : "error");
      invalidateAll(qc);
    },
    onError: () => haptic("error"),
  });

  const done = answer?.ok === true || activity.answered_by_me;
  // «Истекло» замечаем и без рефетча — по времени из анонса.
  const expired =
    activity.expires_at != null &&
    Date.now() > new Date(activity.expires_at).getTime();
  const closed = !done && (activity.closed === true || expired || blocked !== null);

  return (
    <div
      className="mt-1 space-y-2"
      onClick={(e) => e.stopPropagation()}
      data-testid="feed-activity"
    >
      {done ? (
        <div className="rounded-lg bg-status-free/15 px-2 py-1.5 text-xs font-medium text-status-free">
          ✅ Засчитано! Опыт уже в профиле.
        </div>
      ) : closed ? (
        <>
          {/* GHG11(8.a): задание закрывается — поле ввода/кнопки тоже. */}
          <div
            className="rounded-lg bg-tg-bg/60 px-2 py-1.5 text-xs font-medium text-tg-hint"
            data-testid="feed-activity-closed"
          >
            ⛔ Задание закрыто — приём ответов окончен.
          </div>
          {/* GHG11(13): но САМИ варианты показываем — оператор просил видеть, из
              чего выбирали, даже когда приём уже закрыт (и слушать/смотреть
              закрытые голосовые тоже можно). Кнопки здесь неактивны: это
              справка, а не голосование. */}
          {activity.options.length > 0 && (
            <div
              className="flex flex-wrap gap-1.5"
              data-testid="feed-activity-options"
            >
              {activity.options.map((o) => (
                <span
                  key={o.label}
                  className="rounded-full bg-tg-bg/50 px-3 py-1.5 text-xs font-medium text-tg-hint opacity-80"
                >
                  {o.label}
                  {o.xp > 0 && <span className="ml-1">+{o.xp}</span>}
                </span>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          {activity.options.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {activity.options.map((o) => (
                <button
                  key={o.label}
                  type="button"
                  disabled={send.isPending}
                  onClick={() => {
                    haptic("selection");
                    send.mutate(o.label);
                  }}
                  className="rounded-full bg-tg-bg/70 px-3 py-1.5 text-xs font-medium text-tg-text active:scale-[0.98] disabled:opacity-50"
                >
                  {o.label}
                  {o.xp > 0 && <span className="ml-1 text-tg-hint">+{o.xp}</span>}
                </button>
              ))}
            </div>
          )}
          {activity.needs_text && (
            <div className="flex gap-1.5">
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Ответь прямо здесь…"
                maxLength={1000}
                className="min-w-0 flex-1 rounded-lg bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
              />
              <button
                type="button"
                disabled={send.isPending || !text.trim()}
                onClick={() => {
                  haptic("selection");
                  send.mutate(text.trim());
                  setText("");
                }}
                className="shrink-0 rounded-lg bg-tg-button px-3 py-1.5 text-sm font-medium text-tg-button-text active:scale-[0.98] disabled:opacity-50"
              >
                Отправить
              </button>
            </div>
          )}
          {answer && !answer.ok && (
            <div className="rounded-lg bg-status-busy/15 px-2 py-1.5 text-xs font-medium text-status-busy">
              Не подошло — попробуй другой ответ.
            </div>
          )}
        </>
      )}
      {!closed && !done && activity.expires_at && (
        <div className="text-[11px] text-tg-hint">
          Ответы принимаются {formatUntil(activity.expires_at)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Голосовое задание
// ---------------------------------------------------------------------------

/**
 * Участие в голосовом задании прямо у его анонса: сдать запись или убрать
 * свою, если уже сдал. Ничего не рисует, если задание не то/закрыто.
 */
export function VoiceTaskAction({ taskId }: { taskId: number }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: QUERY_VOICE,
    queryFn: fetchVoiceCurrent,
    staleTime: 15_000,
  });
  const data = q.data;
  if (!data?.enabled || data.task_id !== taskId) return null;
  return (
    <div
      className="mt-1"
      onClick={(e) => e.stopPropagation()}
      data-testid="feed-voice-action"
    >
      {data.my_submission_id !== null ? (
        <VoiceWithdraw />
      ) : (
        // GHG11(8.a): если задание закрылось, пока участник записывал, сервер
        // ответит `no_task`/`closed` — обновляем запросы, и блок записи исчезает.
        <VoiceRecorder
          onUploaded={() => invalidateAll(qc)}
          onClosed={() => invalidateAll(qc)}
        />
      )}
    </div>
  );
}

/** Убрать свой вариант: двойное подтверждение (откат опыта отменить нельзя). */
export function VoiceWithdraw() {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const withdraw = useMutation({
    mutationFn: withdrawVoice,
    onSuccess: () => {
      haptic("medium");
      setConfirming(false);
      invalidateAll(qc);
    },
    onError: () => haptic("error"),
  });

  if (!confirming) {
    return (
      <div className="flex items-center gap-2">
        <span className="flex-1 text-xs text-tg-hint">Твой вариант принят.</span>
        <button
          type="button"
          onClick={() => {
            haptic("selection");
            setConfirming(true);
          }}
          className="shrink-0 rounded-lg bg-status-busy/15 px-3 py-1.5 text-xs font-medium text-status-busy"
        >
          Убрать
        </button>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded-lg bg-tg-secondary-bg/70 px-2.5 py-1.5 text-xs font-medium text-tg-text"
        >
          Оставить
        </button>
        <button
          type="button"
          disabled={withdraw.isPending}
          onClick={() => {
            haptic("medium");
            withdraw.mutate();
          }}
          className="rounded-lg bg-status-busy px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-50"
        >
          {withdraw.isPending ? "Убираем…" : "Да, убрать"}
        </button>
      </div>
      <div className="text-[11px] text-status-busy">
        Удаление отменит сдачу и откатит полученный за неё опыт.
      </div>
    </div>
  );
}

export function VoiceRecorder({
  onUploaded,
  onClosed,
}: {
  onUploaded: () => void;
  /** GHG11(8.a): задание закрылось — зовём, чтобы блок записи свернулся. */
  onClosed?: () => void;
}) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [sending, setSending] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef<number>(0);
  const timerRef = useRef<number | null>(null);
  // Формат выбираем один раз при старте записи — он же решает, нужен ли remux.
  const formatRef = useRef<RecorderFormat | null>(null);

  const stopTimer = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const start = async () => {
    haptic("light");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Prefer OGG/OPUS (Firefox) или M4A (Safari); в Chrome получим WebM —
      // его переупакуем в OGG перед отправкой (`prepareVoiceBlob`).
      const fmt = pickRecorderFormat();
      formatRef.current = fmt;
      const recorder = new MediaRecorder(
        stream,
        fmt.mimeType ? { mimeType: fmt.mimeType } : undefined,
      );
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
      };
      recorder.start();
      recorderRef.current = recorder;
      startedAtRef.current = Date.now();
      setElapsed(0);
      setRecording(true);
      timerRef.current = window.setInterval(() => {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }, 500);
    } catch {
      haptic("error");
      void showAlert("Нет доступа к микрофону. Разреши его в настройках Telegram.");
    }
  };

  const stopAndSend = async () => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    haptic("medium");
    stopTimer();
    const durationMs = Date.now() - startedAtRef.current;
    setRecording(false);
    const blob: Blob = await new Promise((resolve) => {
      recorder.onstop = () => {
        recorder.stream.getTracks().forEach((t) => t.stop());
        resolve(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/ogg" }));
      };
      recorder.stop();
    });
    if (blob.size === 0) {
      haptic("error");
      void showAlert("Запись получилась пустой — попробуй ещё раз.");
      return;
    }
    setSending(true);
    const fmt = formatRef.current ?? pickRecorderFormat();
    try {
      // Chrome отдаёт WebM/OPUS — переупаковываем в OGG (Telegram иначе отбивает).
      const prepared = await prepareVoiceBlob(blob, fmt);
      const res = await uploadVoice(
        prepared.blob,
        durationMs / 1000,
        prepared.filename,
      );
      if (res.ok) {
        haptic("success");
        onUploaded();
      } else {
        haptic("error");
        void showAlert(statusText(res.status));
        if (res.status === "no_task" || res.status === "closed") onClosed?.();
      }
    } catch (e) {
      haptic("error");
      void showAlert(uploadErrorText(e instanceof Error ? e.message : ""));
    } finally {
      setSending(false);
    }
  };

  useEffect(() => () => { stopTimer(); }, []);

  if (sending) {
    return <div className="text-xs text-tg-hint">Отправляем…</div>;
  }

  return (
    <button
      type="button"
      onClick={() => (recording ? void stopAndSend() : void start())}
      className={[
        "w-full rounded-lg px-3 py-2 text-sm font-medium active:scale-[0.98]",
        recording
          ? "bg-status-busy/20 text-status-busy"
          : "bg-tg-button text-tg-button-text",
      ].join(" ")}
    >
      {recording ? `⏹ Стоп и отправить (${elapsed}с)` : "🎙 Записать голосовое"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Страховка: открытые задания без анонса в загруженной странице ленты
// ---------------------------------------------------------------------------

/**
 * Открытые призывы, чьего анонса нет среди записей ленты.
 *
 * Обычный путь — участие прямо в карточке анонса (`detail.activity`). Но в
 * режиме «только чат» (или если анонс уехал за первую страницу) строки в ленте
 * нет — тогда задание всё равно должно остаться доступным. `seenIds` — id
 * заданий, анонсы которых лента уже показала.
 */
export function OrphanActivities({ seenIds }: { seenIds: Set<number> }) {
  const q = useQuery({
    queryKey: QUERY_ACT,
    queryFn: fetchActivities,
    staleTime: 15_000,
  });
  const items = (q.data?.items ?? []).filter((it) => !seenIds.has(it.id));
  if (!q.data?.enabled || items.length === 0) return null;
  return (
    <>
      {items.map((it) => (
        <div
          key={it.id}
          className="rounded-2xl bg-tg-secondary-bg/60 p-3"
          data-testid="orphan-activity"
        >
          <div className="flex items-center gap-1.5 text-xs text-tg-hint">
            <span>⚡️</span>
            <span className="font-medium">Событие</span>
          </div>
          <div
            className="mt-1 text-sm text-tg-text [word-break:break-word]"
            dangerouslySetInnerHTML={{ __html: it.text }}
          />
          <ActivityResponse activity={it} />
        </div>
      ))}
    </>
  );
}

/** Тексты для статусов сервиса `voice.submit` (200-й ответ с `ok:false`). */
function statusText(status: string): string {
  switch (status) {
    case "no_task":
      return "Задание уже закрыто.";
    case "closed":
      return "Приём вариантов закрыт.";
    case "already":
      return "Ты уже сдавал вариант в этом задании.";
    case "late":
      return "Награду забрал тот, кто сдал первым.";
    case "silent":
      return "Ты немного опоздал.";
    case "unknown_user":
      return "Тебя нет в списке участников.";
    case "nothing":
      return "Ты ещё ничего не сдавал.";
    default:
      return "Не получилось принять голосовое.";
  }
}

/**
 * Тексты для ошибок Telegram (Э22). Бэкенд отдаёт машинный код, здесь —
 * человеческое объяснение и что именно сделать, чтобы получилось.
 */
function uploadErrorText(code: string): string {
  switch (code) {
    case "user_unreachable":
      return "Бот не может тебе написать в личку. Открой диалог с ботом, нажми «Start» и попробуй снова.";
    case "voice_forbidden":
      return "У тебя в Telegram отключены голосовые сообщения. Включи их в настройках приватности.";
    case "bad_format":
      return "Telegram не принял формат записи. Попробуй записать ещё раз — коротко, 5–30 секунд.";
    case "bad_audio":
      return "Запись получилась пустой — попробуй ещё раз.";
    case "too_big":
      return "Запись слишком длинная — сделай короче.";
    case "no_audio":
    case "not_webm":
    case "empty_webm":
      return "Не удалось распознать запись. Попробуй записать ещё раз.";
    case "send_failed":
      return "Telegram не принял голосовое — попробуй записать через чат с ботом.";
    default:
      return "Не получилось отправить голосовое. Попробуй ещё раз.";
  }
}

function formatUntil(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const ms = d.getTime() - Date.now();
  if (ms <= 0) return "истекли";
  const min = Math.round(ms / 60000);
  if (min < 60) return `ещё ${min} мин`;
  return `ещё ${Math.round(min / 60)} ч`;
}
