import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
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

  // §7 `interruptible`: закрытие — это состояние, а не мгновенное удаление из
  // дерева. Тап во время анимации входа не игнорируется и не ждёт её конца:
  // шторка начинает уезжать с текущей позиции. Флаг `closing` заодно не даёт
  // второму тапу запустить второе закрытие.
  const [closing, setClosing] = useState(false);
  const finished = useRef(false);
  const confirming = useRef(false);

  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    onClose();
  }, [onClose]);

  const close = useCallback(() => {
    if (finished.current) return;
    setClosing(true);
  }, []);

  // Страховка: если выход не проиграется (старый WebView, отключённые
  // анимации), шторка всё равно закроется, а не останется висеть.
  useEffect(() => {
    if (!closing) return;
    const timer = window.setTimeout(finish, 260);
    return () => window.clearTimeout(timer);
  }, [closing, finish]);

  const requestClose = useCallback(() => {
    if (closing || finished.current || confirming.current) return;
    if (!dirty) {
      close();
      return;
    }
    confirming.current = true;
    void showConfirm(tx("Закрыть без сохранения? Введённое не сохранится.")).then(
      (ok) => {
        confirming.current = false;
        if (ok) close();
      },
    );
  }, [close, closing, dirty, tx]);

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
    <AnimatePresence onExitComplete={finish}>
      {!closing && [
        <motion.div
          key="backdrop"
          data-testid="sheet-backdrop"
          className="fixed inset-0 bg-black/40 z-sheet"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          // §7 `exit-faster-than-enter`: уход короче появления — шторка не
          // задерживает человека, который уже закрыл её.
          exit={{ opacity: 0, transition: { duration: 0.1 } }}
          onClick={requestClose}
        />,
        <motion.div
          key="sheet"
          data-testid="sheet"
          role="dialog"
          aria-modal="true"
          aria-label={title}
          // Низ шторки — с запасом на home-индикатор: иначе на iPhone в режиме
          // «на домашнем экране» последняя кнопка оказывается под полосой
          // системы, и нажать её нельзя (M1, docs/MOBILE_PARALLEL.md).
          // §9 `scroll-behavior`: `overscroll-contain` не отдаёт прокрутку
          // странице под шторкой — иначе на телефоне она «уезжает» вместе с
          // содержимым листа, и человек теряет место, где был.
          className="fixed inset-x-0 bottom-0 z-overlay max-h-[85vh] overflow-y-auto overscroll-contain rounded-t-card bg-tg-bg p-4 pb-8 shadow-sheet"
          style={{ paddingBottom: `calc(2rem + ${SAFE_AREA_BOTTOM})` }}
          initial={{ y: "100%" }}
          animate={{ y: 0 }}
          exit={{ y: "100%", transition: { duration: 0.16, ease: "easeIn" } }}
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
        </motion.div>,
      ]}
    </AnimatePresence>
  );
}
