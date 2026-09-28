import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchBotReactions,
  fetchReplyPhrases,
  updateBotReactions,
  updateReplyPhrases,
  type BotReactionsSettings,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";
import PhrasePoolEditor from "./PhrasePoolEditor";
import { Switch } from "@/components/Checkbox";

interface Props {
  onBack: () => void;
}

const errAlert = (e: unknown) => {
  haptic("error");
  void showAlert(humanizeApiError(e));
};

/**
 * GHG7 P2.3.f: реакции бота вынесены из подсекции «Запланированные публикации»
 * в отдельное меню верхнего уровня. Компонент самодостаточен — свой query
 * `["admin","bot-reactions"]`, авто-save при каждом тогле (как было раньше).
 * Логика реакций (GHG6 E9): три master-toggle на упоминание/reply.
 *
 * GHG8 T2.3/п.13: переподписаны контролы. @-упоминание — независимый тогл (а).
 * Поведение reply раньше показывалось двумя путаными независимыми свитчами
 * (`reply_all` / `reply_except_phrases`), хотя в бэке это ВЗАИМОИСКЛЮЧАЮЩИЙ
 * выбор (`reply_all` перекрывает `except`). Теперь это один сегментированный
 * выбор из трёх режимов: Выкл / На все reply (б) / Кроме рандом-цитат (в, дефолт).
 * Маппинг радио↔флаги без потерь, контракт `BotReactionsSettings` и механизм
 * отправки НЕ тронуты (бэк читает те же 3 bool).
 */
type ReplyMode = "off" | "all" | "except";

// reply_all перекрывает except в бэке → при чтении all имеет приоритет.
function toReplyMode(s: BotReactionsSettings): ReplyMode {
  if (s.reply_all_enabled) return "all";
  if (s.reply_except_phrases_enabled) return "except";
  return "off";
}

// Канонический набор флагов под выбранный режим (чистый, без «висящих» битов).
function replyModeFlags(
  m: ReplyMode,
): Pick<BotReactionsSettings, "reply_all_enabled" | "reply_except_phrases_enabled"> {
  return {
    reply_all_enabled: m === "all",
    reply_except_phrases_enabled: m === "except",
  };
}

const REPLY_MODES: { value: ReplyMode; label: string; hint: string }[] = [
  { value: "off", label: "Выкл", hint: "Бот не отвечает на reply к своим сообщениям." },
  {
    value: "all",
    label: "На все reply",
    hint: "Отвечает на любой reply к своему сообщению — включая reply к рандом-цитатам.",
  },
  {
    value: "except",
    label: "Кроме цитат",
    hint: "Отвечает на reply к своим сообщениям, КРОМЕ reply к рандом-цитатам (чтобы шизо-цитату можно было прокомментировать без ответа бота). Режим по умолчанию.",
  },
];

export default function BotReactionsScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "bot-reactions"],
    queryFn: fetchBotReactions,
  });
  const [draft, setDraft] = useState<BotReactionsSettings | null>(null);
  useEffect(() => {
    if (q.data) setDraft({ ...q.data });
  }, [q.data]);

  // H.1: отдельный пул коротких реплик бота (reply/mention).
  const rp = useQuery({
    queryKey: ["admin", "reply-phrases"],
    queryFn: fetchReplyPhrases,
    staleTime: 30_000,
  });
  const savePhrases = useMutation({
    mutationFn: updateReplyPhrases,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "reply-phrases"], data);
    },
    onError: errAlert,
  });

  const save = useMutation({
    mutationFn: updateBotReactions,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "bot-reactions"], data);
    },
    onError: errAlert,
  });

  const setField = (key: keyof BotReactionsSettings, v: boolean) => {
    if (!draft) return;
    const next = { ...draft, [key]: v };
    setDraft(next);
    save.mutate(next);
  };

  const setReplyMode = (m: ReplyMode) => {
    if (!draft) return;
    const next = { ...draft, ...replyModeFlags(m) };
    setDraft(next);
    save.mutate(next);
  };

  return (
    <SubScreen
      title="🤖 Реакции бота"
      subtitle="Ответы на упоминание и reply"
      onBack={onBack}
    >
      {q.isPending || !draft ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={3} />
        </section>
      ) : (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
          <div className="text-xs text-tg-hint">
            Бот отвечает короткой репликой из пула ниже на упоминание и/или reply.
          </div>

          {/* (а) @-упоминание — независимый тогл */}
          <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
            <div className="min-w-0">
              <div className="text-sm text-tg-text">Отвечать на @-упоминание</div>
              <div className="text-[11px] text-tg-hint">
                Когда в сообщении тегнут <code>@бот</code> — бот отвечает фразой.
                Работает независимо от настройки reply ниже.
              </div>
            </div>
            <Switch
              checked={draft.mention_enabled}
              onChange={(v) => setField("mention_enabled", v)}
            />
          </div>

          {/* (б)/(в) reply — взаимоисключающий выбор режима */}
          <div className="rounded-md bg-tg-bg/40 px-2 py-2 space-y-2">
            <div className="text-sm text-tg-text">Ответ на reply сообщений бота</div>
            <div className="flex gap-1 rounded-lg bg-tg-secondary-bg/80 p-0.5">
              {REPLY_MODES.map((m) => {
                const active = toReplyMode(draft) === m.value;
                return (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => {
                      haptic("selection");
                      setReplyMode(m.value);
                    }}
                    aria-pressed={active}
                    className={[
                      "flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
                      active
                        ? "bg-tg-button text-tg-button-text"
                        : "text-tg-hint",
                    ].join(" ")}
                  >
                    {m.label}
                  </button>
                );
              })}
            </div>
            <div className="text-[11px] text-tg-hint">
              {REPLY_MODES.find((m) => m.value === toReplyMode(draft))?.hint}
            </div>
          </div>
        </section>
      )}

      {/* H.1: отдельный пул ответов на reply/упоминание */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">💬 Фразы-ответы</div>
        <div className="text-xs text-tg-hint mb-2">
          Короткие реплики, которыми бот отвечает на reply/упоминание (собственный
          пул вместо общей шизо-цитаты). Пусто → бот молчит.
        </div>
        {rp.isPending || !rp.data ? (
          <ListSkeleton rows={4} />
        ) : (
          <PhrasePoolEditor
            pool="reply_phrases"
            initial={rp.data.phrases}
            isPending={savePhrases.isPending}
            placeholder="например: Так точно 🫡"
            emptyHint="Пусто — бот не отвечает на reply/упоминание."
            onSave={(list) => savePhrases.mutate(list)}
          />
        )}
      </section>
    </SubScreen>
  );
}

