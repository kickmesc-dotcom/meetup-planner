import { useEffect, useState } from "react";

/**
 * UI_UX_PRO_MAX §10 `debounce-throttle` / `input-latency`: значение для фильтра
 * обновляется не на каждое нажатие, а после паузы.
 *
 * Зачем. Поиск по людям фильтрует список на каждый символ: на предприятии в
 * сотню человек это заметная работа на каждую букву, а на телефоне — ещё и
 * подвисание поля ввода. 200 мс — пауза между словами, а не «задержка
 * интерфейса»: быстрее человек всё равно не читает список.
 *
 * Почему не `useDeferredValue`: он не уменьшает число пересчётов, а лишь
 * откладывает отрисовку; для фильтра по массиву нужен именно debounce.
 */
export function useDebouncedValue<T>(value: T, delay = 200): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);

  return debounced;
}
