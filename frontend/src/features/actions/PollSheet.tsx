import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { addDays, format, startOfDay } from "date-fns";
import { createPoll } from "@/api/meetings";
import { fetchPollPresetsPublic } from "@/api/admin";
import type { User } from "@/types";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import { Checkbox } from "@/components/Checkbox";
import { Spinner } from "@/components/Spinner";
import Icon from "@/components/Icon";
import { currentIntlLocale, useTx } from "@/i18n";
import BottomSheet from "./BottomSheet";

interface Props {
  users: User[];
}

interface OptionDraft {
  /** YYYY-MM-DD */
  date: string;
  /** HH:MM, актуально только если includeTime=true */
  time: string;
}

/**
 * GHG6 PL1: дефолтные 3 варианта — пятница/суббота/воскресенье текущей недели.
 * Если сегодня уже после среды и пт/сб/вс прошли — берём следующую неделю.
 */
function defaultWeekendOptions(today: Date = new Date()): string[] {
  const t = startOfDay(today);
  // День недели: 0=Вс,1=Пн,...,5=Пт,6=Сб
  const dow = t.getDay();
  // Считаем, сколько дней прибавить до ближайшей пятницы.
  // Если сегодня <= среда — берём ближайшую пт текущей недели.
  // Если сегодня четверг и позже — берём пт следующей недели.
  let daysToFri: number;
  if (dow <= 4) {
    // 0..4 → 5 - dow (включая, если уже пт)
    daysToFri = 5 - dow;
  } else {
    // пт уже сегодня (5) или прошла (6) — следующая пт
    daysToFri = 5 - dow + 7;
  }
  // На самом деле инструкция: "пт/сб/вс текущей недели, если сегодня уже после
  // среды и они прошли — следующей". То есть пятница включительно — текущая.
  if (dow === 5) daysToFri = 0;
  const fri = addDays(t, daysToFri);
  const sat = addDays(fri, 1);
  const sun = addDays(fri, 2);
  return [fri, sat, sun].map((d) => format(d, "yyyy-MM-dd"));
}

/**
 * Подпись выбранной даты. Порядок дня и месяца — по локали, а не склейкой:
 * в английском он другой, и «Пт · 24.10» там читалось бы как опечатка.
 */
function fmtDate(d: string, locale: string): string {
  if (!d) return "";
  const dt = new Date(`${d}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return d;
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  }).format(dt);
}

export default function PollSheet(_props: Props) {
  const { tx } = useTx();
  const close = () => {
    useUI.getState().setShowPollSheet(false);
    // Очищаем пресеты после закрытия, чтобы следующий ручной вызов
    // PollSheet начинался с обычных дефолтов.
    useUI.getState().setPollSheetPresetDate(null);
    useUI.getState().setPollSheetPresetQuestion(null);
  };
  // GHG8 P2.4.c: ДР-поповер кладёт сюда «Собираемся на ДР {имя}?».
  const presetQuestion = useUI((s) => s.pollSheetPresetQuestion);
  const [question, setQuestion] = useState(
    presetQuestion ?? tx("Когда собираемся?"),
  );

  // Public presets подтягиваем — нужен дефолт-час, если включат «Указать время».
  const presetsQ = useQuery({
    queryKey: ["poll-presets"],
    queryFn: fetchPollPresetsPublic,
    staleTime: 60_000,
  });
  const defaultTime = useMemo(() => {
    const first = presetsQ.data?.[0]?.start;
    return first || "20:00";
  }, [presetsQ.data]);

  // GHG6 BD2: если поповер ДР открыл нас с пресетной датой — она становится
  // первым вариантом, следующие два — это +1 и +2 дня. Иначе обычные пт/сб/вс.
  const presetDate = useUI((s) => s.pollSheetPresetDate);
  const [options, setOptions] = useState<OptionDraft[]>(() => {
    if (presetDate) {
      try {
        const base = new Date(`${presetDate}T00:00:00`);
        return [base, addDays(base, 1), addDays(base, 2)].map((d) => ({
          date: format(d, "yyyy-MM-dd"),
          time: "20:00",
        }));
      } catch {
        // fallthrough → defaults
      }
    }
    return defaultWeekendOptions().map((d) => ({ date: d, time: "20:00" }));
  });
  const [includeTime, setIncludeTime] = useState(false);
  const [closesIn, setClosesIn] = useState(24);
  // G2.9: чекбокс пина опроса в чате. См. комментарий в GamesScreen.tsx
  // — серверный дефолт (admin_config.polls.pin_default) применяется только
  // при `pin=null`. Здесь стейт — boolean (явное намерение пользователя).
  const [pin, setPin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      createPoll({
        question: question.trim(),
        // Если время не указано — шлём YYYY-MM-DD; иначе ISO datetime в локальной зоне.
        options: options
          .filter((o) => !!o.date)
          .map((o) => {
            if (!includeTime) return o.date;
            const iso = new Date(`${o.date}T${o.time || defaultTime}:00`).toISOString();
            return iso;
          }),
        closes_in_hours: closesIn,
        pin,
      }),
    onSuccess: () => {
      haptic("success");
      close();
    },
    onError: (e) => {
      haptic("error");
      const human = humanizeApiError(e);
      setError(human);
      void showAlert(human);
    },
  });

  const setOption = (i: number, patch: Partial<OptionDraft>) => {
    setOptions((o) => o.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  };

  const addOption = () => {
    if (options.length >= 6) return;
    // Новый вариант — следующий день после последнего, время дефолтное.
    const last = options[options.length - 1]?.date;
    let next: string;
    try {
      next = format(addDays(new Date(`${last}T00:00:00`), 1), "yyyy-MM-dd");
    } catch {
      next = format(new Date(), "yyyy-MM-dd");
    }
    setOptions((o) => [...o, { date: next, time: defaultTime }]);
  };

  const removeOption = (i: number) => {
    if (options.length <= 2) return;
    setOptions((o) => o.filter((_, idx) => idx !== i));
  };

  const valid =
    question.trim().length > 0 &&
    options.length >= 2 &&
    options.every((o) => !!o.date) &&
    (!includeTime || options.every((o) => /^\d{2}:\d{2}$/.test(o.time)));

  return (
    <BottomSheet title={tx("Опрос в чат")} onClose={close}>
      <label className="text-sm">
        <div className="mb-1 text-xs text-tg-hint">{tx("Вопрос")}</div>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={255}
          className="w-full rounded-tile bg-tg-secondary-bg px-3 py-2"
        />
      </label>

      <div className="mt-3">
        <Checkbox
          checked={includeTime}
          onChange={setIncludeTime}
          label={tx("Указать время")}
          size="md"
        />
        {!includeTime && (
          <div className="mt-1 pl-1 text-xs text-tg-hint">
            {tx("Без времени — в опросе будет только день недели и число.")}
          </div>
        )}
      </div>

      <div className="mt-3 space-y-2">
        <div className="text-xs text-tg-hint">
          {tx("Варианты дат (2–6) · по умолчанию пт/сб/вс текущей недели")}
        </div>
        {options.map((o, i) => (
          <div
            key={i}
            className="rounded-tile bg-tg-secondary-bg/40 p-2 space-y-1.5"
          >
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={o.date}
                onChange={(e) => setOption(i, { date: e.target.value })}
                className="flex-1 rounded-tile bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
              />
              <span className="min-w-[78px] text-right text-xs text-tg-hint tabular-nums">
                {fmtDate(o.date, currentIntlLocale())}
              </span>
              {options.length > 2 && (
                <button
                  type="button"
                  onClick={() => removeOption(i)}
                  className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-status-busy/15 text-status-busy"
                  title={tx("Убрать")}
                  aria-label={tx("Убрать вариант")}
                >
                  <Icon name="close" size={14} />
                </button>
              )}
            </div>
            {includeTime && (
              <input
                type="time"
                value={o.time || defaultTime}
                onChange={(e) => setOption(i, { time: e.target.value })}
                className="w-[120px] rounded-tile bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text tabular-nums outline-none border border-transparent focus:border-tg-link"
              />
            )}
          </div>
        ))}
        {options.length < 6 && (
          <button
            type="button"
            onClick={addOption}
            className="w-full rounded-tile bg-tg-secondary-bg/60 py-2 text-sm"
          >
            {tx("+ ещё вариант")}
          </button>
        )}
      </div>

      {/* G2.9: чекбокс «Закрепить» — над выбором длительности, чтобы он не
          терялся между вариантами и кнопкой отправки.
          GHG7 P1.2 (попутно): .chk-tg + min-h-11 — тот же стандарт что и в
          GamesScreen.tsx, чтобы не было «чёрного на чёрном» и hit-target
          ≥44px. Не в чеклисте, но идентичный паттерн «чекбокс закрепить
          опрос», логично выровнять одним заходом. */}
      <label className="mt-3 flex items-center gap-2 cursor-pointer text-sm min-h-11 py-1.5">
        <input
          type="checkbox"
          checked={pin}
          onChange={(e) => setPin(e.target.checked)}
          className="chk-tg"
        />
        <span>
          <Icon
            name="pin"
            size={14}
            className="mr-1 inline-block align-[-2px]"
          />
          {tx("Закрепить опрос в чате")}
          <div className="text-xs text-tg-hint">
            {tx("Сразу после публикации бот пин-нёт сообщение (без шумного уведомления).")}
          </div>
        </span>
      </label>

      <label className="mt-3 block text-sm">
        <div className="mb-1 text-xs text-tg-hint">{tx("Закрыть через")}</div>
        <select
          value={closesIn}
          onChange={(e) => setClosesIn(Number(e.target.value))}
          className="w-full rounded-tile bg-tg-secondary-bg px-2 py-2"
        >
          <option value={6}>{tx("6 часов")}</option>
          <option value={12}>{tx("12 часов")}</option>
          <option value={24}>{tx("24 часа")}</option>
          <option value={48}>{tx("2 дня")}</option>
          <option value={72}>{tx("3 дня")}</option>
        </select>
      </label>

      {error && (
        <div className="mt-2 rounded-tile bg-status-busy/15 p-2 text-center text-sm text-status-busy">
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          haptic("medium");
          mut.mutate();
        }}
        disabled={!valid || mut.isPending}
        className="mt-4 w-full rounded-card bg-tg-button py-3 font-medium text-tg-button-text disabled:opacity-50 inline-flex items-center justify-center gap-2"
      >
        {mut.isPending && <Spinner />}
        {mut.isPending ? tx("Отправляем…") : tx("Отправить в чат")}
      </button>

      <button
        type="button"
        onClick={close}
        className="mt-2 w-full rounded-card bg-tg-secondary-bg py-3 font-medium"
      >
        {tx("Отмена")}
      </button>

      {/* Chip-presets времени убраны — они теперь применяются только когда
          включён чекбокс «Указать время» через default. */}
    </BottomSheet>
  );
}
