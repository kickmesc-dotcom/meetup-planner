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

export default function LanguageSwitcher({
  className,
  bare = false,
}: {
  className?: string;
  /** Без своего фона: когда языки стоят в общей капсуле с темой. */
  bare?: boolean;
}) {
  const { locale, t } = useT();
  const setLocale = useLocale((s) => s.setLocale);
  const uzPackAvailable = useLocale((s) => s.uzPackAvailable);

  return (
    <div
      role="group"
      aria-label={t("locale.label")}
      data-testid="language-switcher"
      className={[
        "flex flex-wrap items-center justify-center gap-2",
        bare ? "" : "rounded-full bg-tg-secondary-bg/70 p-1",
        className ?? "",
      ].join(" ")}
    >
      {localesFor(uzPackAvailable).map((option) => {
        const active = option === locale;
        return (
          <button
            key={option}
            type="button"
            aria-pressed={active}
            // §2.5.3 `label-in-name`: видимый текст — «RU/EN/UZ», поэтому имя
            // обязано его содержать. Было просто «Русский», и человек,
            // который диктует «нажми RU», не находил кнопку по имени.
            aria-label={`${t(LABELS[option])} ${option.toUpperCase()}`}
            title={t(LABELS[option])}
            onClick={() => {
              if (active) return;
              haptic("selection");
              setLocale(option);
            }}
            className={[
            // §1.4.5 `touch-target-size`: не только высота, но и ширина 44.
              // Было 36 px («промах по вертикали основной»), но AAA требует
              // обе стороны. Три языка по 44 — 132 px; на 375 px заголовку
              // остаётся 243, и `layout.spec.ts` подтверждает, что шапка не
              // переполняется.
              "min-h-11 min-w-11 rounded-full px-2 text-2xs font-semibold uppercase transition-colors",
              // Неактивная кнопка была `text-tg-hint` на полупрозрачном
              // secondary: axe дал 4.2:1 — ниже AA для текста 11 px.
              // Различие состояний держат фон и кольцо, а не бледность.
              active ? "bg-tg-bg text-tg-text" : "text-tg-text",
            ].join(" ")}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}
