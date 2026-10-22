import { useEffect, useState } from "react";

/**
 * Порог «широкого» экрана. Совпадает с `lg` в Tailwind, поэтому CSS и JS
 * переключаются в один и тот же момент — без щели, где сайдбар уже нарисован,
 * а нижняя полоса ещё видна.
 */
export const DESKTOP_QUERY = "(min-width: 1024px)";

function readMatch(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(DESKTOP_QUERY).matches;
}

/**
 * `true`, когда приложение открыто на широком экране (ПК/ноутбук/планшет
 * альбомом). Тогда вместо нижней полосы показываем сайдбар и широкую область,
 * как в обычной админ-панели.
 *
 * Почему медиа-запрос, а не ширина Telegram-окна: в браузере (прямая ссылка)
 * Telegram-объекта нет вовсе, а окно мини-аппа на ПК пользователь может
 * растянуть руками — в обоих случаях верный ответ даёт viewport.
 */
export function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState<boolean>(readMatch);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mq = window.matchMedia(DESKTOP_QUERY);
    const onChange = () => setIsDesktop(mq.matches);
    // Синхронно сверяемся при монтировании: между первым рендером и эффектом
    // окно могли успеть поменять.
    onChange();

    // Safari < 14 знает только addListener — без него каркас залипнет на
    // стартовом значении после поворота экрана/растягивания окна.
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    }
    mq.addListener?.(onChange);
    return () => mq.removeListener?.(onChange);
  }, []);

  return isDesktop;
}
