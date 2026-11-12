/**
 * Статус-страница (`/status`, этап 9 AAA_ROADMAP).
 *
 * Зачем отдельная страница, а не «напишите в поддержку». Во время инцидента
 * человеку нужно одно: работает ли сервис и когда обновлялись данные. Ответ
 * «у нас всё падает» без времени проверки бесполезен — через минуту он может
 * быть уже неверным.
 *
 * Источник — публичный `/api/meta`, который уже существует: отпечаток сборки,
 * состояние базы и `status`. Новая серверная ручка не нужна, а значит не может
 * разойтись с паспортом контейнера.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import { currentIntlLocale, useTx } from "@/i18n";
import { BusyLabel } from "@/components/BusyLabel";
import { statusView, type Meta } from "./status";

const REFRESH_MS = 30_000;

export default function StatusScreen() {
  const { tx } = useTx();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [failed, setFailed] = useState(false);
  const [updated, setUpdated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const data = await api<Meta>("/api/meta");
      setMeta(data);
      setFailed(false);
      setUpdated(new Date().toLocaleTimeString(currentIntlLocale()));
    } catch {
      setFailed(true);
      setMeta(null);
      setUpdated(new Date().toLocaleTimeString(currentIntlLocale()));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const view = meta ? statusView(meta) : null;
  const ok = view?.ok === true && !failed;

  return (
    <main className="min-h-full bg-tg-bg px-4 py-8 text-tg-text">
      <div className="mx-auto w-full max-w-md space-y-3">
        <header className="space-y-1">
          <h1 className="text-lg font-semibold">{tx("Статус")}</h1>
          <p className="text-xs text-tg-hint">
            {tx("Проверка обновляется каждые 30 секунд.")}
          </p>
        </header>

        {/* role="status" + aria-live: скринридер сообщает смену состояния, а не
            заставляет перечитывать страницу вручную. */}
        <div
          role="status"
          aria-live="polite"
          data-testid="status-badge"
          className={[
            "flex items-center gap-2 rounded-card p-3 text-sm font-semibold",
            ok
              ? "bg-status-free/15 text-status-free"
              : "bg-status-busy/15 text-status-busy",
          ].join(" ")}
        >
          <span
            aria-hidden
            className={[
              "h-2.5 w-2.5 rounded-full",
              ok ? "bg-status-free" : "bg-status-busy",
            ].join(" ")}
          />
          {failed
            ? tx("Нет связи с API")
            : ok
              ? tx("Работает")
              : tx("Есть проблемы")}
        </div>

        <dl className="divide-y divide-tg-secondary-bg rounded-card bg-tg-secondary-bg/40 px-3">
          <Row label={tx("API")} value={failed ? tx("не отвечает") : tx("отвечает")} />
          <Row
            label={tx("База")}
            value={
              view?.dbOk
                ? tx("доступна")
                : view?.dbError
                  ? `${tx("ошибка")}: ${view.dbError}`
                  : "—"
            }
          />
          <Row label={tx("Версия сборки")} value={view?.build ?? "—"} />
          <Row label={tx("Миграции")} value={view?.version ?? "—"} />
          <Row label={tx("Провайдер базы")} value={view?.provider ?? "—"} />
          <Row label={tx("Проверено")} value={updated ?? "—"} />
        </dl>

        <button
          type="button"
          onClick={() => void load()}
          disabled={busy}
          aria-busy={busy}
          className="min-h-11 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-60"
        >
          <BusyLabel busy={busy}>
            {busy ? tx("Проверяем…") : tx("Обновить")}
          </BusyLabel>
        </button>

        <p className="text-2xs leading-snug text-tg-hint">
          {tx(
            "Если работа не идёт — откройте runbook: там шаги для 503, базы и токена бота.",
          )}
        </p>
      </div>
    </main>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2.5 text-sm">
      <dt className="shrink-0 text-tg-hint">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium text-tg-text">{value}</dd>
    </div>
  );
}
