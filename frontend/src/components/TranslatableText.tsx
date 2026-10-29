import { createElement, useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { tx, useLocale } from "@/i18n";
import { haptic } from "@/tg/webapp";
import { needsTranslation, targetCode, targetFor, translateOne } from "./translateCore";
import { TRANSLATED_MARK_INLINE } from "./TranslatableBlock";
import { useTranslateAssist } from "@/store/translate";

/**
 * Текст, который можно прочитать на своём языке (план, 11).
 *
 * Зачем. Поручения и пункты чек-листа пишет руководитель по-русски. Человек,
 * у которого в интерфейсе выбран узбекский или английский, видит их всё равно
 * по-русски — и это не «дыра в переводе», а чужие данные, которые кодом не
 * переводятся. Кнопка в углу блока даёт перевод по требованию.
 *
 * Почему кнопка, а не автоперевод:
 *
 *  • машинный перевод корявый, и делать его единственной версией задания, по
 *    которому человек отчитывается, нельзя — он обязан уметь вернуться к
 *    оригиналу одним тапом;
 *  • перевод стоит времени (модель на CPU), а нужен не всем и не всегда;
 *  • это assist-функция доступности, а не режим приложения: включил — прочитал
 *    — выключил.
 *
 * Сброс при уходе с экрана — через `useTranslateAssist`: вкладки не
 * размонтируются, поэтому локального состояния мало, иначе возврат на экран
 * показывал бы перевод, о котором человек уже забыл.
 */
type Tag = "p" | "span" | "div" | "h2" | "h3";

interface Props {
  /** Русский оригинал — то, что пришло из базы. */
  text: string;
  /** Классы элемента текста: перевод наследует ту же типографику. */
  className?: string;
  /** Каким тегом выводить текст. Заголовок задачи остаётся заголовком. */
  as?: Tag;
  /** `inline` — внутри строки, без блочной обёртки. */
  layout?: "block" | "inline";
}

export default function TranslatableText({
  text,
  className = "",
  as = "p",
  layout = "block",
}: Props) {
  const locale = useLocale((s) => s.locale);
  const epoch = useTranslateAssist((s) => s.epoch);
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [translated, setTranslated] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const alive = useRef(true);

  const target = targetFor(locale);
  const code = targetCode(locale);

  // Ушли с экрана — режим снят. Перевод в кэше остаётся: вернувшись, человек
  // получит его мгновенно, но уже по своему нажатию.
  useEffect(() => {
    setOn(false);
  }, [epoch]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const Tag = (layout === "inline" ? "span" : as) as Tag;

  if (!target || !needsTranslation(text)) {
    // Русский интерфейс или уже латинский текст: переводить нечего, и кнопки
    // быть не должно — иначе она выглядит как обещание, которого нет.
    return createElement(Tag, { className }, text);
  }

  const press = async () => {
    haptic("light");
    if (on) {
      setOn(false);
      return;
    }
    if (translated) {
      setOn(true);
      return;
    }

    setBusy(true);
    setFailed(false);
    try {
      const value = await translateOne(text, target);
      if (!alive.current) return;
      setTranslated(value);
      setOn(value !== null);
      // `null` — либо строка уже на другом языке, либо на этом хосте нет
      // модели. Второе человеку важно назвать своим именем, а не молчать.
      setFailed(value === null);
    } catch {
      if (!alive.current) return;
      setFailed(true);
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const shown = on && translated ? translated : text;
  const Wrapper = layout === "inline" ? "span" : "div";

  return createElement(
    Wrapper,
    { className: "relative" },
    createElement(
      Tag,
      {
        className: [
          className,
          on && translated
            ? // Подложка в цвет активного глобуса: видно, что это перевод поверх
              // оригинала, а не сам оригинал. Серый был цветом карточек вокруг —
              // то есть подложки не было видно вовсе.
              TRANSLATED_MARK_INLINE
            : "",
          // Место под кнопку с кодом языка, чтобы она не наезжала на первую
          // строку.
          "pr-16",
        ]
          .filter(Boolean)
          .join(" "),
      },
      shown,
    ),
    createElement(
      "button",
      {
        type: "button",
        onClick: () => void press(),
        "aria-pressed": on,
        "aria-busy": busy,
        "aria-label": on ? tx(locale, "Показать оригинал") : tx(locale, "Перевести"),
        title: on ? tx(locale, "Показать оригинал") : tx(locale, "Перевести"),
        "data-testid": "translate-toggle",
        className: [
          "absolute right-0 top-0 flex h-7 items-center gap-1 rounded-full px-2",
          "border border-tg-hint/15 transition-colors",
          busy ? "opacity-60" : "",
          on
            ? "bg-tg-link/15 text-tg-link"
            : "bg-tg-secondary-bg/60 text-tg-hint",
        ]
          .filter(Boolean)
          .join(" "),
      },
      createElement(Icon, { name: "globe", size: 13 }),
      code
        ? createElement(
            "span",
            {
              "data-testid": "translate-target",
              className: "text-2xs font-semibold tracking-wide",
            },
            code,
          )
        : null,
    ),
    failed
      ? createElement(
          "span",
          {
            className: "mt-1 block text-2xs text-tg-hint",
            "data-testid": "translate-failed",
          },
          tx(locale, "Перевод недоступен"),
        )
      : null,
  );
}
