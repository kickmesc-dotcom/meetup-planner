/**
 * GHG6 BD2: модалка-поповер, который открывается при клике по 🎂.
 *
 * Содержит две кнопки:
 *  - «✨ Креативное поздравление» — POST /api/birthdays/{user_id}/greeting,
 *    результат показывается в textarea с кнопкой «📋 Скопировать».
 *  - «📅 Назначить встречу» — закрывает поповер, выставляет
 *    `pollSheetPresetDate` и открывает PollSheet.
 *
 * Намеренно не реализован как сложный позиционируемый поповер: TG WebApp
 * на телефонах — узкая колонка, центрированная модалка надёжнее.
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { fetchBirthdayGreeting } from "@/api/birthdays";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import { Spinner } from "@/components/Spinner";

export default function BirthdayPopover() {
  const popover = useUI((s) => s.birthdayPopover);
  const setPopover = useUI((s) => s.setBirthdayPopover);
  const setPollSheet = useUI((s) => s.setShowPollSheet);
  const setPresetDate = useUI((s) => s.setPollSheetPresetDate);
  const [greeting, setGreeting] = useState<string | null>(null);

  const greetingMut = useMutation({
    mutationFn: () => {
      if (!popover) throw new Error("no_popover");
      return fetchBirthdayGreeting(popover.userId, popover.date);
    },
    onSuccess: (resp) => {
      haptic("success");
      setGreeting(resp.text);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  if (!popover) return null;

  const close = () => {
    setPopover(null);
    setGreeting(null);
  };

  const onAssignMeeting = () => {
    haptic("selection");
    setPresetDate(popover.date);
    setPopover(null);
    setGreeting(null);
    setPollSheet(true);
  };

  const onCopy = async () => {
    if (!greeting) return;
    try {
      await navigator.clipboard.writeText(greeting);
      haptic("success");
      void showAlert("Скопировано в буфер 📋");
    } catch {
      haptic("error");
      void showAlert("Не получилось скопировать — выдели текст вручную.");
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-black/40"
      onClick={close}
    >
      <div
        className="w-full max-w-md rounded-t-2xl bg-tg-bg p-4 pb-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="text-base font-semibold">
            🎂 {popover.displayName}
          </div>
          <button
            type="button"
            onClick={close}
            className="text-tg-hint text-lg leading-none px-2"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => greetingMut.mutate()}
            disabled={greetingMut.isPending}
            className="rounded-lg bg-tg-button text-tg-button-text py-2 px-3 text-sm font-medium active:scale-[0.98] disabled:opacity-60 flex items-center justify-center gap-2"
          >
            {greetingMut.isPending && <Spinner size={14} />}
            ✨ Креативное поздравление
          </button>

          {greeting && (
            <div className="mt-2 rounded-lg bg-tg-secondary-bg/60 p-2">
              <textarea
                value={greeting}
                onChange={(e) => setGreeting(e.target.value)}
                rows={4}
                className="w-full bg-transparent text-sm outline-none resize-none"
              />
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={onCopy}
                  className="rounded bg-tg-button/80 text-tg-button-text text-xs px-2 py-1"
                >
                  📋 Скопировать
                </button>
                <button
                  type="button"
                  onClick={() => greetingMut.mutate()}
                  className="rounded bg-tg-secondary-bg text-tg-text text-xs px-2 py-1"
                >
                  🔄 Ещё вариант
                </button>
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={onAssignMeeting}
            className="mt-1 rounded-lg bg-tg-secondary-bg text-tg-text py-2 px-3 text-sm font-medium active:scale-[0.98]"
          >
            📅 Назначить встречу
          </button>
        </div>
      </div>
    </div>
  );
}
