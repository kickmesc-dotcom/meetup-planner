/**
 * Приветствие над календарём.
 *
 * Раньше здесь была «сводка званий»: чухан недели, лох дня, главный лох,
 * главный чухан и червь. Этого контура в продукте больше нет — баннер отвечает
 * только за приветствие и за возможность его скрыть (возврат — в профиле,
 * `hide_greeting`).
 *
 * Пропсы `users`/`format` убраны вместе с блоками: держать у вызывающей стороны
 * данные, которые никто не читает, — приглашение снова отрастить здесь
 * случайную сводку.
 */
import { haptic, showConfirm } from "@/tg/webapp";
import Icon from "@/components/Icon";
import { useTx } from "@/i18n";
interface Props {
  meName: string;
  onHide: () => void;
}

export default function WelcomeBanner({ meName, onHide }: Props) {
  const { tx } = useTx();
  return (
    <header className="px-4 py-0 border-b border-tg-secondary-bg">
      <div className="flex min-h-11 items-center gap-1.5">
        <div className="flex min-h-11 min-w-0 flex-1 items-center gap-1.5">
          <span className="text-base font-medium truncate">
            Привет, {meName}
          </span>
        </div>
        <button
          type="button"
          onClick={async () => {
            haptic("warning");
            const ok = await showConfirm(
              tx("Не показывать приветствие? Вернуть можно в настройках профиля."),
            );
            if (ok) onHide();
          }}
          aria-label={tx("Скрыть приветствие")}
          title={tx("Не показывать в следующий раз")}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-tg-hint transition-transform hover:text-tg-text press"
        >
          <Icon name="close" size={16} />
        </button>
      </div>
    </header>
  );
}
