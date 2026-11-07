import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

/**
 * §3 QOL: место в длинном списке переживает уход на другую вкладку.
 *
 * Экраны приложения переключаются условием `tab === …`, то есть размонтируются
 * целиком. Без этого хука человек, открывший карточку из середины ленты и
 * вернувшийся назад, оказывался в самом верху — и заново искал своё место.
 *
 * Почему `sessionStorage`, а не `localStorage`: место в ленте — состояние
 * текущего визита. На следующее утро лента уже другая, и вчерашняя позиция
 * была бы случайным числом, а не «где я остановился».
 *
 * Почему восстановление ждёт `ready`: до прихода данных высота списка нулевая,
 * и браузер обрезал бы `scrollTop` до нуля. Флаг `ready` — это «данные уже
 * отрисованы», а не «запрос начался».
 */
const KEY_PREFIX = "scroll:";

/** Порог, после которого «Наверх» появляется: первый экран уже пройден. */
const SHOW_TOP_AFTER = 600;

function readTop(key: string): number {
  try {
    const value = Number(window.sessionStorage.getItem(KEY_PREFIX + key));
    return Number.isFinite(value) && value > 0 ? value : 0;
  } catch {
    // Приватный режим и WebView с запретом хранилища: прокрутка просто начнётся
    // сверху, экран от этого не ломается.
    return 0;
  }
}

function writeTop(key: string, top: number): void {
  try {
    window.sessionStorage.setItem(KEY_PREFIX + key, String(Math.round(top)));
  } catch {
    /* см. `readTop` — удобство, не обязанность */
  }
}

export function useScrollRestore(
  key: string,
  ready: boolean,
  ref: RefObject<HTMLDivElement | null>,
): { showTop: boolean; scrollToTop: () => void } {
  const [showTop, setShowTop] = useState(false);
  const restored = useRef(false);
  const lastTop = useRef(0);

  // Новый ключ — новый список: позицию восстанавливаем заново, а не считаем,
  // что уже восстановили (иначе смена вида журнала оставляла бы старый сдвиг).
  useEffect(() => {
    restored.current = false;
    lastTop.current = 0;
  }, [key]);

  useEffect(() => {
    if (!ready || restored.current) return;
    const el = ref.current;
    if (!el) return;
    restored.current = true;
    const top = readTop(key);
    el.scrollTop = top;
  }, [key, ready, ref]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let frame = 0;
    const onScroll = () => {
      setShowTop(el.scrollTop > SHOW_TOP_AFTER);
      if (frame) return;
      // Один кадр — одна запись: обработчик скролла вызывается десятки раз в
      // секунду, и синхронный `sessionStorage` в нём заметно подтормаживал бы.
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        lastTop.current = el.scrollTop;
      });
    };
    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
      writeTop(key, el.scrollTop || lastTop.current);
    };
  }, [key, ref]);

  const scrollToTop = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const reduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (typeof el.scrollTo === "function") {
      el.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
    } else {
      el.scrollTop = 0;
    }
  }, [ref]);

  return { showTop, scrollToTop };
}
