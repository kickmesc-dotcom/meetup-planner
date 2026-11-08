/**
 * Интеграции: ключи API и вебхуки (B2B_PLATFORM_PLAN, шаг 6.1).
 *
 * Зачем экран. До этого шага подключить CRM или учётную систему можно было
 * только через нас: интегратору нечего дать, кроме пароля владельца, а пароль
 * даёт всё, включая удаление организации. Здесь владелец выписывает ключ с
 * нужными правами и отзывает его одной кнопкой.
 *
 * Почему токен показывается один раз и крупно. В базе лежит только хеш;
 * «посмотреть позже» невозможно by design. Экран говорит это до создания, а
 * после — даёт скопировать, чтобы человек не искал значение в списке.
 *
 * Почему события вебхука подписаны, а не кодами. `employee.created` — это
 * контракт для интегратора; подпись «Новый сотрудник» — для владельца. Оба
 * видны рядом: код в мелкой строке, чтобы его можно было продиктовать.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createApiKey,
  createWebhook,
  deleteWebhook,
  EVENT_LABELS,
  fetchApiKeys,
  fetchDeliveries,
  fetchImportRuns,
  fetchWebhooks,
  revokeApiKey,
  SCOPE_LABELS,
  updateWebhook,
  type ApiKeyRow,
} from "@/api/integrations";
import { humanizeApiError } from "@/api/client";
import { Skeleton } from "@/components/Skeleton";
import { useTx } from "@/i18n";
import SubScreen from "./SubScreen";

const ALL_SCOPES = [
  "people.read",
  "schedule.read",
  "menu.read",
  "contacts.read",
  "people.write",
  "schedule.write",
];
const DEFAULT_SCOPES = ["people.read", "schedule.read", "menu.read"];
const ALL_EVENTS = ["employee.created", "employee.updated", "employee.deactivated"];

function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value)
    ? list.filter((item) => item !== value)
    : [...list, value];
}

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard?.writeText(value);
    return true;
  } catch {
    return false;
  }
}

function Check({
  checked,
  label,
  hint,
  onChange,
}: {
  checked: boolean;
  label: string;
  hint?: string;
  onChange: () => void;
}) {
  const { tx } = useTx();
  return (
    <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-tg-text">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="h-4 w-4 accent-tg-link"
      />
      <span className="min-w-0 flex-1">
        {tx(label)}
        {hint && <span className="block text-2xs text-tg-hint">{hint}</span>}
      </span>
    </label>
  );
}

export default function IntegrationsScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();

  const [keyName, setKeyName] = useState("");
  const [keyScopes, setKeyScopes] = useState<string[]>(DEFAULT_SCOPES);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState<number | null>(null);

  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(ALL_EVENTS);
  const [newSecret, setNewSecret] = useState<string | null>(null);

  const keys = useQuery({
    queryKey: ["integrations", "keys"],
    queryFn: fetchApiKeys,
    staleTime: 20_000,
    retry: false,
  });
  const hooks = useQuery({
    queryKey: ["integrations", "hooks"],
    queryFn: fetchWebhooks,
    staleTime: 20_000,
    retry: false,
  });
  const deliveries = useQuery({
    queryKey: ["integrations", "deliveries"],
    queryFn: () => fetchDeliveries(20),
    staleTime: 20_000,
    retry: false,
  });
  const importRuns = useQuery({
    queryKey: ["integrations", "import-runs"],
    queryFn: () => fetchImportRuns(10),
    staleTime: 20_000,
    retry: false,
  });

  const createKey = useMutation({
    mutationFn: () => createApiKey(keyName.trim(), keyScopes),
    onSuccess: (data) => {
      setNewToken(data.token);
      setCopied(false);
      setKeyName("");
      void qc.invalidateQueries({ queryKey: ["integrations", "keys"] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: number) => revokeApiKey(id),
    onSuccess: () => {
      setConfirmRevoke(null);
      void qc.invalidateQueries({ queryKey: ["integrations", "keys"] });
    },
  });

  const addHook = useMutation({
    mutationFn: () => createWebhook(url.trim(), events),
    onSuccess: (data) => {
      setNewSecret(data.secret);
      setUrl("");
      void qc.invalidateQueries({ queryKey: ["integrations", "hooks"] });
      void qc.invalidateQueries({ queryKey: ["integrations", "deliveries"] });
    },
  });

  const patchHook = useMutation({
    mutationFn: ({ id, isActive }: { id: number; isActive: boolean }) =>
      updateWebhook(id, { is_active: isActive }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations", "hooks"] });
    },
  });

  const removeHook = useMutation({
    mutationFn: (id: number) => deleteWebhook(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations", "hooks"] });
      void qc.invalidateQueries({ queryKey: ["integrations", "deliveries"] });
    },
  });

  const error =
    keys.error ?? hooks.error ?? deliveries.error ?? importRuns.error ??
    createKey.error ??
    revoke.error ?? addHook.error ?? patchHook.error ?? removeHook.error;

  return (
    <SubScreen
      title={tx("Интеграции")}
      subtitle={tx("Ключи API и вебхуки для внешних систем")}
      onBack={onBack}
    >
      {error && (
        <p className="rounded-tile bg-red-500/10 p-3 text-xs text-red-600" role="alert">
          {humanizeApiError(error)}
        </p>
      )}

      {/* ------------------------------ ключи ------------------------------ */}
      <section className="rounded-tile bg-tg-secondary-bg/60 p-3">
        <div className="text-sm font-semibold text-tg-text">{tx("Ключи API")}</div>
        <p className="mt-1 text-xs text-tg-hint">
          {tx(
            "Ключ открывает данные снаружи: чтение, а с правом записи — импорт людей и графика по CSV.",
          )}
        </p>

        {keys.isLoading && <Skeleton className="mt-2 h-16" />}

        {newToken && (
          <div className="mt-2 rounded-tile bg-tg-link/10 p-3">
            <p className="text-xs font-semibold text-tg-link">
              {tx("Ключ создан — скопируйте сейчас, второй раз он не покажется.")}
            </p>
            <code className="mt-1 block break-all rounded-tile bg-tg-bg p-2 text-2xs text-tg-text">
              {newToken}
            </code>
            <button
              type="button"
              onClick={() => {
                void copyText(newToken).then((ok) => setCopied(ok));
              }}
              className="mt-2 min-h-11 w-full rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link"
            >
              {copied ? tx("Скопировано") : tx("Скопировать")}
            </button>
          </div>
        )}

        <div
          role="group"
          aria-label={tx("Создать ключ")}
          className="mt-3 flex flex-col gap-2"
        >
          <label className="text-xs font-semibold text-tg-hint">
            {tx("Название")}
            <input
              value={keyName}
              aria-required="true"
              onChange={(event) => setKeyName(event.target.value)}
              placeholder={tx("Например: CRM")}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg px-3 text-sm font-normal text-tg-text"
            />
          </label>
          <p className="mt-1 text-2xs text-tg-hint">
            {tx("Показывается один раз — сохраните ключ.")}
          </p>
          {ALL_SCOPES.map((scope) => (
            <Check
              key={scope}
              checked={keyScopes.includes(scope)}
              label={SCOPE_LABELS[scope]}
              hint={scope}
              onChange={() => setKeyScopes((prev) => toggle(prev, scope))}
            />
          ))}
          <button
            type="button"
            disabled={createKey.isPending || keyName.trim().length === 0}
            aria-busy={createKey.isPending}
            onClick={() => createKey.mutate()}
            className="min-h-11 w-full rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
          >
            {createKey.isPending ? tx("Создаём…") : tx("Создать ключ")}
          </button>
        </div>

        {keys.data && keys.data.length > 0 ? (
          <ul className="mt-3 overflow-hidden rounded-card border border-tg-secondary-bg">
            {keys.data.map((key: ApiKeyRow, index) => (
              <li
                key={key.id}
                className={[
                  "px-3 py-2 text-sm",
                  index > 0 ? "border-t border-tg-secondary-bg" : "",
                ].join(" ")}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate font-medium text-tg-text">
                    {key.name}
                  </span>
                  <span className="shrink-0 text-2xs text-tg-hint">
                    {key.revoked_at ? tx("Отозван") : tx("Живой")}
                  </span>
                </div>
                <div className="truncate font-mono text-2xs text-tg-hint">
                  {key.prefix}…
                </div>
                <div className="text-2xs text-tg-hint">
                  {key.scopes.map((scope) => tx(SCOPE_LABELS[scope] ?? scope)).join(" · ")}
                </div>
                <div className="text-2xs text-tg-hint">
                  {tx("Использован")}: {shortDate(key.last_used_at)}
                </div>
                {!key.revoked_at &&
                  (confirmRevoke === key.id ? (
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        disabled={revoke.isPending}
                        aria-busy={revoke.isPending}
                        onClick={() => revoke.mutate(key.id)}
                        className="min-h-9 flex-1 rounded-tile bg-red-500/10 text-xs font-semibold text-red-600"
                      >
                        {tx("Да, отозвать")}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmRevoke(null)}
                        className="min-h-9 flex-1 rounded-tile bg-tg-bg text-xs text-tg-hint"
                      >
                        {tx("Отмена")}
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmRevoke(key.id)}
                      className="mt-2 min-h-9 w-full rounded-tile bg-tg-bg text-xs text-red-600"
                    >
                      {tx("Отозвать")}
                    </button>
                  ))}
              </li>
            ))}
          </ul>
        ) : (
          !keys.isLoading && (
            <p className="mt-2 text-xs text-tg-hint">{tx("Ключей пока нет.")}</p>
          )
        )}
      </section>

      {/* ----------------------------- вебхуки ----------------------------- */}
      <section className="rounded-tile bg-tg-secondary-bg/60 p-3">
        <div className="text-sm font-semibold text-tg-text">{tx("Вебхуки")}</div>
        <p className="mt-1 text-xs text-tg-hint">
          {tx(
            "События уходят на ваш адрес сразу, а не по опросу. Подпись — в заголовке X-SemiTask-Signature.",
          )}
        </p>

        {newSecret && (
          <div className="mt-2 rounded-tile bg-amber-500/10 p-3">
            <p className="text-xs font-semibold text-amber-700">
              {tx("Секрет создан — им проверяется подпись. Второй раз не покажется.")}
            </p>
            <code className="mt-1 block break-all rounded-tile bg-tg-bg p-2 text-2xs text-tg-text">
              {newSecret}
            </code>
          </div>
        )}

        <div className="mt-3 flex flex-col gap-2">
          <label className="text-xs font-semibold text-tg-hint">
            {tx("Адрес приёмника")}
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://crm.example.com/hooks/semitask"
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg px-3 text-sm font-normal text-tg-text"
            />
          </label>
          {ALL_EVENTS.map((event) => (
            <Check
              key={event}
              checked={events.includes(event)}
              label={EVENT_LABELS[event]}
              hint={event}
              onChange={() => setEvents((prev) => toggle(prev, event))}
            />
          ))}
          <button
            type="button"
            disabled={addHook.isPending || url.trim().length < 8 || events.length === 0}
            aria-busy={addHook.isPending}
            onClick={() => addHook.mutate()}
            className="min-h-11 w-full rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
          >
            {addHook.isPending ? tx("Добавляем…") : tx("Добавить вебхук")}
          </button>
        </div>

        {hooks.data && hooks.data.length > 0 ? (
          <ul className="mt-3 space-y-2">
            {hooks.data.map((hook) => (
              <li key={hook.id} className="rounded-card border border-tg-secondary-bg p-2">
                <div className="break-all text-xs font-medium text-tg-text">
                  {hook.url}
                </div>
                <div className="mt-1 text-2xs text-tg-hint">
                  {hook.events
                    .map((event) => tx(EVENT_LABELS[event] ?? event))
                    .join(" · ")}
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-2xs">
                  <span className={hook.is_active ? "text-tg-link" : "text-tg-hint"}>
                    {hook.is_active ? tx("Включён") : tx("Выключен")}
                  </span>
                  <span className="text-tg-hint">
                    {tx("Ошибок подряд: {count}", { count: String(hook.failures) })}
                  </span>
                </div>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    disabled={patchHook.isPending}
                    aria-busy={patchHook.isPending}
                    onClick={() =>
                      patchHook.mutate({ id: hook.id, isActive: !hook.is_active })
                    }
                    className="min-h-9 flex-1 rounded-tile bg-tg-bg text-xs text-tg-text"
                  >
                    {hook.is_active ? tx("Выключить") : tx("Включить")}
                  </button>
                  <button
                    type="button"
                    disabled={removeHook.isPending}
                    aria-busy={removeHook.isPending}
                    onClick={() => removeHook.mutate(hook.id)}
                    className="min-h-9 flex-1 rounded-tile bg-red-500/10 text-xs font-semibold text-red-600"
                  >
                    {tx("Удалить")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          !hooks.isLoading && (
            <p className="mt-2 text-xs text-tg-hint">{tx("Вебхуков пока нет.")}</p>
          )
        )}
      </section>

      {/* --------------------------- журнал доставок ----------------------- */}
      <section>
        <div className="mb-2 px-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
          {tx("Последние доставки")}
        </div>
        {deliveries.data && deliveries.data.length > 0 ? (
          <ul className="overflow-hidden rounded-card border border-tg-secondary-bg">
            {deliveries.data.map((row, index) => (
              <li
                key={row.id}
                className={[
                  "px-3 py-2 text-sm",
                  index > 0 ? "border-t border-tg-secondary-bg" : "",
                ].join(" ")}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate text-tg-text">
                    {tx(EVENT_LABELS[row.event] ?? row.event)}
                  </span>
                  <span
                    className={[
                      "shrink-0 text-2xs",
                      row.status === "sent"
                        ? "text-tg-link"
                        : row.status === "failed"
                          ? "text-red-600"
                          : "text-tg-hint",
                    ].join(" ")}
                  >
                    {row.status === "sent"
                      ? tx("Отправлено")
                      : row.status === "failed"
                        ? tx("Ошибка")
                        : tx("В очереди")}
                  </span>
                </div>
                <div className="text-2xs text-tg-hint">
                  {shortDate(row.created_at)} ·{" "}
                  {tx("Попыток: {count}", { count: String(row.attempts) })}
                  {row.response_code ? ` · HTTP ${row.response_code}` : ""}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
            {tx("Доставок пока нет.")}
          </p>
        )}
      </section>
      {/* ------------------------ журнал импортов по API --------------------- */}
      <section>
        <div className="mb-2 px-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
          {tx("Импорты по API")}
        </div>
        {importRuns.data && importRuns.data.length > 0 ? (
          <ul className="overflow-hidden rounded-card border border-tg-secondary-bg">
            {importRuns.data.map((row, index) => (
              <li
                key={row.id}
                className={[
                  "px-3 py-2 text-sm",
                  index > 0 ? "border-t border-tg-secondary-bg" : "",
                ].join(" ")}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate text-tg-text">
                    {row.kind === "people" ? tx("Люди") : tx("График")}
                    {row.filename ? ` · ${row.filename}` : ""}
                  </span>
                  <span
                    className={[
                      "shrink-0 text-2xs",
                      row.errors > 0 ? "text-red-600" : "text-tg-link",
                    ].join(" ")}
                  >
                    {row.errors > 0
                      ? tx("Ошибок: {count}", { count: String(row.errors) })
                      : tx("Без ошибок")}
                  </span>
                </div>
                <div className="text-2xs text-tg-hint">
                  {shortDate(row.created_at)} ·{" "}
                  {tx("Создано: {count}", { count: String(row.created) })}
                  {row.updated > 0
                    ? ` · ${tx("Обновлено: {count}", {
                        count: String(row.updated),
                      })}`
                    : ""}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
            {tx("Импортов по ключу пока не было.")}
          </p>
        )}
      </section>

    </SubScreen>
  );
}
