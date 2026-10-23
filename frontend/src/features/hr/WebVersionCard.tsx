import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createAccessLink,
  fetchAccessLinks,
  revokeAccessLink,
  type AccessLink,
} from "@/api/access";
import { clearAccessToken, humanizeApiError, isEndpointMissing } from "@/api/client";
import Icon from "@/components/Icon";
import { copyText } from "@/lib/clipboard";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";

/**
 * «Веб-версия»: открыть приложение на компьютере.
 *
 * Зачем карточка в профиле, а не только команда `/app`. Сотрудник ищет
 * настройки там, где всё остальное, а не в чате. Здесь же видно, **какие**
 * ссылки выданы и когда последний раз использованы, — это единственный способ
 * заметить чужой вход.
 *
 * Ссылка показывается один раз: сервер хранит только хеш и повторить её не
 * может. Поэтому после выпуска URL виден прямо на экране с кнопкой
 * «Скопировать» — Telegram-webview не всегда умеет `navigator.clipboard`,
 * поэтому есть запасной путь через скрытую textarea.
 */
export default function WebVersionCard() {
  const qc = useQueryClient();
  const [fresh, setFresh] = useState<{ url: string; expires_at: string } | null>(
    null,
  );
  const [copied, setCopied] = useState(false);

  const linksQ = useQuery({
    queryKey: ["access-links"],
    queryFn: fetchAccessLinks,
    retry: false,
    staleTime: 60_000,
  });

  const create = useMutation({
    mutationFn: () => createAccessLink(),
    onSuccess: (created) => {
      haptic("success");
      setFresh({ url: created.url, expires_at: created.expires_at });
      setCopied(false);
      void qc.invalidateQueries({ queryKey: ["access-links"] });
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const revoke = useMutation({
    mutationFn: (id: number) => revokeAccessLink(id),
    onSuccess: () => {
      haptic("light");
      void qc.invalidateQueries({ queryKey: ["access-links"] });
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  // Старый бэкенд (до пересборки) отвечает 404 — карточку просто не рисуем,
  // чтобы не показывать кнопку, которая гарантированно упадёт.
  if (linksQ.isError && isEndpointMissing(linksQ.error)) return null;

  const links = linksQ.data ?? [];
  const current = links.find((l) => l.is_current);

  return (
    <section
      data-testid="web-version-card"
      className="rounded-card bg-tg-secondary-bg/60 p-3"
    >
      <div className="flex items-start gap-2">
        <Icon name="layout" size={18} className="mt-0.5 text-tg-hint" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-tg-text">Веб-версия</h3>
          <p className="mt-1 text-xs text-tg-hint">
            На компьютере окно Telegram узкое. Открой ссылку в браузере — там
            широкий экран с разделами и сводкой смены.
          </p>
          <p className="mt-1 text-2xs text-tg-hint">
            На телефоне ссылку можно поставить на домашний экран: в Safari —
            «Поделиться → На экран Домой», в Chrome — «Установить приложение».
            Откроется без адресной строки, как обычная программа.
          </p>
        </div>
      </div>

      <button
        type="button"
        disabled={create.isPending}
        onClick={() => create.mutate()}
        className="mt-2 min-h-11 w-full rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-60"
      >
        {create.isPending ? "Готовлю ссылку…" : "Создать ссылку для компьютера"}
      </button>

      {fresh && (
        <div className="mt-2 rounded-tile bg-tg-bg/70 p-2">
          <p className="text-2xs text-tg-hint">
            Ссылка показывается один раз и работает как пароль — не пересылай
            её. Действует до {new Date(fresh.expires_at).toLocaleDateString("ru-RU")}.
          </p>
          <code className="mt-1 block break-all text-2xs text-tg-text">
            {fresh.url}
          </code>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => {
                void copyText(fresh.url).then((ok) => {
                  setCopied(ok);
                  haptic(ok ? "success" : "error");
                });
              }}
              className="min-h-9 flex-1 rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text"
            >
              {copied ? "Скопировано" : "Скопировать"}
            </button>
            <a
              href={fresh.url}
              target="_blank"
              rel="noreferrer"
              className="grid min-h-9 flex-1 place-items-center rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-link"
            >
              Открыть
            </a>
          </div>
        </div>
      )}

      {links.length > 0 && (
        <ul className="mt-2 space-y-1">
          {links.map((link) => (
            <LinkRow
              key={link.id}
              link={link}
              busy={revoke.isPending}
              onRevoke={async () => {
                const ok = await showConfirm(
                  "Отозвать ссылку? Браузер, где она открыта, потеряет доступ.",
                );
                if (ok) revoke.mutate(link.id);
              }}
            />
          ))}
        </ul>
      )}

      {current && (
        <button
          type="button"
          onClick={() => {
            haptic("light");
            clearAccessToken();
            window.location.reload();
          }}
          className="mt-2 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-xs text-tg-hint"
        >
          Выйти из веб-версии на этом устройстве
        </button>
      )}
    </section>
  );
}

function LinkRow({
  link,
  busy,
  onRevoke,
}: {
  link: AccessLink;
  busy: boolean;
  onRevoke: () => void;
}) {
  const used = link.last_used_at
    ? `использована ${new Date(link.last_used_at).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })}`
    : "ещё не открывалась";
  return (
    <li className="flex items-center gap-2 rounded-tile bg-tg-bg/40 px-2 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-tg-text">
          {link.label || "Ссылка"}
          {link.is_current ? " · это устройство" : ""}
        </div>
        <div className="truncate text-2xs text-tg-hint">
          {link.is_active ? used : "отозвана"}
        </div>
      </div>
      {link.is_active && (
        <button
          type="button"
          disabled={busy}
          onClick={onRevoke}
          className="min-h-8 shrink-0 rounded-full px-2 text-2xs text-tg-hint disabled:opacity-50"
        >
          Отозвать
        </button>
      )}
    </li>
  );
}
