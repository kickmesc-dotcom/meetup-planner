import { motion } from "framer-motion";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";

export default function ActionBar() {
  const setShowAuto = useUI((s) => s.setShowAutoPickSheet);
  const setShowLoser = useUI((s) => s.setShowLoserSheet);
  const setShowPoll = useUI((s) => s.setShowPollSheet);

  const tap = (fn: () => void) => () => {
    haptic("light");
    fn();
  };

  return (
    <div className="grid grid-cols-3 gap-2 border-t border-tg-secondary-bg bg-tg-bg p-2">
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
        label="🎲 Лох дня"
      />
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
        "min-h-12 rounded-xl py-3 text-sm font-medium",
        primary
          ? "bg-tg-button text-tg-button-text shadow-sm"
          : "bg-tg-secondary-bg",
      ].join(" ")}
    >
      {label}
    </motion.button>
  );
}
