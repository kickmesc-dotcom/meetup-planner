import Icon from "@/components/Icon";

/**
 * «Наверх» для длинной ленты.
 *
 * Появляется только после первого экрана: на коротком списке это была бы
 * кнопка, ведущая туда, где человек и так стоит. Тач-цель 44 px и `fixed` над
 * нижней полосой — палец дотягивается, не перекрывая вкладки.
 */
export default function ScrollTopButton({
  show,
  label,
  onClick,
}: {
  show: boolean;
  label: string;
  onClick: () => void;
}) {
  if (!show) return null;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="fixed bottom-24 right-4 z-20 grid h-11 w-11 place-items-center rounded-full bg-tg-button text-tg-button-text shadow-floating"
    >
      <Icon name="chevron" size={18} className="-rotate-90" />
    </button>
  );
}
