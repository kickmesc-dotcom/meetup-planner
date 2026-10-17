/**
 * GHG6 BD2: модалка-поповер, который открывается при клике по 🎂.
 *
 * Содержит кнопки:
 *  - «✨ Креативное поздравление» — POST /api/birthdays/{user_id}/greeting,
 *    результат показывается в textarea с кнопкой «📋 Скопировать».
 *  - GHG8 P2.4: после генерации — публикация текста из textarea в группу:
 *    «🤖 Пост от лица бота» (как есть) и «✍️ Пост от своего имени» (бот
 *    допишет «— Поздравил {имя}»; отправить за юзера напрямую TG не даёт).
 *  - «📅 Назначить встречу» — закрывает поповер, выставляет
 *    `pollSheetPresetDate` и открывает PollSheet.
 *
 * Намеренно не реализован как сложный позиционируемый поповер: TG WebApp
 * на телефонах — узкая колонка, центрированная модалка надёжнее.
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { fetchBirthdayGreeting, postBirthdayGreeting } from "@/api/birthdays";
import { useUI } from "@/store/ui";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import { Spinner } from "@/components/Spinner";

export default function BirthdayPopover() {
  const popover = useUI((s) => s.birthdayPopover);
  const setPopover = useUI((s) => s.setBirthdayPopover);
  const setPollSheet = useUI((s) => s.setShowPollSheet);
  const setPresetDate = useUI((s) => s.setPollSheetPresetDate);
  const setPresetQuestion = useUI((s) => s.setPollSheetPresetQuestion);
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

  // GHG8 P2.4: «Пост от лица бота» / «Пост от своего имени» (signed).
  const postMut = useMutation({
    mutationFn: (signed: boolean) => {
      if (!popover || !greeting?.trim()) throw new Error("no_greeting");
      return postBirthdayGreeting(popover.userId, greeting.trim(), signed);
    },
    onSuccess: (resp) => {
      haptic("success");
      void showAlert(
        resp.signed
          ? "Запостил в чат с подписью от тебя ✍️"
          : "Запостил в чат от лица бота 🤖",
      );
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
    // P2.4.c: get-together контекст — вопрос опроса сразу про ДР.
    setPresetQuestion(`Собираемся на ДР ${popover.displayName}?`);
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

  const onPost = async (signed: boolean) => {
    if (!greeting?.trim() || postMut.isPending) return;
    haptic("selection");
    const ok = await showConfirm(
      signed
        ? "Бот запостит этот текст в чат и подпишет, что поздравил — ты. Отправляем?"
        : "Бот запостит этот текст в чат от своего лица. Отправляем?",
    );
    if (!ok) return;
    postMut.mutate(signed);
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
              <div className="mt-2 flex flex-wrap gap-2">
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
              {/* GHG8 P2.4: публикация в группу. Кнопки доступны только когда
                  есть текст; во время отправки обе блокируются. */}
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void onPost(false)}
                  disabled={postMut.isPending || !greeting.trim()}
                  className="rounded bg-tg-button/80 text-tg-button-text text-xs px-2 py-1 disabled:opacity-60 flex items-center gap-1"
                >
                  {postMut.isPending && <Spinner size={10} />}
                  🤖 Пост от лица бота
                </button>
                <button
                  type="button"
                  onClick={() => void onPost(true)}
                  disabled={postMut.isPending || !greeting.trim()}
                  className="rounded bg-tg-secondary-bg text-tg-text text-xs px-2 py-1 disabled:opacity-60"
                >
                  ✍️ Пост от своего имени
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
