import { useCallback, useEffect, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { SAFE_AREA_BOTTOM } from "@/tg/safeArea";
import Icon from "@/components/Icon";
import { showConfirm } from "@/tg/webapp";
import { useTx } from "@/i18n";

interface Props {
  title: string;
  onClose: () => void;
  /**
   * В шторке есть несохранённый ввод. §8 `sheet-dismiss-confirm`: тап мимо
   * на телефоне — обычное движение пальца, и без вопроса человек терял
   * написанную заметку или текст проблемы.
   */
  dirty?: boolean;
  children: ReactNode;
}

export default function BottomSheet({
  title,
  onClose,
  dirty = false,
  children,
}: Props) {
  const { tx } = useTx();

  const requestClose = useCallback(() => {
    if (!dirty) {
      onClose();
      return;
    }
    void showConfirm(tx("Закрыть без сохранения? Введённое не сохранится.")).then(
      (ok) => {
        if (ok) onClose();
      },
    );
  }, [dirty, onClose, tx]);

  // §1 `escape-routes` / §9 `modal-escape`: шторка закрывается клавишей Escape,
  // а не только тапом по фону. На телефоне фон легко перекрыть пальцем, на
  // компьютере у человека без мыши другого выхода из шторки не было вовсе.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [requestClose]);

  return (
    <AnimatePresence>
      <motion.div
        key="backdrop"
        data-testid="sheet-backdrop"
        className="fixed inset-0 bg-black/40 z-40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={requestClose}
      />
      <motion.div
        key="sheet"
        data-testid="sheet"
        role="dialog"
        aria-modal="true"
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
        <button
          type="button"
          onClick={requestClose}
          aria-label={tx("Закрыть")}
          className="absolute right-2 top-2 grid h-11 w-11 place-items-center rounded-full text-tg-hint press"
        >
          <Icon name="close" size={18} />
        </button>
        <div className="mb-3 pr-12 text-base font-semibold">{title}</div>
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
