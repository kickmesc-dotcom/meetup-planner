import { useState } from "react";
import { motion } from "framer-motion";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { fetchMe } from "@/api/availability";
import { triggerRandomPhrases } from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { Spinner } from "@/components/Spinner";

export default function ActionBar() {
  // H.2 (19.06 #2): панель кнопок схлопывается в строку со стрелкой — на
  // телефоне 4 кнопки съедали четверть экрана. По умолчанию РАЗВЁРНУТА
  // (как и приветствие), состояние живёт до перезагрузки мини-аппа.
  const [open, setOpen] = useState(true);

  const setShowAuto = useUI((s) => s.setShowAutoPickSheet);
  const setShowLoser = useUI((s) => s.setShowLoserSheet);
  const setShowPoll = useUI((s) => s.setShowPollSheet);

  // Q: кнопка «Прогон фразы» — только админам (эндпоинт admin-only).
  const meQ = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60 * 1000 });
  const isAdmin = !!meQ.data?.is_admin;

  const phrases = useMutation({
    mutationFn: triggerRandomPhrases,
    onSuccess: () => {
      haptic("success");
      void showAlert("Прогон фраз запущен.");
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const tap = (fn: () => void) => () => {
    haptic("light");
    fn();
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen(true);
        }}
        aria-expanded={false}
        className="flex w-full items-center justify-center gap-1.5 border-t border-tg-secondary-bg bg-tg-bg px-2 py-2 text-[11px] text-tg-hint"
      >
        <span aria-hidden>▴</span> Кнопки действий — развернуть
      </button>
    );
  }

  return (
    <div
      className={[
        "grid gap-2 border-t border-tg-secondary-bg bg-tg-bg p-2",
        isAdmin ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-3",
      ].join(" ")}
    >
      {/* H.2: симметрично приветствию — своей строкой, а не поверх кнопок. */}
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen(false);
        }}
        aria-expanded
        title="Свернуть кнопки действий"
        className="col-span-full -mt-1 flex items-center justify-center gap-1 text-[10px] text-tg-hint"
      >
        <span aria-hidden>▾</span> свернуть кнопки
      </button>
      <ActionBtn
        onClick={tap(() => setShowAuto(true))}
        label="🎯 Авто-подбор"
        primary
      />
      <ActionBtn
        onClick={tap(() => setShowPoll(true))}
        label="📊 Опрос"
      />
      <ActionBtn
        onClick={tap(() => setShowLoser(true))}
        label="🤡 Автолох"
      />
      {isAdmin && (
        <ActionBtn
          onClick={() => {
            haptic("light");
            phrases.mutate();
          }}
          label="🗯 Прогон фразы"
          loading={phrases.isPending}
        />
      )}
    </div>
  );
}

function ActionBtn({
  onClick,
  label,
  primary,
  loading,
}: {
  onClick: () => void;
  label: string;
  primary?: boolean;
  loading?: boolean;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={loading}
      whileTap={{ scale: 0.94 }}
      transition={{ type: "spring", stiffness: 500, damping: 22 }}
      className={[
        "min-h-12 rounded-xl py-3 text-sm font-medium inline-flex items-center justify-center gap-1.5 disabled:opacity-60",
        primary
          ? "bg-tg-button text-tg-button-text shadow-sm"
          : "bg-tg-secondary-bg",
      ].join(" ")}
    >
      {loading && <Spinner />}
      {label}
    </motion.button>
  );
}
