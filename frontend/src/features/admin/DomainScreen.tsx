import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearOrgDomain,
  fetchOrgDomain,
  saveOrgDomain,
  verifyOrgDomain,
} from "@/api/orgs";
import { humanizeApiError, looksLikeCode } from "@/api/client";
import { Skeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";
import { haptic, showAlert } from "@/tg/webapp";
import { useTx } from "@/i18n";

/**
 * «Свой домен» (06.11.2026).
 *
 * Зачем экран, если домен можно вписать в конфиг. Домен — это адрес, по
 * которому сотрудники открывают приложение; владелец должен видеть, что уже
 * работает, что ждёт подтверждения и что именно положить на домен. Инструкция
 * рождается из ответа сервера (путь и токен), поэтому она не разъедется с
 * проверкой.
 *
 * Почему домен не включается сразу. Сохранённый, но неподтверждённый адрес —
 * это чужая наклейка: без файла с токеном любой мог бы занять домен, который
 * ему не принадлежит. Платформенная ссылка работает всегда.
 */
const ERROR_TEXT: Record<string, string> = {
  bad_domain: "Это не похоже на домен вида salon.ru.",
  domain_reserved: "Платформенный адрес занять нельзя.",
  domain_taken: "Этот домен уже занят другой организацией.",
  domain_not_set: "Сначала сохраните домен.",
  verify_failed:
    "Не удалось прочитать файл на домене — проверьте, что он открывается по https.",
  verify_mismatch: "В файле нет нашего токена — проверьте содержимое.",
};

export default function DomainScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["org-domain"],
    queryFn: fetchOrgDomain,
    retry: false,
    staleTime: 30_000,
  });
  const [value, setValue] = useState("");
  const data = q.data;

  useEffect(() => {
    setValue(data?.domain ?? "");
  }, [data?.domain]);

  const fail = (error: unknown) => {
    const code = humanizeApiError(error);
    void showAlert(
      tx(
        ERROR_TEXT[code] ??
          (looksLikeCode(code)
            ? "Не получилось. Попробуем ещё раз?"
            : code),
      ),
    );
  };

  const save = useMutation({
    mutationFn: (domain: string) => saveOrgDomain(domain),
    onSuccess: (row) => {
      haptic("success");
      qc.setQueryData(["org-domain"], row);
    },
    onError: fail,
  });

  const verify = useMutation({
    mutationFn: () => verifyOrgDomain(),
    onSuccess: (row) => {
      haptic("success");
      qc.setQueryData(["org-domain"], row);
      void showAlert(
        row.verified ? tx("Домен подтверждён.") : tx("Домен пока не подтверждён."),
      );
    },
    onError: fail,
  });

  const clear = useMutation({
    mutationFn: () => clearOrgDomain(),
    onSuccess: (row) => {
      haptic("success");
      qc.setQueryData(["org-domain"], row);
      void showAlert(tx("Домен снят."));
    },
    onError: fail,
  });

  const busy = save.isPending || verify.isPending || clear.isPending;
  const line = `${data?.verify_prefix ?? ""}${data?.token ?? ""}`;

  return (
    <SubScreen
      title={tx("Свой домен")}
      subtitle={tx("Адрес входа для команды вместо платформенной ссылки")}
      onBack={onBack}
    >
      {q.isLoading && <Skeleton className="h-24" />}

      {data && (
        <>
          <section className="rounded-card bg-tg-secondary-bg/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-tg-text">
                  {data.domain ?? tx("Домен не задан")}
                </div>
                <div className="text-xs text-tg-hint">
                  {data.domain
                    ? data.verified
                      ? tx("Подтверждён — можно открывать приложение по этому адресу.")
                      : tx("Ждёт подтверждения: пока работает платформенная ссылка.")
                    : tx("Работает платформенная ссылка — свой домен её дополнит.")}
                </div>
              </div>
              {data.domain && (
                <span
                  className={[
                    "shrink-0 rounded-full px-2 py-0.5 text-2xs",
                    data.verified
                      ? "bg-green-500/15 text-green-600"
                      : "bg-tg-secondary-bg text-tg-hint",
                  ].join(" ")}
                >
                  {data.verified ? tx("Подтверждён") : tx("Не подтверждён")}
                </span>
              )}
            </div>

            <label className="mt-3 block text-xs text-tg-hint" htmlFor="org-domain">
              {tx("Домен")}
            </label>
            <div className="mt-1 flex gap-2">
              <input
                id="org-domain"
                value={value}
                onChange={(event) => setValue(event.target.value)}
                placeholder="cabinet.salon.ru"
                autoCapitalize="none"
                autoCorrect="off"
                inputMode="url"
                className="min-h-11 min-w-0 flex-1 rounded-tile bg-tg-bg px-2 text-sm text-tg-text"
              />
              <button
                type="button"
                disabled={busy || !value.trim() || value.trim() === data.domain}
                onClick={() => save.mutate(value.trim())}
                className="min-h-11 shrink-0 rounded-tile bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {tx("Сохранить")}
              </button>
            </div>
          </section>

          {data.domain && data.token && (
            <section className="rounded-card bg-tg-secondary-bg/40 p-3">
              <div className="text-sm font-semibold text-tg-text">
                {tx("Как подтвердить")}
              </div>
              <p className="mt-1 text-xs text-tg-hint">
                {tx(
                  "Создайте на своём домене файл по адресу ниже — он должен открываться по https без входа.",
                )}
              </p>
              <code className="mt-2 block break-all rounded-tile bg-tg-bg p-2 text-xs text-tg-text">
                https://{data.domain}
                {data.verify_path}
              </code>
              <p className="mt-2 text-xs text-tg-hint">
                {tx("Содержимое файла — одна строка:")}
              </p>
              <code className="mt-1 block break-all rounded-tile bg-tg-bg p-2 text-xs text-tg-text">
                {line}
              </code>
              <p className="mt-2 text-2xs text-tg-hint">
                {tx(
                  "Токен меняется вместе с доменом: старая наклейка на прежнем адресе ничего не подтверждает.",
                )}
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => verify.mutate()}
                  className="min-h-11 flex-1 rounded-tile bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
                >
                  {tx("Проверить")}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => clear.mutate()}
                  className="min-h-11 rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text disabled:opacity-50"
                >
                  {tx("Снять")}
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </SubScreen>
  );
}
