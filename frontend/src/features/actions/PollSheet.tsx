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

const DOW_RU = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"] as const;

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

function fmtDateRu(d: string): string {
  if (!d) return "";
  try {
    const dt = new Date(d + "T00:00:00");
    const dow = DOW_RU[dt.getDay()];
    const dm = format(dt, "dd.MM");
    return `${dow} · ${dm}`;
  } catch {
    return d;
  }
}

export default function PollSheet(_props: Props) {
  const close = () => {
    useUI.getState().setShowPollSheet(false);
    // Очищаем пресетную дату после закрытия, чтобы следующий ручной вызов
    // PollSheet начинался с обычных дефолтов.
    useUI.getState().setPollSheetPresetDate(null);
  };
  const [question, setQuestion] = useState("Когда собираемся?");

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
    <BottomSheet title="📊 Опрос в чат" onClose={close}>
      <label className="text-sm">
        <div className="mb-1 text-xs text-tg-hint">Вопрос</div>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={255}
          className="w-full rounded-lg bg-tg-secondary-bg px-3 py-2"
        />
      </label>

      <div className="mt-3">
        <Checkbox
          checked={includeTime}
          onChange={setIncludeTime}
          label="Указать время"
          size="md"
        />
        {!includeTime && (
          <div className="mt-1 pl-1 text-[11px] text-tg-hint">
            Без времени — в опросе будет только день недели и число.
          </div>
        )}
      </div>

      <div className="mt-3 space-y-2">
        <div className="text-xs text-tg-hint">
          Варианты дат (2–6) · по умолчанию пт/сб/вс текущей недели
        </div>
        {options.map((o, i) => (
          <div
            key={i}
            className="rounded-lg bg-tg-secondary-bg/40 p-2 space-y-1.5"
          >
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={o.date}
                onChange={(e) => setOption(i, { date: e.target.value })}
                className="flex-1 rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
              />
              <span className="min-w-[78px] text-right text-xs text-tg-hint tabular-nums">
                {fmtDateRu(o.date)}
              </span>
              {options.length > 2 && (
                <button
                  type="button"
                  onClick={() => removeOption(i)}
                  className="min-h-9 min-w-9 rounded-md bg-status-busy/15 px-2 text-xs text-status-busy"
                  title="Убрать"
                >
                  ✕
                </button>
              )}
            </div>
            {includeTime && (
              <input
                type="time"
                value={o.time || defaultTime}
                onChange={(e) => setOption(i, { time: e.target.value })}
                className="w-[120px] rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text tabular-nums outline-none border border-transparent focus:border-tg-link"
              />
            )}
          </div>
        ))}
        {options.length < 6 && (
          <button
            type="button"
            onClick={addOption}
            className="w-full rounded-lg bg-tg-secondary-bg/60 py-2 text-sm"
          >
            + ещё вариант
          </button>
        )}
      </div>

      {/* G2.9: чекбокс «Закрепить» — над выбором длительности, чтобы он не
          терялся между вариантами и кнопкой отправки. */}
      <label className="mt-3 flex items-start gap-2 cursor-pointer text-sm">
        <input
          type="checkbox"
          checked={pin}
          onChange={(e) => setPin(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          📌 Закрепить опрос в чате
          <div className="text-[11px] text-tg-hint">
            Сразу после публикации бот пин-нёт сообщение (без шумного
            уведомления).
          </div>
        </span>
      </label>

      <label className="mt-3 block text-sm">
        <div className="mb-1 text-xs text-tg-hint">Закрыть через</div>
        <select
          value={closesIn}
          onChange={(e) => setClosesIn(Number(e.target.value))}
          className="w-full rounded-lg bg-tg-secondary-bg px-2 py-2"
        >
          <option value={6}>6 часов</option>
          <option value={12}>12 часов</option>
          <option value={24}>24 часа</option>
          <option value={48}>2 дня</option>
          <option value={72}>3 дня</option>
        </select>
      </label>

      {error && (
        <div className="mt-2 rounded-lg bg-status-busy/15 p-2 text-center text-sm text-status-busy">
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
        className="mt-4 w-full rounded-xl bg-tg-button py-3 font-medium text-tg-button-text disabled:opacity-50 inline-flex items-center justify-center gap-2"
      >
        {mut.isPending && <Spinner />}
        {mut.isPending ? "Отправляем…" : "Отправить в чат"}
      </button>

      <button
        type="button"
        onClick={close}
        className="mt-2 w-full rounded-xl bg-tg-secondary-bg py-3 font-medium"
      >
        Отмена
      </button>

      {/* Chip-presets времени убраны — они теперь применяются только когда
          включён чекбокс «Указать время» через default. */}
    </BottomSheet>
  );
}
