import type { ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * VISUAL_AUDIT P3.17: мягкая смена вкладки.
 *
 * Раньше переключение вкладок было рывком: React просто подменял дерево, и
 * экран появлялся целиком. Здесь 120 мс opacity — этого хватает, чтобы переход
 * читался как «переход», а не как мигание, и при этом навигация не тормозит:
 * задержки нет, старый экран уходит сразу.
 *
 * §7 `excessive-motion`: подъём на 4px убран. При смене вкладки двигались сразу
 * три вещи — подчёркивание в полосе, цвет подписи и экран. Осталось одно
 * движение на действие: экран проявляется, остальное переключается без анимации.
 *
 * Почему framer-motion, а не CSS-класс: DESIGN_SYSTEM §7 требует анимации входа
 * через framer-motion (Tailwind-плагина анимаций в проекте нет). Хук
 * `useReducedMotion` — единственный честный способ выключить движение, когда
 * ОС просит `prefers-reduced-motion: reduce`: в этом случае `initial={false}`,
 * то есть контент сразу в конечном состоянии.
 *
 * Ключ `key` ставит вызывающий код (`<TabTransition key={tab}>`), иначе React
 * переиспользует компонент и входа не будет.
 */
export default function TabTransition({ children }: { children: ReactNode }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.12, ease: "easeOut" }}
      className="flex min-h-0 flex-1 flex-col"
    >
      {children}
    </motion.div>
  );
}
