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
 * Почему шаг помечен своим id. Снятие шага (`history.back()` в уборке) тоже
 * присылает `popstate` — но уже следующему экземпляру хука. Без метки он
 * принимал его за «назад» пользователя: кабинет при перемонтировании
 * открывался и тут же сбрасывал раздел в корень, а карточка коллеги
 * закрывалась сама. Поэтому чужой шаг (метка другого экземпляра) игнорируется.
 *
 * `onClose` держим в ref: компоненты передают стрелочную функцию, и без этого
 * эффект перезапускался бы на каждой перерисовке, добавляя шаг истории.
 */

/** Уникальная метка шага: строка, а не `true`, чтобы отличить свои и чужие. */
let overlaySeq = 0;
/**
 * До какого момента ждём `popstate` от собственной уборки. `history.back()`
 * асинхронен, и его событие может прийти уже следующему экземпляру хука — тот
 * не должен принять его за «назад» пользователя. Окно короткое: если браузер
 * событие не прислал, защита снимается сама и не глотает следующий жест.
 */
let cleanupBackUntil = 0;
const CLEANUP_BACK_WINDOW_MS = 300;

/** Только для тестов: jsdom не присылает `popstate` на `history.back()`. */
export function resetBackCloseGuard(): void {
  cleanupBackUntil = 0;
}

export function useBackClose(onClose: () => void): void {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const id = `overlay-${++overlaySeq}`;
    let pushed = false;
    let popped = false;
    try {
      window.history.pushState(
        { ...window.history.state, semitaskOverlay: id },
        "",
      );
      pushed = true;
    } catch {
      // Приватный режим или запрет истории: оверлей всё равно закрывается
      // своей стрелкой, просто системная «назад» останется как была.
      pushed = false;
    }

    const onPop = (event: PopStateEvent) => {
      if (Date.now() < cleanupBackUntil) {
        cleanupBackUntil = 0;
        return;
      }
      const marker = (event.state as { semitaskOverlay?: unknown } | null)
        ?.semitaskOverlay;
      // Шаг снят другим оверлеем (или предыдущим экземпляром этого же) — это
      // не действие человека, закрывать текущий экран нельзя.
      if (typeof marker === "string" && marker !== id) return;
      popped = true;
      closeRef.current();
    };
    window.addEventListener("popstate", onPop);

    return () => {
      window.removeEventListener("popstate", onPop);
      // Снимаем только свой шаг: если история уже ушла дальше (оверлей
      // закрыли системной кнопкой или поверх открылся другой), `back()`
      // увёл бы приложение на предыдущую страницу и перезагрузил мини-апп.
      const stillOurs =
        (window.history.state as { semitaskOverlay?: unknown } | null)
          ?.semitaskOverlay === id;
      if (pushed && !popped && stillOurs) {
        cleanupBackUntil = Date.now() + CLEANUP_BACK_WINDOW_MS;
        try {
          window.history.back();
        } catch {
          /* история недоступна — не повод падать */
        }
      }
    };
  }, []);
}
