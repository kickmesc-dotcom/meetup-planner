import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { SAFE_AREA_BOTTOM } from "@/tg/safeArea";

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export default function BottomSheet({ title, onClose, children }: Props) {
  return (
    <AnimatePresence>
      <motion.div
        key="backdrop"
        data-testid="sheet-backdrop"
        className="fixed inset-0 bg-black/40 z-40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.div
        key="sheet"
        data-testid="sheet"
        role="dialog"
        aria-label={title}
        // Низ шторки — с запасом на home-индикатор: иначе на iPhone в режиме
        // «на домашнем экране» последняя кнопка оказывается под полосой
        // системы, и нажать её нельзя (M1, docs/MOBILE_PARALLEL.md).
        className="fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-card bg-tg-bg p-4 pb-8 shadow-xl"
        style={{ paddingBottom: `calc(2rem + ${SAFE_AREA_BOTTOM})` }}
        initial={{ y: "100%" }}
        animate={{ y: 0 }}
        exit={{ y: "100%" }}
        transition={{ type: "spring", damping: 30, stiffness: 320 }}
      >
        <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-tg-hint/40" />
        <div className="mb-3 text-base font-semibold">{title}</div>
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
