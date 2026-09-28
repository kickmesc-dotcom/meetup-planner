import { humanizeApiError } from "@/api/client";
import { haptic } from "@/tg/webapp";

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
export default function ErrorState({
  error,
  onRetry,
  title = "Что-то пошло не так",
}: Props) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <div className="text-4xl mb-2" aria-hidden>
        ⚠️
      </div>
      <div className="text-base font-semibold text-tg-text">{title}</div>
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
          className="mt-4 min-h-11 rounded-lg bg-tg-button px-4 text-sm font-medium text-tg-button-text active:scale-[0.98] transition-transform"
        >
          Повторить
        </button>
      )}
    </div>
  );
}
