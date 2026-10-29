import { createElement, useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { tx, useLocale } from "@/i18n";
import { haptic } from "@/tg/webapp";
import { translateTexts, type TranslateTarget } from "@/api/translate";
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
const CYRILLIC = /[А-Яа-яЁё]/;

/** Сервер принимает до 500 символов; режем здесь, чтобы не получить 400. */
const MAX_CHARS = 500;

/**
 * Кэш на время сессии: `язык + текст → перевод`.
 *
 * Нужен, потому что человек листает список и включает перевод у нескольких
 * блоков подряд, а иногда выключает и включает снова. Один и тот же текст
 * второй раз по сети не ходит — серверный кэш в базе всё равно сработал бы, но
 * это лишний круг до чужого сервера на мобильном интернете.
 */
const SESSION_CACHE = new Map<string, string | null>();

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

function targetFor(locale: string): TranslateTarget | null {
  if (locale === "en") return "en";
  if (locale === "uz") return "uz";
  return null;
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

  if (!target || !CYRILLIC.test(text)) {
    // Русский интерфейс или уже латинский текст: переводить нечего, и кнопки
    // быть не должно — иначе она выглядит как обещание, которого нет.
    return createElement(Tag, { className }, text);
  }

  const source = text.slice(0, MAX_CHARS);

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
    const key = `${target}:${source}`;
    const preset = SESSION_CACHE.get(key);
    if (preset !== undefined) {
      setTranslated(preset);
      setFailed(preset === null);
      setOn(preset !== null);
      return;
    }

    setBusy(true);
    setFailed(false);
    try {
      const response = await translateTexts([source], target);
      const value = response.items[0]?.translated ?? null;
      SESSION_CACHE.set(key, value);
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
            ? // Подложка: видно, что это перевод поверх оригинала, а не сам
              // оригинал. Без неё человек читает машинный текст как авторский.
              "-mx-1 rounded-tile bg-tg-secondary-bg/70 px-1 ring-1 ring-tg-hint/10"
            : "",
          // Место под кнопку, чтобы она не наезжала на первую строку.
          "pr-9",
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
          "absolute right-0 top-0 grid h-9 w-9 place-items-center rounded-full",
          "border border-tg-hint/15 transition-colors",
          busy ? "opacity-60" : "",
          on
            ? "bg-tg-link/15 text-tg-link"
            : "bg-tg-secondary-bg/60 text-tg-hint",
        ]
          .filter(Boolean)
          .join(" "),
      },
      createElement(Icon, { name: "globe", size: 16 }),
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
