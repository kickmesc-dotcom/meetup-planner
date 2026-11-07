import { useState } from "react";
import Icon from "@/components/Icon";
import { useTx } from "@/i18n";
import { haptic } from "@/tg/webapp";

/**
 * Однократное знакомство с двумя зонами (11promt-TEACHER §3.2).
 *
 * Зачем. У руководителя приложение выглядит как у сотрудника: та же полоса,
 * те же экраны. Переключатель «Сотрудник | Управление» стоит сверху, но
 * человек, который пришёл закрыть свою смену, его просто не замечает — и потом
 * ищет приглашения и отчёты в профиле.
 *
 * Почему подсказка, а не постоянная плашка. Постоянная объяснялка занимает
 * место каждый день ради того, что нужно понять один раз. Здесь — три строки,
 * одна кнопка «Понятно» и запись в localStorage: второй раз не появится.
 *
 * Почему только мобильный каркас. На широком экране в сайдбаре уже есть
 * отдельная кнопка «Управление», и подсказка там была бы дублем.
 */
const HINT_KEY = "ux.zoneHint.v1";

function readSeen(): boolean {
  try {
    return localStorage.getItem(HINT_KEY) === "1";
  } catch {
    // Приватный режим: не показываем каждый раз, иначе подсказка станет шумом.
    return true;
  }
}

export default function ZoneHint({ canManage }: { canManage: boolean }) {
  const { tx } = useTx();
  const [hidden, setHidden] = useState(readSeen);

  if (!canManage || hidden) return null;

  const dismiss = () => {
    haptic("selection");
    try {
      localStorage.setItem(HINT_KEY, "1");
    } catch {
      // Запомнить не удалось — скроем до перезагрузки, это не поломка.
    }
    setHidden(true);
  };

  return (
    <div
      data-testid="zone-hint"
      className="mt-2 flex items-start gap-2 rounded-tile bg-tg-link/10 p-2 text-xs text-tg-text"
    >
      <Icon name="admin" size={16} className="mt-0.5 shrink-0 text-tg-link" />
      <p className="min-w-0 flex-1">
        {tx(
          "Вы руководитель. «Управление» вверху — это кабинет: люди, поручения и отчёты. Вкладки внизу остаются вашей сменой.",
        )}
      </p>
      <button
        type="button"
        onClick={dismiss}
        className="min-h-8 shrink-0 rounded-tile px-2 text-tg-link press"
      >
        {tx("Понятно")}
      </button>
    </div>
  );
}
