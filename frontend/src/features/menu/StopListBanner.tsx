import { useQuery } from "@tanstack/react-query";
import { fetchMenu } from "@/api/menu";
import { useTx } from "@/i18n";

/**
 * Стоп-лист в шапке ленты: что сегодня нельзя заказать.
 *
 * Почему плашка, а не раздел. Официант узнаёт о стоп-листе в тот момент, когда
 * гость просит блюдо, — искать его в меню некогда. Одна строка над событиями
 * смены отвечает на вопрос сразу, а сам список остаётся в «Меню смены», где его
 * и правят.
 *
 * Данные берутся тем же ключом `["menu"]`, что и экран меню: правка на месте
 * обновляет и плашку, а лишний запрос не уходит. Ответ кэшируется на минуту —
 * стоп-лист меняется не чаще, чем раз в несколько минут.
 */
export default function StopListBanner() {
  const { tx } = useTx();
  const q = useQuery({
    queryKey: ["menu"],
    queryFn: fetchMenu,
    staleTime: 60_000,
  });

  // `items ?? []`, а не `data?.items`: ответ без списка (ошибка, пустой мок,
  // старый бэкенд) не должен ронять экран ленты — плашка просто не рисуется.
  const stopped = (q.data?.items ?? []).filter((item) => !item.is_available);
  if (stopped.length === 0) return null;

  const names = stopped.slice(0, 3).map((item) => item.name);
  const rest = stopped.length - names.length;

  return (
    <div
      data-testid="stop-list-banner"
      role="status"
      className="mt-2 flex items-start gap-2 rounded-tile bg-status-busy/10 px-3 py-2 text-xs text-tg-text"
    >
      <span aria-hidden="true" className="mt-0.5 text-status-busy">
        ●
      </span>
      <p className="min-w-0">
        <span className="font-medium">{tx("Стоп-лист")}: </span>
        {names.join(", ")}
        {rest > 0 && (
          <span className="text-tg-hint">
            {" "}
            {tx("и ещё {count}", { count: rest })}
          </span>
        )}
      </p>
    </div>
  );
}
