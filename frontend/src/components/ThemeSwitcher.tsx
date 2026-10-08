/**
 * GHG11(11): компактный свитчер темы в верхнем углу приложения.
 *
 * Одно нажатие — другая тема; никаких настроек и отдельного экрана (тема — не
 * то, ради чего стоит уводить человека с ленты). Иконка показывает ТЕКУЩУЮ тему
 * (🌙 при тёмной), подпись в `aria-label`/`title` — что произойдёт по тапу.
 * Вид максимально тихий: круглая плашка под цвет фона размером 28px, поэтому
 * она не спорит с содержимым шапки. Зарезервированное место в шапках — `pr-12`.
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
        "grid h-7 w-7 place-items-center rounded-full bg-tg-secondary-bg/70",
        "text-[13px] leading-none text-tg-hint active:scale-95 transition-transform",
        className ?? "",
      ].join(" ")}
    >
      <span aria-hidden>{dark ? "🌙" : "☀️"}</span>
    </button>
  );
}
