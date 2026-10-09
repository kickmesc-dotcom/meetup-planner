/**
 * GHG11(11/12): компактный свитчер темы.
 *
 * Одно нажатие — другая тема; никаких настроек и отдельного экрана (тема — не
 * то, ради чего стоит уводить человека с ленты). Иконка показывает ТЕКУЩУЮ тему
 * (🌙 при тёмной), подпись в `aria-label`/`title` — что произойдёт по тапу.
 * Вид максимально тихий: круглая плашка под цвет фона размером 28px.
 *
 * GHG11(12): раньше он висел абсолютом в углу оболочки (и «косо сидел» рядом
 * с настоящими элементами). Теперь это обычный flex-элемент в верхней строке
 * каждого экрана — выравнивание получается само: тот же центр строки и тот же
 * отступ, что у колокольчика/стрелок/заголовка.
 */
import { useTheme } from "@/store/theme";
import { haptic, syncWebAppChrome } from "@/tg/webapp";

export default function ThemeSwitcher({ className }: { className?: string }) {
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggleTheme);

  const dark = theme === "dark";
  const label = dark ? "Включить светлую тему" : "Включить тёмную тему";

  return (
    <button
      type="button"
      data-testid="theme-switcher"
      aria-label={label}
      title={label}
      onClick={() => {
        haptic("light");
        toggleTheme();
        // Тема уже применилась; теперь просим клиент перекрасить свой хром.
        syncWebAppChrome(dark ? "light" : "dark");
      }}
      className={[
        "grid h-7 w-7 shrink-0 place-items-center rounded-full bg-tg-secondary-bg/70",
        "text-[13px] leading-none text-tg-hint active:scale-95 transition-transform",
        className ?? "",
      ].join(" ")}
    >
      <span aria-hidden>{dark ? "🌙" : "☀️"}</span>
    </button>
  );
}
