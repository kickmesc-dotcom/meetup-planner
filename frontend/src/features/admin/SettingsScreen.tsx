/**
 * Настройки приложения — одна дверь для того, что раньше валялось в шапке.
 *
 * Зачем понадобился экран. 02.11.2026 владелец открыл зону управления и увидел
 * в верхней строке подряд: значок-гаечный ключ (декоративный, ничего не делал),
 * переключатель зон, переключатель языка и тему. Язык и тема — это настройки, но
 * стояли они вплотную к вкладкам и читались как их продолжение: «где я — и
 * почему тут же EN/UZ». Отсюда два правила, которые теперь соблюдаются:
 *
 * 1. Верхняя строка отвечает ровно на один вопрос — в какой я зоне.
 * 2. Всё, что настраивает вид и язык, живёт здесь, за самой правой кнопкой
 *    нижней полосы, и никуда не девается оттуда.
 *
 * Ряды-ссылки ниже не дублируют кабинет: это короткие дороги к тем его
 * разделам, которые человек меняет чаще всего, чтобы за ними не возвращаться
 * в общий список.
 */
import Icon, { type IconName } from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import SubScreen from "@/features/admin/SubScreen";
import { useTx } from "@/i18n";
import { haptic } from "@/tg/webapp";
import { setUxMode, useUxMode } from "./uxMode";

interface Shortcut {
  id: string;
  icon: IconName;
  title: string;
  subtitle: string;
}

const SHORTCUTS: Shortcut[] = [
  {
    id: "feed-settings",
    icon: "layout",
    title: "Вид ленты",
    subtitle: "Компактный (миниатюры участников) или классический",
  },
  {
    id: "calendar-settings",
    icon: "calendar",
    title: "Вид календаря",
    subtitle: "Новый таймлайн или legacy-вид",
  },
  {
    id: "languages",
    icon: "globe",
    title: "Языки команды",
    subtitle: "Узбекский пакет: включён по умолчанию",
  },
  {
    id: "privacy",
    icon: "check",
    title: "Данные и приватность",
    subtitle: "Копия данных, удаление организации, журнал доступа",
  },
  {
    id: "branches",
    icon: "team",
    title: "Филиалы сети",
    subtitle: "Несколько салонов под одним владельцем",
  },
  {
    id: "domain",
    icon: "globe",
    title: "Свой домен",
    subtitle: "Адрес входа для команды вместо платформенной ссылки",
  },
  {
    id: "texts",
    icon: "edit",
    title: "Тексты приложения",
    subtitle: "Приветствие, подсказки и пустые состояния",
  },
];

export default function SettingsScreen({
  onBack,
  onOpen,
  platform = false,
}: {
  onBack: () => void;
  /** Переход в раздел кабинета (он же — раздел настроек). */
  onOpen: (section: string) => void;
  /** Системные тексты правятся только владельцем платформы. */
  platform?: boolean;
}) {
  const { tx } = useTx();
  const uxMode = useUxMode();
  const shortcuts = SHORTCUTS.filter((s) => s.id !== "texts" || platform);

  return (
    <SubScreen
      title={tx("Настройки")}
      subtitle={tx("Язык, вид приложения и доступы")}
      onBack={onBack}
    >
      <section
        aria-label={tx("Язык и вид")}
        className="rounded-card border border-tg-secondary-bg bg-tg-secondary-bg/20 p-3"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-tg-text">{tx("Язык")}</div>
            <div className="text-xs text-tg-hint">
              {tx("Интерфейс без перезагрузки")}
            </div>
          </div>
          <LanguageSwitcher />
        </div>
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-tg-secondary-bg pt-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-tg-text">{tx("Тема")}</div>
            <div className="text-xs text-tg-hint">
              {tx("Светлая или тёмная — по клику")}
            </div>
          </div>
          <ThemeSwitcher />
        </div>
      </section>

      <section
        aria-label={tx("Подробность интерфейса")}
        className="rounded-card border border-tg-secondary-bg bg-tg-secondary-bg/20 p-3"
      >
        <div className="text-sm font-semibold text-tg-text">
          {tx("Подробность интерфейса")}
        </div>
        <p className="mt-1 text-xs text-tg-hint">
          {tx("Простой — только основное. Расширенный — все разделы сразу.")}
        </p>
        <div
          role="group"
          aria-label={tx("Подробность интерфейса")}
          className="mt-2 grid grid-cols-2 gap-2"
        >
          {(["simple", "advanced"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={uxMode === value}
              onClick={() => {
                haptic("selection");
                setUxMode(value);
              }}
              className={[
                "min-h-11 rounded-tile px-3 text-sm press",
                uxMode === value
                  ? "bg-tg-button font-medium text-tg-button-text"
                  : "bg-tg-secondary-bg text-tg-text",
              ].join(" ")}
            >
              {value === "simple" ? tx("Простой режим") : tx("Расширенный режим")}
            </button>
          ))}
        </div>
      </section>

      <div>
        <div className="mb-2 px-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
          {tx("Ещё настройки")}
        </div>
        <div className="overflow-hidden rounded-card border border-tg-secondary-bg">
          {shortcuts.map((s, i) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                haptic("light");
                onOpen(s.id);
              }}
              className={[
                "flex w-full items-center gap-3 bg-tg-bg px-3 py-2.5 text-left press-row",
                i > 0 ? "border-t border-tg-secondary-bg" : "",
              ].join(" ")}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-tile bg-tg-secondary-bg/60 text-tg-link">
                <Icon name={s.icon} size={17} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-tg-text" title={tx(s.title)}>
                  {tx(s.title)}
                </span>
                <span className="block truncate text-xs text-tg-hint" title={tx(s.subtitle)}>
                  {tx(s.subtitle)}
                </span>
              </span>
              <Icon name="chevron" size={16} className="shrink-0 text-tg-hint" />
            </button>
          ))}
        </div>
      </div>
    </SubScreen>
  );
}
