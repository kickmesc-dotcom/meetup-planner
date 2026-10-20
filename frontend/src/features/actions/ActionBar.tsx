import { useState } from "react";
import { motion } from "framer-motion";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";

/**
 * Кнопки действий календаря: авто-подбор и опрос по встрече.
 *
 * Прогон «рандомной фразы» убран вместе с модулем: бот больше не постит
 * случайные реплики, а календарь — про смены и встречи.
 */
export default function ActionBar() {
  // H.2 (19.06 #2): панель схлопывается в строку со стрелкой — на телефоне
  // кнопки съедали четверть экрана. По умолчанию РАЗВЁРНУТА (как приветствие).
  const [open, setOpen] = useState(true);

  const setShowAuto = useUI((s) => s.setShowAutoPickSheet);
  const setShowPoll = useUI((s) => s.setShowPollSheet);

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
        className="flex w-full items-center justify-center gap-1.5 border-t border-tg-secondary-bg bg-tg-bg px-2 py-2 text-xs text-tg-hint"
      >
        <span aria-hidden>▴</span> Кнопки действий — развернуть
      </button>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 border-t border-tg-secondary-bg bg-tg-bg p-2">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen(false);
        }}
        aria-expanded
        title="Свернуть кнопки действий"
        className="col-span-full -mt-1 flex items-center justify-center gap-1 text-2xs text-tg-hint"
      >
        <span aria-hidden>▾</span> свернуть кнопки
      </button>
      <ActionBtn
        onClick={tap(() => setShowAuto(true))}
        label="🎯 Авто-подбор"
        primary
      />
      <ActionBtn onClick={tap(() => setShowPoll(true))} label="📊 Опрос" />
    </div>
  );
}

function ActionBtn({
  onClick,
  label,
  primary,
}: {
  onClick: () => void;
  label: string;
  primary?: boolean;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileTap={{ scale: 0.94 }}
      transition={{ type: "spring", stiffness: 500, damping: 22 }}
      className={[
        "min-h-12 rounded-xl py-3 text-sm font-medium inline-flex items-center justify-center gap-1.5",
        primary
          ? "bg-tg-button text-tg-button-text shadow-sm"
          : "bg-tg-secondary-bg",
      ].join(" ")}
    >
      {label}
    </motion.button>
  );
}
