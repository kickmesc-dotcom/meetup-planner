import { useEffect } from "react";
import { humanizeApiError, isNetworkError } from "@/api/client";
import Icon from "@/components/Icon";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";
interface Props {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}

/**
 * DESIGN_SYSTEM §8: единое состояние ошибки экрана.
 *
 * До этого App/Meetings/Polls печатали сырой `String(error)` в голом
 * `p-6 text-status-busy` — «Ошибка: Error: ...». Здесь сообщение проходит через
 * `humanizeApiError`, есть иконка и повтор запроса.
 */
export default function ErrorState({ error, onRetry, title }: Props) {
  const { tx } = useTx();
  const offline = isNetworkError(error);

  // Обрыв сети — единственная ошибка, которую человек не может исправить
  // кнопкой: сеть вернётся сама. Поэтому ждём `online` и повторяем запрос
  // без нажатия; кнопка остаётся для ручного повтора.
  useEffect(() => {
    if (!offline || !onRetry) return;
    const retry = () => onRetry();
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [offline, onRetry]);

  return (
    <div
      role="alert"
      className="flex h-full flex-col items-center justify-center px-6 text-center"
    >
      <Icon name="alert" size={34} className="mb-2 text-status-busy" />
      <div className="text-base font-semibold text-tg-text">
        {title ?? (offline ? tx("Нет связи") : tx("Что-то пошло не так"))}
      </div>
      <div className="mt-1 text-sm text-tg-hint break-words">
        {humanizeApiError(error)}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onRetry();
          }}
          className="mt-4 min-h-11 rounded-tile bg-tg-button px-4 text-sm font-medium text-tg-button-text press"
        >
          {tx("Повторить")}
        </button>
      )}
    </div>
  );
}
