/**
 * Переключатель языка: RU / EN / UZ, без перезагрузки.
 *
 * Кнопки вместо выпадающего списка: языков максимум три, а список на экране
 * входа — лишний тап и лишний слой. Выбранный язык подсвечен, `aria-pressed`
 * говорит то же скринридеру.
 *
 * Узбекский — не всегда: это языковой пакет организации (план, 8.3), и когда
 * владелец его выключил, кнопки просто нет. Показывать её серой нельзя:
 * «есть, но не для тебя» — это вопрос, на который сотрудник не найдёт ответа
 * в приложении.
 */
import { useT, useLocale, localesFor, type Locale, type MessageKey } from "@/i18n";
import { haptic } from "@/tg/webapp";

const LABELS: Record<Locale, MessageKey> = {
  ru: "locale.ru",
  en: "locale.en",
  uz: "locale.uz",
};

export default function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, t } = useT();
  const setLocale = useLocale((s) => s.setLocale);
  const uzPackAvailable = useLocale((s) => s.uzPackAvailable);

  return (
    <div
      role="group"
      aria-label={t("locale.label")}
      data-testid="language-switcher"
      className={["flex items-center gap-0.5 rounded-full bg-tg-secondary-bg/70 p-0.5", className ?? ""].join(" ")}
    >
      {localesFor(uzPackAvailable).map((option) => {
        const active = option === locale;
        return (
          <button
            key={option}
            type="button"
            aria-pressed={active}
            aria-label={t(LABELS[option])}
            title={t(LABELS[option])}
            onClick={() => {
              if (active) return;
              haptic("selection");
              setLocale(option);
            }}
            className={[
              "min-h-8 min-w-9 rounded-full px-2 text-2xs font-semibold uppercase transition-colors",
              active ? "bg-tg-bg text-tg-text" : "text-tg-hint",
            ].join(" ")}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}
