import { useEffect, useRef } from "react";

/**
 * Закрыть оверлей системной кнопкой «назад».
 *
 * Зачем. Карточка коллеги и дашборд отдела рисуются поверх ленты и умеют
 * закрываться только своей стрелкой. Телефонная кнопка «назад» (Android, жест
 * Safari в веб-версии) при этом закрывала мини-апп целиком: человек выходил из
 * приложения вместо возврата к ленте с прежними фильтрами и прокруткой —
 * «после закрытия карточки возвращаешься не туда, где был».
 *
 * Как. При открытии добавляем шаг в историю; `popstate` закрывает оверлей, а не
 * приложение. Закрытие своей стрелкой снимает добавленный шаг, иначе следующее
 * «назад» открывало бы карточку заново.
 *
 * `onClose` держим в ref: компоненты передают стрелочную функцию, и без этого
 * эффект перезапускался бы на каждой перерисовке, добавляя шаг истории.
 */
export function useBackClose(onClose: () => void): void {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    let pushed = false;
    let popped = false;
    try {
      window.history.pushState(
        { ...window.history.state, semitaskOverlay: true },
        "",
      );
      pushed = true;
    } catch {
      // Приватный режим или запрет истории: оверлей всё равно закрывается
      // своей стрелкой, просто системная «назад» останется как была.
      pushed = false;
    }

    const onPop = () => {
      popped = true;
      closeRef.current();
    };
    window.addEventListener("popstate", onPop);

    return () => {
      window.removeEventListener("popstate", onPop);
      if (pushed && !popped) {
        try {
          window.history.back();
        } catch {
          /* история недоступна — не повод падать */
        }
      }
    };
  }, []);
}
