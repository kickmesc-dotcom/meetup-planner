import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";

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
        className="fixed inset-0 bg-black/40 z-40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.div
        key="sheet"
        className="fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-2xl bg-tg-bg p-4 pb-8 shadow-xl"
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
