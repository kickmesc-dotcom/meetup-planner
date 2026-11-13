import { useEffect } from "react";

import { useUI, type Tab } from "@/store/ui";

/**
 * Системная «назад» возвращает предыдущую вкладку.
 *
 * Зачем. Смена вкладок не писалась в историю: телефонная кнопка «назад» (или
 * жест Safari) закрывала мини-апп с любой вкладки, кроме корневой. Человек,
 * ушедший из «Задач» в «Ленту», на «назад» выходил из приложения, а не
 * возвращался к задачам.
 *
 * Как. `setTab` пишет шаг истории; `popstate` читает вкладку из состояния и
 * возвращает её без нового шага. Оверлеи (`useBackClose`) продолжают работать:
 * у них свой шаг, и закрытие оверлея возвращает ту же вкладку, с которой его
 * открыли.
 */
export function useTabHistory(): void {
  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      const state = event.state as { semitaskTab?: unknown } | null;
      const tab = state?.semitaskTab;
      if (typeof tab !== "string") return;
      useUI.getState().setTab(tab as Tab, { history: false });
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
}
