import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { requestEmailVerification } from "@/api/auth";
import { fetchMe } from "@/api/availability";
import { humanizeApiError } from "@/api/client";
import Icon from "@/components/Icon";
import { haptic, showAlert } from "@/tg/webapp";
import { useTx } from "@/i18n";
/**
 * «Подтвердите почту» — только пока адрес не подтверждён.
 *
 * Зачем карточка, а не только письмо при регистрации. Письмо теряется: спам,
 * опечатка в адресе, закрытая вкладка. Без подтверждения человек продолжает
 * работать, но адрес нельзя считать своим — а на него уходят сброс пароля и
 * приглашения. Поэтому кнопка живёт там, где человек ищет настройки.
 */
export default function EmailVerifyCard() {
  const { tx } = useTx();
  const meQ = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    retry: false,
    staleTime: 60_000,
  });
  const [sent, setSent] = useState(false);

  const send = useMutation({
    mutationFn: () => requestEmailVerification(),
    onSuccess: (res) => {
      haptic("success");
      if (res.already) {
        void meQ.refetch();
        return;
      }
      setSent(true);
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const me = meQ.data;
  if (!me?.email || me.email_verified) return null;

  return (
    <section
      data-testid="email-verify-card"
      className="rounded-card bg-tg-secondary-bg/60 p-3"
    >
      <div className="flex items-start gap-2">
        <Icon name="lock" size={18} className="mt-0.5 text-tg-hint" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-tg-text">{tx("Почта не подтверждена")}</h3>
          <p className="mt-1 text-xs text-tg-hint">
            {me.email}. Подтверди адрес, чтобы не потерять доступ к аккаунту:
            на него приходит сброс пароля и приглашения.
          </p>
        </div>
      </div>

      {sent ? (
        <p className="mt-2 rounded-tile bg-tg-bg/70 p-2 text-2xs text-tg-hint">{tx(
          "Письмо отправлено. Ссылка живёт двое суток — открой её на любом устройстве, вход не нужен.",
        )}</p>
      ) : (
        <button
          type="button"
          disabled={send.isPending}
          onClick={() => send.mutate()}
          className="mt-2 min-h-11 w-full rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-60"
        >
          {send.isPending ? tx("Отправляю…") : tx("Подтвердить почту")}
        </button>
      )}
    </section>
  );
}
