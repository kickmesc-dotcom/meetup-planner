import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  answerActivity,
  fetchActivities,
  fetchVoiceAudioUrl,
  fetchVoiceCurrent,
  uploadVoice,
  withdrawVoice,
  type GameActivity,
  type VoiceSubmission,
} from "@/api/game";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * Э21: активности прямо в приложении.
 *
 * В софт-режимах («ачивки в приложение» / «всё в приложение») бот не пишет в
 * чат, но механики должны жить. Поэтому лента — «внутренняя расширенная копия
 * чата»: тут закрываем вопросы кнопкой/текстом и возимся с голосовыми.
 *
 * Панель самодостаточна: сама грузит вопросы и текущее голосовое задание и
 * прячется, если ничего нет / всё выключено.
 */
export default function ActivitiesPanel() {
  return (
    <div className="space-y-2">
      <QuestionsBlock />
      <VoiceBlock />
    </div>
  );
}

const QUERY_ACT = ["game-activities"] as const;
const QUERY_VOICE = ["game-voice"] as const;

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: QUERY_ACT });
  void qc.invalidateQueries({ queryKey: QUERY_VOICE });
  void qc.invalidateQueries({ queryKey: ["game-feed"] });
  void qc.invalidateQueries({ queryKey: ["me"] });
}

// ---------------------------------------------------------------------------
// Вопросы (случайные события)
// ---------------------------------------------------------------------------

function QuestionsBlock() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: QUERY_ACT, queryFn: fetchActivities, staleTime: 15_000 });
  const [answer, setAnswer] = useState<{ ok: boolean; xp: number } | null>(null);

  const send = useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) => answerActivity(id, text),
    onSuccess: (res) => {
      setAnswer({ ok: res.ok, xp: res.xp });
      haptic(res.ok ? "success" : "error");
      invalidateAll(qc);
    },
    onError: () => haptic("error"),
  });

  const items = q.data?.items ?? [];
  if (!q.data?.enabled || items.length === 0) return null;

  return (
    <>
      {items.map((it) => (
        <QuestionCard
          key={it.id}
          activity={it}
          busy={send.isPending}
          answered={answer}
          onAnswer={(text) => send.mutate({ id: it.id, text })}
        />
      ))}
    </>
  );
}

function QuestionCard({
  activity,
  onAnswer,
  busy,
  answered,
}: {
  activity: GameActivity;
  onAnswer: (text: string) => void;
  busy: boolean;
  answered: { ok: boolean; xp: number } | null;
}) {
  const [text, setText] = useState("");
  return (
    <div className="rounded-2xl bg-tg-secondary-bg/60 p-3">
      <div className="flex items-center gap-1.5 text-xs text-tg-hint">
        <span>⚡️</span>
        <span className="font-medium">Событие</span>
        <span className="ml-auto shrink-0">{formatUntil(activity.expires_at)}</span>
      </div>
      <div
        className="mt-1 text-sm text-tg-text [word-break:break-word]"
        dangerouslySetInnerHTML={{ __html: activity.text }}
      />
      {answered && (
        <div
          className={[
            "mt-2 rounded-lg px-2 py-1.5 text-xs font-medium",
            answered.ok
              ? "bg-status-free/15 text-status-free"
              : "bg-status-busy/15 text-status-busy",
          ].join(" ")}
        >
          {answered.ok ? "✅ Засчитано! Опыт уже в профиле." : "Не подошло — попробуй другой ответ."}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {activity.options.map((o) => (
          <button
            key={o.label}
            type="button"
            disabled={busy}
            onClick={() => {
              haptic("selection");
              onAnswer(o.label);
            }}
            className="rounded-full bg-tg-bg/70 px-3 py-1.5 text-xs font-medium text-tg-text active:scale-[0.98] disabled:opacity-50"
          >
            {o.label}
            {o.xp > 0 && <span className="ml-1 text-tg-hint">+{o.xp}</span>}
          </button>
        ))}
      </div>
      {activity.needs_text && (
        <div className="mt-2 flex gap-1.5">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Твой ответ…"
            className="min-w-0 flex-1 rounded-lg bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
          />
          <button
            type="button"
            disabled={busy || !text.trim()}
            onClick={() => {
              haptic("selection");
              onAnswer(text.trim());
              setText("");
            }}
            className="shrink-0 rounded-lg bg-tg-button px-3 py-1.5 text-sm font-medium text-tg-button-text active:scale-[0.98] disabled:opacity-50"
          >
            Отправить
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Голосовое задание
// ---------------------------------------------------------------------------

function VoiceBlock() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: QUERY_VOICE, queryFn: fetchVoiceCurrent, staleTime: 15_000 });
  const data = q.data;

  const withdraw = useMutation({
    mutationFn: withdrawVoice,
    onSuccess: () => {
      haptic("medium");
      invalidateAll(qc);
    },
    onError: () => haptic("error"),
  });

  if (!data?.enabled || data.task_id === null) return null;

  return (
    <div className="rounded-2xl bg-tg-secondary-bg/60 p-3">
      <div className="flex items-center gap-1.5 text-xs text-tg-hint">
        <span>🎙</span>
        <span className="font-medium">Голосовое задание</span>
        <span className="ml-auto shrink-0">
          +{data.reward} XP · {formatUntil(data.expires_at)}
        </span>
      </div>
      <div className="mt-0.5 text-sm font-medium">{data.title}</div>

      <div className="mt-2 space-y-1.5">
        {data.submissions.map((s) => (
          <SubmissionRow key={s.id} submission={s} />
        ))}
        {data.submissions.length === 0 && (
          <div className="text-xs text-tg-hint">Пока никто не сдал — будь первым.</div>
        )}
      </div>

      <div className="mt-2">
        {data.my_submission_id !== null ? (
          <div className="flex items-center gap-2">
            <span className="flex-1 text-xs text-tg-hint">Твой вариант принят.</span>
            <button
              type="button"
              disabled={withdraw.isPending}
              onClick={() => {
                if (!confirm("Убрать свой вариант? Опыт останется, но сдать заново уже нельзя.")) return;
                withdraw.mutate();
              }}
              className="shrink-0 rounded-lg bg-status-busy/15 px-3 py-1.5 text-xs font-medium text-status-busy disabled:opacity-50"
            >
              Убрать
            </button>
          </div>
        ) : (
          <VoiceRecorder onUploaded={() => invalidateAll(qc)} />
        )}
      </div>
    </div>
  );
}

function SubmissionRow({ submission }: { submission: VoiceSubmission }) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const play = async () => {
    haptic("light");
    if (url) {
      setUrl(null);
      URL.revokeObjectURL(url);
      return;
    }
    setLoading(true);
    try {
      const blobUrl = await fetchVoiceAudioUrl(submission.id);
      setUrl(blobUrl);
    } catch {
      haptic("error");
    } finally {
      setLoading(false);
    }
  };

  // Освобождаем blob-URL при размонтировании, чтобы не текла память.
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  return (
    <div className="flex items-center gap-2 rounded-lg bg-tg-bg/50 px-2 py-1.5">
      <button
        type="button"
        onClick={play}
        disabled={loading}
        className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-1 text-sm disabled:opacity-50"
        aria-label="Прослушать"
      >
        {loading ? "…" : url ? "⏸" : "▶️"}
      </button>
      <span className="min-w-0 flex-1 truncate text-sm">
        {submission.user_name ?? "участник"}
        {submission.is_mine && <span className="text-tg-hint"> (ты)</span>}
      </span>
      {submission.duration != null && (
        <span className="shrink-0 text-xs tabular-nums text-tg-hint">
          {submission.duration}с
        </span>
      )}
      {url && <audio src={url} autoPlay onEnded={() => { URL.revokeObjectURL(url); setUrl(null); }} />}
    </div>
  );
}

function VoiceRecorder({ onUploaded }: { onUploaded: () => void }) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [sending, setSending] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef<number>(0);
  const timerRef = useRef<number | null>(null);

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
      const recorder = new MediaRecorder(stream);
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
    if (blob.size === 0) return;
    setSending(true);
    try {
      const res = await uploadVoice(blob, durationMs / 1000);
      if (res.ok) {
        haptic("success");
        onUploaded();
      } else {
        haptic("error");
        void showAlert(statusText(res.status));
      }
    } catch (e) {
      haptic("error");
      void showAlert(
        e instanceof Error && e.message === "send_failed"
          ? "Telegram не принял голосовое — попробуй записать через чат с ботом."
          : "Не получилось отправить голосовое.",
      );
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
    default:
      return "Не получилось принять голосовое.";
  }
}

function formatUntil(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const ms = d.getTime() - Date.now();
  if (ms <= 0) return "истекло";
  const min = Math.round(ms / 60000);
  if (min < 60) return `ещё ${min} мин`;
  return `ещё ${Math.round(min / 60)} ч`;
}
