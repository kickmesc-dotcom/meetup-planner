import Icon from "@/components/Icon";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";

/**
 * Личная галочка приватности: включена/выключена и, если политика организации
 * запрещает выключение, — «заперто руководителем», без лживого «выключено».
 *
 * Вынесено из профиля в отдельный компонент, когда настройки профиля стали
 * самостоятельным экраном: те же две галочки живут и там, и второй копии
 * разметки быть не должно.
 */
export default function PrivacyRow({
  title,
  hint,
  value,
  locked,
  busy,
  onToggle,
}: {
  title: string;
  hint: string;
  value: boolean;
  locked: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  const { tx } = useTx();
  return (
    <div className="flex items-center gap-2 rounded-tile bg-tg-bg/50 p-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-xs text-tg-text">
          {title}
          {locked && <Icon name="lock" size={11} className="text-tg-hint" />}
        </div>
        <div className="text-2xs text-tg-hint">{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={title}
        disabled={locked || busy}
        onClick={() => {
          haptic("light");
          onToggle();
        }}
        className={[
          "min-h-9 shrink-0 rounded-full px-3 text-xs transition-colors disabled:opacity-60",
          value
            ? "bg-tg-button text-tg-button-text"
            : "bg-tg-secondary-bg text-tg-text",
        ].join(" ")}
      >
        {value ? tx("Видно") : tx("Скрыто")}
      </button>
    </div>
  );
}
