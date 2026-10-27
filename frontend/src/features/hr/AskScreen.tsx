import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { searchKnowledge, type KnowledgeHit } from "@/api/knowledge";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import Icon from "@/components/Icon";
import { haptic } from "@/tg/webapp";
import { useUI } from "@/store/ui";
import { useTx } from "@/i18n";

/**
 * «Спросить» — один вход в знания заведения.
 *
 * Почему не поиск внутри «Стандартов»: сотрудник не знает, где лежит ответ.
 * «Как закрыть смену» может быть стандартом, а может — пунктом чек-листа, и
 * искать надо сразу в обоих. Поэтому здесь единая строка и общая выдача.
 *
 * Почему без debounce-магии и подсказок «пока вы печатаете»: запрос уходит по
 * кнопке (и по Enter). Слабый мобильный канал в зале — это норма, и лишние
 * пять запросов на слово превращают поиск в ожидание.
 */
const EXAMPLES = ["закрыть смену", "открытие зала", "фотоотчёт", "опоздание"];

export default function AskScreen() {
  const { tx } = useTx();
  const setTab = useUI((s) => s.setTab);
  const [text, setText] = useState("");
  // Что реально ищем: черновик в поле и запрос — разные вещи, иначе выдача
  // дёргается на каждой букве.
  const [query, setQuery] = useState("");

  const search = useQuery({
    queryKey: ["knowledge-search", query],
    queryFn: () => searchKnowledge(query),
    enabled: query.trim().length >= 2,
    // Инструкции меняются редко: держим ответ минуту, чтобы возврат «назад»
    // не стоил ещё одного запроса к базе.
    staleTime: 60_000,
  });

  const submit = (value: string) => {
    const next = value.trim();
    if (next.length < 2) return;
    haptic("light");
    setText(next);
    setQuery(next);
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setTab("tasks");
          }}
          className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
          aria-label={tx("Назад к задачам")}
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
            <Icon name="search" size={15} className="shrink-0" />
            {tx("Спросить")}
          </div>
          <div className="text-xs text-tg-hint">
            {tx("Стандарты и чек-листы одним поиском")}
          </div>
        </div>
      </header>

      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 py-3">
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            submit(text);
          }}
        >
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={tx("Например: как закрыть смену")}
            className="min-h-11 min-w-0 flex-1 rounded-tile border border-tg-secondary-bg bg-transparent px-3 text-sm outline-none focus:border-tg-link"
            aria-label={tx("Что найти")}
            maxLength={120}
          />
          <button
            type="submit"
            disabled={text.trim().length < 2}
            className="min-h-11 rounded-tile bg-tg-button px-4 text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {tx("Найти")}
          </button>
        </form>

        {!query && (
          <section className="mt-4">
            <div className="text-xs text-tg-hint">{tx("Частые вопросы")}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => submit(example)}
                  className="min-h-9 rounded-full border border-tg-secondary-bg px-3 text-xs text-tg-link"
                >
                  {tx(example)}
                </button>
              ))}
            </div>
          </section>
        )}

        {/* Пока идёт поиск, форма и подсказки уже на экране — скелетон занимает
            ровно место будущих карточек, поэтому результат не «прыгает». */}
        {query && search.isPending && (
          <section className="mt-4 flex flex-col gap-2" aria-busy="true">
            <CardSkeleton />
            <CardSkeleton />
          </section>
        )}

        {query && search.isError && (
          <div className="mt-4">
            <ErrorState error={search.error} onRetry={() => void search.refetch()} />
          </div>
        )}

        {query && search.data && search.data.hits.length > 0 && (
          <section className="mt-4 flex flex-col gap-2">
            {search.data.hits.map((hit) => (
              <HitCard key={`${hit.kind}-${hit.id}`} hit={hit} />
            ))}
          </section>
        )}

        {query && search.data?.empty && (
          <section className="mt-6 text-sm text-tg-hint">
            {tx("Ничего не нашлось. Спросите руководителя — ответ стоит добавить в стандарты.")}
          </section>
        )}
      </main>
    </div>
  );
}

/**
 * Один результат. Клик ведёт в раздел, где элемент живёт, — поиск не заменяет
 * экраны, а сокращает путь к ним.
 */
function HitCard({ hit }: { hit: KnowledgeHit }) {
  const { tx } = useTx();
  const setTab = useUI((s) => s.setTab);
  const isStandard = hit.kind === "standard";
  return (
    <button
      type="button"
      onClick={() => {
        haptic("light");
        setTab(isStandard ? "standards" : "checklist");
      }}
      className="rounded-card border border-tg-secondary-bg px-3 py-2 text-left"
    >
      <div className="flex items-center gap-1.5 text-xs text-tg-hint">
        <Icon name={isStandard ? "book" : "check"} size={13} className="shrink-0" />
        <span>{isStandard ? tx("Стандарт") : tx("Чек-лист")}</span>
        {hit.subtitle && <span className="truncate">· {hit.subtitle}</span>}
      </div>
      <div className="mt-1 text-sm font-medium text-tg-text">{hit.title}</div>
      {hit.snippet && (
        <div className="mt-1 text-xs text-tg-hint">{hit.snippet}</div>
      )}
    </button>
  );
}
