import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { tx, useLocale, useTx } from "@/i18n";
import { haptic } from "@/tg/webapp";
import { needsTranslation, targetCode, targetFor, translateBatch } from "./translateCore";
import { useTranslateAssist } from "@/store/translate";

/**
 * Подложка перевода (план, 11.6).
 *
 * Раньше это был серый `bg-tg-secondary-bg`, то есть ровно тот же цвет, что у
 * карточек вокруг: подложки фактически не было, и человек читал машинный
 * перевод как авторский текст. Теперь цвет тот же, что у активного глобуса
 * (`tg-link/10` + кольцо того же акцента) — между кнопкой и тем, что она
 * изменила, видно связь, не вчитываясь.
 */
export const TRANSLATED_MARK =
  "rounded-tile bg-tg-link/10 px-1 ring-1 ring-tg-link/30";

/** То же для текста внутри строки: подложка рвётся по переносам, а не рамкой. */
export const TRANSLATED_MARK_INLINE =
  "box-decoration-clone rounded-tile bg-tg-link/10 px-0.5 ring-1 ring-tg-link/25";

/**
 * Перевод целого блока данных одной кнопкой (план, 11.5).
 *
 * Почему не `TranslatableText` в каждой строке. В ленте событий на экране два
 * десятка строк, в тесте стандарта — десяток вопросов с вариантами. Кнопка в
 * каждом элементе превращает список в стену одинаковых иконок, а человеку
 * нужна одна мысль: «прочитай этот блок по-своему». Одна кнопка на блок и
 * один запрос на всю пачку — это и дешевле по сети, и читаемее.
 *
 * Правила те же, что у одиночного текста: только по нажатию, повторное
 * снимает, уход с экрана снимает сам, при русском интерфейсе кнопки нет, а
 * честный отказ сервера называется словами.
 *
 * Никакого автоперевода списка при открытии: модель на CPU считает фразу
 * около секунды, и лента из 20 событий открывалась бы заметно дольше, чем
 * сейчас. Скорость экрана важнее «умности».
 */
export interface BatchTranslate {
  /** Есть что переводить и есть на какой язык — только тогда рисуем кнопку. */
  canTranslate: boolean;
  on: boolean;
  busy: boolean;
  failed: boolean;
  toggle: () => Promise<void>;
  /** Текст с учётом режима: оригинал либо перевод, если он уже есть. */
  t: (text: string) => string;
}

export function useBatchTranslate(texts: string[]): BatchTranslate {
  const locale = useLocale((s) => s.locale);
  const epoch = useTranslateAssist((s) => s.epoch);
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [map, setMap] = useState<Map<string, string>>(() => new Map());
  const alive = useRef(true);

  // Пачка берётся в момент нажатия, а не запоминается вместе с обработчиком.
  // Иначе `useCallback` ниже захватил бы `texts` первого рендера — когда
  // данные ещё грузились и пачка была пустой или неполной, — и кнопка
  // "нажималась бы вхолостую" именно там, где карточка приходит с сервера
  // (стандарт открывается запросом). Это ловилось тестом, а не глазами.
  const textsRef = useRef(texts);
  textsRef.current = texts;

  const target = targetFor(locale);
  // Для решения «нужна ли кнопка» достаточно самого факта кириллицы.
  const canTranslate = target !== null && texts.some(needsTranslation);

  // Ушли с экрана — режим снят. Перевод остаётся в кэше: вернувшись, человек
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

  const toggle = useCallback(async () => {
    if (!target) return;
    haptic("light");
    if (on) {
      setOn(false);
      return;
    }
    if (map.size > 0) {
      setOn(true);
      return;
    }

    setBusy(true);
    setFailed(false);
    try {
      const next = await translateBatch(textsRef.current, target);
      if (!alive.current) return;
      setMap(next);
      setOn(next.size > 0);
      // Ни один текст не перевёлся — это либо «уже латиница», либо хост без
      // модели. Второе человеку важно назвать своим именем, а не молчать.
      setFailed(next.size === 0);
    } catch {
      if (alive.current) setFailed(true);
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [target, on, map]);

  const t = useCallback(
    (text: string) => (on ? map.get(text) ?? text : text),
    [on, map],
  );

  return { canTranslate, on, busy, failed, toggle, t };
}

/**
 * Кнопка блока: та же форма и тот же отклик, что у одиночного текста — иначе
 * два способа перевести одно и то же выглядели бы как два разных продукта.
 *
 * Код языка (`EN`/`UZ`) стоит рядом с глобусом всегда, а не после нажатия:
 * кнопка обязана отвечать на вопрос «на что переведёт» до того, как её нажали.
 */
export function TranslateBlockButton({
  on,
  busy,
  onClick,
}: {
  on: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  const { tx, locale } = useTx();
  const label = on ? tx("Показать оригинал") : tx("Перевести");
  const code = targetCode(locale);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-busy={busy}
      aria-label={label}
      title={label}
      data-testid="translate-block"
      className={[
        "flex h-9 shrink-0 items-center gap-1 rounded-full px-2.5",
        "border border-tg-hint/15 transition-colors press",
        busy ? "opacity-60" : "",
        on ? "bg-tg-link/15 text-tg-link" : "bg-tg-secondary-bg text-tg-hint",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Icon name="globe" size={15} />
      {code && (
        <span
          data-testid="translate-target"
          className="text-2xs font-semibold tracking-wide"
        >
          {code}
        </span>
      )}
    </button>
  );
}

/**
 * Честный отказ вместо тишины: на Amvera модели нет, и кнопка не должна
 * выглядеть как «ничего не произошло».
 */
export function TranslateFailedNotice({ show }: { show: boolean }) {
  const { locale } = useTx();
  if (!show) return null;
  return (
    <p
      data-testid="translate-block-failed"
      className="text-2xs text-tg-hint"
    >
      {tx(locale, "Перевод недоступен")}
    </p>
  );
}
