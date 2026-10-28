import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import BottomSheet from "@/features/actions/BottomSheet";
import Icon from "@/components/Icon";
import { Skeleton } from "@/components/Skeleton";
import {
  createQuickTask,
  fetchQuickPeople,
  parseQuickText,
  quickErrorText,
  type QuickPerson,
} from "@/api/quick";
import { haptic, showAlert } from "@/tg/webapp";
import { intlLocaleFor, useTx, type Locale } from "@/i18n";

/**
 * «Сказал — стало поручением» (план, 8.5).
 *
 * Руководитель видит проблему в зале и диктует одну фразу. Шторка показывает,
 * **как его поняли**, ещё до создания: кому, когда, срочно ли. Это главное
 * отличие от формы — форма спрашивает пять полей до того, как что-то поняла,
 * а здесь сначала появляется черновик, и его либо подтверждают одним тапом,
 * либо поправляют один чип.
 *
 * Принципы, которые здесь соблюдаются:
 *
 * * **Сначала подписи, потом данные.** Заголовок, поле ввода и кнопка видны
 *   сразу — они не зависят от сети. Карточка разбора появляется каркасом и
 *   заполняется ответом, высота при этом не прыгает.
 * * **Сервер решает, интерфейс показывает.** Правила срока и исполнителя
 *   живут на сервере; здесь нет второй копии, которая разошлась бы с ним.
 * * **Ничего не создаётся, пока не нажали.** Разбор не пишет в базу: можно
 *   передумать, и никто не получит уведомление о несуществующей работе.
 * * **Голос — только там, где он есть.** Расшифровка идёт в браузере
 *   (`SpeechRecognition`): сервер получает уже текст, аудио никуда не уходит и
 *   не хранится. Где браузер не умеет слушать (часть iOS), кнопка не
 *   рисуется — «не работает» хуже, чем «нет кнопки».
 */

/** Минимум браузерного API, который нам нужен: без `any` и без пакета типов. */
interface SpeechResultEvent {
  results: { length: number; [index: number]: { [index: number]: { transcript: string } } };
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
}

type SpeechCtor = new () => SpeechRecognitionLike;

function speechCtor(): SpeechCtor | null {
  const scope = window as unknown as {
    SpeechRecognition?: SpeechCtor;
    webkitSpeechRecognition?: SpeechCtor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

const SPEECH_LANG: Record<Locale, string> = {
  ru: "ru-RU",
  en: "en-US",
  uz: "uz-UZ",
};

/**
 * Срок для плашки: «сегодня 18:00», «завтра 09:00», иначе «30.10 18:00».
 *
 * Слова «сегодня»/«завтра» возвращаются кодом, а не текстом: их переводит
 * экран через `tx`, иначе узбекская шторка показывала бы русские слова
 * посреди своих.
 */
function describeDue(
  iso: string | null,
  locale: Locale,
): { relative: "today" | "tomorrow" | null; rest: string } {
  if (!iso) return { relative: null, rest: "" };
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return { relative: null, rest: "" };
  const time = date.toLocaleTimeString(intlLocaleFor(locale), {
    hour: "2-digit",
    minute: "2-digit",
  });
  const dayOf = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((dayOf(date) - dayOf(new Date())) / 86_400_000);
  if (diff === 0) return { relative: "today", rest: time };
  if (diff === 1) return { relative: "tomorrow", rest: time };
  const day = date.toLocaleDateString(intlLocaleFor(locale), {
    day: "2-digit",
    month: "2-digit",
  });
  return { relative: null, rest: `${day} ${time}` };
}

export default function QuickTaskSheet({ onClose }: { onClose: () => void }) {
  const { tx, locale } = useTx();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const [listening, setListening] = useState(false);
  const [picking, setPicking] = useState<"assignee" | "due" | null>(null);
  // Ручные правки черновика. `undefined` — «как разобрал сервер»: правка не
  // затирает разбор, если человек её не делал.
  const [chosenAssignee, setChosenAssignee] = useState<QuickPerson | null | undefined>();
  const [chosenDue, setChosenDue] = useState<string | null | undefined>();
  const [urgent, setUrgent] = useState<boolean | undefined>();
  const [photo, setPhoto] = useState<boolean | undefined>();
  const [created, setCreated] = useState<{ title: string; who: string | null } | null>(
    null,
  );
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    // Поле в фокусе сразу: шторка открывается ради одной фразы, и лишний тап
    // по полю — это ровно тот шаг, который механика экономит.
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    // Разбор по паузе в наборе: 300 мс — примерно конец фразы, но ещё не
    // «показывает» каждую букву. Меньше — лишние запросы на медленном сервере.
    const timer = setTimeout(() => setDebounced(text.trim()), 300);
    return () => clearTimeout(timer);
  }, [text]);

  const draftQ = useQuery({
    queryKey: ["quick-parse", debounced],
    queryFn: () => parseQuickText(debounced),
    enabled: debounced.length >= 3,
    staleTime: 5 * 60_000,
  });
  const peopleQ = useQuery({
    queryKey: ["quick-people"],
    queryFn: fetchQuickPeople,
    enabled: picking === "assignee",
    staleTime: 5 * 60_000,
  });

  const create = useMutation({
    mutationFn: createQuickTask,
    onSuccess: (task) => {
      haptic("success");
      setCreated({ title: task.title, who: task.assignee_name });
      void qc.invalidateQueries({ queryKey: ["hr-tasks"] });
      void qc.invalidateQueries({ queryKey: ["feed"] });
    },
    onError: (error) => {
      haptic("error");
      showAlert(quickErrorText(error));
    },
  });

  const draft = draftQ.data ?? null;
  const effectiveAssignee =
    chosenAssignee !== undefined ? chosenAssignee : (draft?.assignee ?? null);
  const effectiveDue = chosenDue !== undefined ? chosenDue : (draft?.due_at ?? null);
  const effectivePriority =
    urgent !== undefined ? (urgent ? "high" : "normal") : (draft?.priority ?? "normal");
  const effectivePhoto = photo !== undefined ? photo : (draft?.requires_photo ?? false);
  const isGroup = draft?.scope === "department" && !effectiveAssignee;
  const due = describeDue(effectiveDue, locale);

  const canCreate =
    !create.isPending &&
    debounced.length >= 3 &&
    (isGroup || effectiveAssignee !== null);

  const toggleVoice = () => {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const Ctor = speechCtor();
    if (!Ctor) return;
    const recognition = new Ctor();
    recognition.lang = SPEECH_LANG[locale] ?? "ru-RU";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const phrase = event.results[0]?.[0]?.transcript ?? "";
      if (phrase) {
        setText((prev) => (prev ? `${prev} ${phrase}` : phrase));
        haptic("selection");
      }
    };
    recognition.onerror = () => {
      setListening(false);
      haptic("error");
      showAlert(tx("Не расслышал — попробуй ещё раз или напиши словами."));
    };
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    setListening(true);
    haptic("light");
    recognition.start();
  };

  const submit = () => {
    if (!canCreate) return;
    haptic("light");
    create.mutate({
      text: debounced,
      assignee_employee_id: effectiveAssignee?.id ?? null,
      department_id: draft?.department_id ?? null,
      scope: effectiveAssignee ? "employee" : (draft?.scope ?? "employee"),
      due_at: effectiveDue,
      priority: effectivePriority,
      requires_photo: effectivePhoto,
      requires_review: draft?.requires_review ?? false,
    });
  };

  if (created) {
    return (
      <BottomSheet title={tx("Поручение создано")} onClose={onClose}>
        <div className="flex flex-col items-center py-4 text-center">
          <span className="grid h-12 w-12 place-items-center rounded-full bg-status-free/20">
            <Icon name="check" size={24} className="text-status-free" />
          </span>
          <p className="mt-3 text-sm font-medium text-tg-text">{created.title}</p>
          <p className="mt-1 text-xs text-tg-hint">
            {created.who
              ? tx("Исполнитель: {name}", { name: created.who })
              : tx("Поручение отправлено отделу.")}
          </p>
        </div>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setCreated(null);
              setText("");
              setDebounced("");
              setChosenAssignee(undefined);
              setChosenDue(undefined);
              setUrgent(undefined);
              setPhoto(undefined);
              inputRef.current?.focus();
            }}
            className="min-h-11 flex-1 rounded-full bg-tg-secondary-bg text-xs text-tg-text"
          >
            {tx("Ещё одно")}
          </button>
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              onClose();
            }}
            className="min-h-11 flex-1 rounded-full bg-tg-button text-xs text-tg-button-text"
          >
            {tx("Готово")}
          </button>
        </div>
      </BottomSheet>
    );
  }

  return (
    <BottomSheet title={tx("Скажи, что нужно сделать")} onClose={onClose}>
      <div className="flex items-end gap-2">
        <textarea
          ref={inputRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={2}
          maxLength={500}
          placeholder={tx("Например: Аня, протри витрину до 18:00")}
          aria-label={tx("Что нужно сделать")}
          className="min-h-11 flex-1 resize-none rounded-tile bg-tg-secondary-bg px-3 py-2.5 text-sm text-tg-text outline-none placeholder:text-tg-hint"
        />
        {speechCtor() && (
          <button
            type="button"
            onClick={toggleVoice}
            aria-label={listening ? tx("Остановить запись") : tx("Сказать голосом")}
            aria-pressed={listening}
            className={[
              "grid h-11 w-11 shrink-0 place-items-center rounded-full",
              listening
                ? "bg-status-busy text-white animate-pulse motion-reduce:animate-none"
                : "bg-tg-secondary-bg text-tg-text",
            ].join(" ")}
          >
            <Icon name="mic" size={18} />
          </button>
        )}
      </div>

      <p className="mt-1.5 text-2xs text-tg-hint">
        {tx("Голос распознаёт браузер — запись никуда не отправляется.")}
      </p>

      {/* Каркас той же формы, что и карточка разбора: пока сервер думает,
          место уже занято, и шторка не «прыгает» на ответе. */}
      {debounced.length >= 3 && draftQ.isLoading && (
        <div className="mt-3 space-y-2 rounded-card bg-tg-secondary-bg/60 p-3" aria-busy="true">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-28" />
        </div>
      )}

      {debounced.length < 3 && (
        <p className="mt-4 rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
          {tx(
            "Напиши или продиктуй одной фразой: что сделать, кому и к когда. Срок и исполнителя разберём сами.",
          )}
        </p>
      )}

      {draft && !draftQ.isLoading && (
        <div className="mt-3 rounded-card bg-tg-secondary-bg/60 p-3">
          <div className="text-sm font-medium text-tg-text">{draft.title}</div>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setPicking(picking === "assignee" ? null : "assignee");
              }}
              className="inline-flex min-h-9 items-center gap-1 rounded-full bg-tg-bg px-3 text-xs text-tg-text"
            >
              <Icon name="team" size={14} className="text-tg-hint" />
              {effectiveAssignee
                ? effectiveAssignee.name
                : isGroup
                  ? tx("Всему отделу")
                  : tx("Кому?")}
            </button>
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setPicking(picking === "due" ? null : "due");
              }}
              className="inline-flex min-h-9 items-center gap-1 rounded-full bg-tg-bg px-3 text-xs text-tg-text"
            >
              <Icon name="clock" size={14} className="text-tg-hint" />
              {effectiveDue ? (
                <>
                  {due.relative === "today" && `${tx("сегодня")} `}
                  {due.relative === "tomorrow" && `${tx("завтра")} `}
                  {due.rest}
                </>
              ) : (
                tx("Без срока")
              )}
            </button>
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setUrgent(effectivePriority !== "high");
              }}
              aria-pressed={effectivePriority === "high"}
              className={[
                "inline-flex min-h-9 items-center gap-1 rounded-full px-3 text-xs",
                effectivePriority === "high"
                  ? "bg-status-busy/20 text-status-busy"
                  : "bg-tg-bg text-tg-hint",
              ].join(" ")}
            >
              {tx("Срочно")}
            </button>
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setPhoto(!effectivePhoto);
              }}
              aria-pressed={effectivePhoto}
              className={[
                "inline-flex min-h-9 items-center gap-1 rounded-full px-3 text-xs",
                effectivePhoto ? "bg-tg-link/15 text-tg-text" : "bg-tg-bg text-tg-hint",
              ].join(" ")}
            >
              {tx("Фото")}
            </button>
          </div>

          <p className="mt-2 text-2xs text-tg-hint">
            {draft.due_kind === "shift_close"
              ? tx("Срок: конец смены")
              : tx("Срок взят из фразы")}
          </p>

          {/* Неоднозначность показывается, а не замалчивается: две Ани в
              составе — это два уведомления, одно из них не тому. */}
          {!effectiveAssignee && !isGroup && draft.candidates.length > 0 && (
            <div className="mt-2">
              <div className="text-2xs text-tg-hint">{tx("Кто именно:")}</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {draft.candidates.map((person) => (
                  <button
                    key={person.id}
                    type="button"
                    onClick={() => {
                      haptic("selection");
                      setChosenAssignee(person);
                      setPicking(null);
                    }}
                    className="min-h-9 rounded-full bg-tg-bg px-3 text-xs text-tg-text"
                  >
                    {person.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {picking === "assignee" && (
            <div className="mt-2 max-h-48 overflow-y-auto rounded-tile bg-tg-bg p-1">
              {peopleQ.isLoading && (
                <div className="space-y-1 p-1">
                  <Skeleton className="h-8" />
                  <Skeleton className="h-8" />
                </div>
              )}
              {peopleQ.data?.length === 0 && (
                <p className="p-2 text-xs text-tg-hint">{tx("В команде пока никого нет.")}</p>
              )}
              {peopleQ.data?.map((person) => (
                <button
                  key={person.id}
                  type="button"
                  onClick={() => {
                    haptic("selection");
                    setChosenAssignee(person);
                    setPicking(null);
                  }}
                  className="flex w-full min-h-10 items-center justify-between rounded-tile px-2 text-left text-xs text-tg-text active:bg-tg-secondary-bg"
                >
                  <span className="truncate">{person.name}</span>
                  <span className="ml-2 shrink-0 text-2xs text-tg-hint">
                    {person.position ?? ""}
                  </span>
                </button>
              ))}
            </div>
          )}

          {picking === "due" && (
            <div className="mt-2 space-y-1.5">
              <div className="flex flex-wrap gap-1.5">
                <DueOption
                  label={tx("К концу смены")}
                  onClick={() => {
                    setChosenDue(draft.due_kind === "shift_close" ? draft.due_at : null);
                    setPicking(null);
                  }}
                />
                <DueOption
                  label={tx("Через час")}
                  onClick={() => {
                    setChosenDue(new Date(Date.now() + 3_600_000).toISOString());
                    setPicking(null);
                  }}
                />
                <DueOption
                  label={tx("Завтра")}
                  onClick={() => {
                    const base = effectiveDue ? new Date(effectiveDue) : new Date();
                    base.setDate(base.getDate() + 1);
                    setChosenDue(base.toISOString());
                    setPicking(null);
                  }}
                />
                <DueOption
                  label={tx("Без срока")}
                  onClick={() => {
                    setChosenDue(null);
                    setPicking(null);
                  }}
                />
              </div>
              <label className="block text-2xs text-tg-hint">
                {tx("Точное время")}
                <input
                  type="datetime-local"
                  value={toLocalInput(effectiveDue)}
                  onChange={(event) => {
                    const value = event.target.value;
                    setChosenDue(value ? new Date(value).toISOString() : null);
                  }}
                  className="mt-1 block w-full min-h-11 rounded-tile bg-tg-bg px-3 text-xs text-tg-text outline-none"
                />
              </label>
            </div>
          )}
        </div>
      )}

      {draft?.unclear.includes("department") && (
        <p className="mt-2 text-xs text-status-busy">
          {tx("У тебя не указано подразделение — выбери человека, кому поручить.")}
        </p>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={!canCreate}
        className={[
          "mt-4 flex min-h-12 w-full items-center justify-center gap-2 rounded-full text-sm font-medium transition-colors",
          canCreate
            ? "bg-tg-button text-tg-button-text shadow-sm"
            : "bg-tg-secondary-bg text-tg-hint",
        ].join(" ")}
      >
        {create.isPending ? tx("Создаю…") : tx("Создать поручение")}
      </button>
      {!canCreate && debounced.length >= 3 && !isGroup && (
        <p className="mt-1.5 text-center text-2xs text-tg-hint">
          {tx("Выбери исполнителя — без него поручение не создать.")}
        </p>
      )}
    </BottomSheet>
  );
}

function DueOption({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={() => {
        haptic("selection");
        onClick();
      }}
      className="min-h-9 rounded-full bg-tg-bg px-3 text-xs text-tg-text"
    >
      {label}
    </button>
  );
}

/** ISO → `YYYY-MM-DDTHH:MM` для `<input type="datetime-local">` (местные часы). */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}
