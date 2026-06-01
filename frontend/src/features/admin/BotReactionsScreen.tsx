import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchBotReactions,
  updateBotReactions,
  type BotReactionsSettings,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

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
 */
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
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
          <div className="text-xs text-tg-hint mb-2">
            Бот отвечает рандомной шизо-цитатой на упоминание и/или reply.
          </div>

          <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
            <div className="min-w-0">
              <div className="text-sm text-tg-text">@-упоминание</div>
              <div className="text-[11px] text-tg-hint">
                На тег <code>@бот</code> бот отвечает фразой.
              </div>
            </div>
            <Switch
              checked={draft.mention_enabled}
              onChange={(v) => {
                haptic("selection");
                setField("mention_enabled", v);
              }}
            />
          </div>

          <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
            <div className="min-w-0">
              <div className="text-sm text-tg-text">Reply на любое сообщение бота</div>
              <div className="text-[11px] text-tg-hint">
                На любой ответ-реплай на сообщение бота — бот отвечает фразой
                (включая reply к собственным цитатам).
              </div>
            </div>
            <Switch
              checked={draft.reply_all_enabled}
              onChange={(v) => {
                haptic("selection");
                setField("reply_all_enabled", v);
              }}
            />
          </div>

          <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
            <div className="min-w-0">
              <div className="text-sm text-tg-text">Reply, кроме рандом-цитат</div>
              <div className="text-[11px] text-tg-hint">
                Бот отвечает на reply к своим сообщениям, кроме случаев, когда
                оригинал — рандом-цитата. Работает независимо от верхнего тогла.
              </div>
            </div>
            <Switch
              checked={draft.reply_except_phrases_enabled}
              onChange={(v) => {
                haptic("selection");
                setField("reply_except_phrases_enabled", v);
              }}
            />
          </div>
        </section>
      )}
    </SubScreen>
  );
}

function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
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
