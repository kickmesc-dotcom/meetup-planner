/**
 * Переключатель языка: RU / EN, без перезагрузки.
 *
 * Две кнопки вместо выпадающего списка: языков ровно два, а список на экране
 * входа — лишний тап и лишний слой. Выбранный язык подсвечен, `aria-pressed`
 * говорит то же скринридеру.
 */
import { useT, useLocale, type Locale } from "@/i18n";
import { haptic } from "@/tg/webapp";

const OPTIONS: { value: Locale; label: "locale.ru" | "locale.en" }[] = [
  { value: "ru", label: "locale.ru" },
  { value: "en", label: "locale.en" },
];

export default function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, t } = useT();
  const setLocale = useLocale((s) => s.setLocale);

  return (
    <div
      role="group"
      aria-label={t("locale.label")}
      data-testid="language-switcher"
      className={["flex items-center gap-0.5 rounded-full bg-tg-secondary-bg/70 p-0.5", className ?? ""].join(" ")}
    >
      {OPTIONS.map((option) => {
        const active = option.value === locale;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            aria-label={t(option.label)}
            title={t(option.label)}
            onClick={() => {
              if (active) return;
              haptic("selection");
              setLocale(option.value);
            }}
            className={[
              "min-h-8 min-w-9 rounded-full px-2 text-2xs font-semibold uppercase transition-colors",
              active ? "bg-tg-bg text-tg-text" : "text-tg-hint",
            ].join(" ")}
          >
            {option.value}
          </button>
        );
      })}
    </div>
  );
}
