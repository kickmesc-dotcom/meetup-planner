import { useEffect } from "react";
import Icon from "./Icon";
import { dismissToast, useToasts } from "./toast";
import { useTx } from "@/i18n";

/**
 * Единственное место, где тосты рисуются.
 *
 * Почему `aria-live="polite"`: сообщение не должно перебивать действия
 * скринридера, но обязано быть прочитано. `role="status"` даёт то же поведение
 * в старых движках Telegram.
 *
 * Почему снизу и с отступом: на мобильном внизу живёт полоса вкладок, и тост
 * поверх неё закрыл бы навигацию. `pointer-events-none` у обёртки пропускает
 * касания мимо, кроме самих сообщений.
 */
export default function ToastHost() {
  const toasts = useToasts();
  const { tx } = useTx();

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="toast-host"
      className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4"
    >
      {toasts.map((toast) => (
        <ToastRow
          key={toast.id}
          id={toast.id}
          text={toast.text}
          success={toast.kind === "success"}
          closeLabel={tx("Скрыть сообщение")}
        />
      ))}
    </div>
  );
}

function ToastRow({
  id,
  text,
  success,
  closeLabel,
}: {
  id: number;
  text: string;
  success: boolean;
  closeLabel: string;
}) {
  useEffect(() => {
    const timer = window.setTimeout(() => dismissToast(id), 3200);
    return () => window.clearTimeout(timer);
  }, [id]);

  return (
    <div className="pointer-events-auto flex w-full max-w-[420px] items-start gap-2 rounded-card bg-tg-secondary-bg px-3 py-2 text-sm text-tg-text shadow-lg ring-1 ring-tg-hint/20">
      <Icon
        name={success ? "check" : "alert"}
        size={16}
        className={[
          "mt-0.5 shrink-0",
          success ? "text-green-600" : "text-tg-link",
        ].join(" ")}
      />
      <span className="min-w-0 flex-1 break-words">{text}</span>
      {/* UI_UX_PRO_MAX §2 `touch-target-size`: закрытие — тоже кнопка,
          поэтому 44×44, а не 32px текстового «×». Отрицательные отступы
          не дают тосту вырасти из-за увеличенной тач-цели. */}
      <button
        type="button"
        aria-label={closeLabel}
        onClick={() => dismissToast(id)}
        className="-my-2 -mr-2 grid min-h-11 min-w-11 shrink-0 place-items-center rounded-tile text-tg-hint"
      >
        <Icon name="close" size={16} />
      </button>
    </div>
  );
}
