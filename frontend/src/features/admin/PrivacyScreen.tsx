/**
 * Данные и приватность (B2B_PLATFORM_PLAN, шаг 5.5).
 *
 * Зачем экран. «Удалите наши данные» и «дайте копию» до этого шага означали
 * письмо в поддержку и ручную работу в базе. Для B2B это не мелочь: клиент
 * выбирает сервис в том числе по тому, может ли он уйти.
 *
 * Почему удаление — с вводом кода, а не с кнопкой «Да». Удаление необратимо;
 * диалог подтверждения закрывают не читая, а код организации нужно набрать
 * руками. Это единственная защита, которая работает на телефоне в спешке.
 *
 * Почему сроки приходят с сервера. Числа на экране и в `docs/PRIVACY.md`
 * должны быть одним источником: обещание «храним 30 дней» проверяется по тому,
 * что реально делает планировщик, а не по тексту на странице.
 */
import { useState } from "react";
import FormField from "@/components/FormField";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelOrgDeletion,
  fetchAudit,
  fetchOrgExport,
  fetchPrivacy,
  requestOrgDeletion,
  rotateOrgLinks,
  saveExportFile,
  type PrivacyState,
} from "@/api/privacy";
import { fetchMeta } from "@/api/meta";
import { humanizeApiError } from "@/api/client";
import { Skeleton } from "@/components/Skeleton";
import { BusyLabel } from "@/components/BusyLabel";
import { formatDateTime } from "@/lib/format";
import { useTx } from "@/i18n";
import SubScreen from "./SubScreen";

/** Код события → подпись. Сервер отдаёт код, текст живёт здесь. */
const ACTION_TEXT: Record<string, string> = {
  "data.exported": "Выгрузка данных",
  "org.delete_requested": "Запрошено удаление",
  "org.delete_canceled": "Удаление отменено",
  "org.links_rotated": "Отозваны ссылки на фото и календарь",
  "member.role_changed": "Смена роли",
  "invitation.created": "Создано приглашение",
  "invitation.revoked": "Отозвано приглашение",
};


export default function PrivacyScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [confirmRotate, setConfirmRotate] = useState(false);

  const q = useQuery({
    queryKey: ["privacy"],
    queryFn: fetchPrivacy,
    staleTime: 30_000,
    retry: false,
  });
  const audit = useQuery({
    queryKey: ["privacy", "audit"],
    queryFn: () => fetchAudit(20),
    staleTime: 30_000,
    retry: false,
  });
  // Возможности бэкенда: на Amvera сборка может отставать, и ручки отзыва
  // там ещё нет. Скрываем только при явном ответе без неё — если `/api/meta`
  // недоступен, оптимистично показываем, а не прячем рабочее действие.
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: fetchMeta,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const canRotate =
    !meta.data || meta.data.features.includes("org.links.rotate");

  const download = useMutation({
    mutationFn: async (slug: string) => {
      const data = await fetchOrgExport();
      saveExportFile(slug, data);
    },
    onSuccess: () => {
      setNote(tx("Данные выгружены — файл скачался."));
      // Выгрузка — событие журнала: перечитываем, чтобы человек увидел
      // собственную запись, а не сомневался, сработало ли.
      void qc.invalidateQueries({ queryKey: ["privacy", "audit"] });
    },
  });

  const remove = useMutation({
    mutationFn: () => requestOrgDeletion(confirm.trim()),
    onSuccess: (state) => {
      qc.setQueryData<PrivacyState>(["privacy"], (old) =>
        old ? { ...old, deletion: state } : old,
      );
      setConfirm("");
      setNote(
        tx("Удаление запланировано: данные исчезнут через {days} дн.", {
          days: state.days_left ?? 0,
        }),
      );
      void qc.invalidateQueries({ queryKey: ["privacy", "audit"] });
    },
  });

  const restore = useMutation({
    mutationFn: () => cancelOrgDeletion(),
    onSuccess: (state) => {
      qc.setQueryData<PrivacyState>(["privacy"], (old) =>
        old ? { ...old, deletion: state } : old,
      );
      setNote(tx("Удаление отменено."));
      void qc.invalidateQueries({ queryKey: ["privacy", "audit"] });
    },
  });

  const rotate = useMutation({
    mutationFn: () => rotateOrgLinks(),
    onSuccess: (result) => {
      setConfirmRotate(false);
      setNote(
        tx("Ссылки отозваны. Старые работают до {until}.", {
          until: formatDateTime(result.previous_valid_until),
        }),
      );
      void qc.invalidateQueries({ queryKey: ["privacy", "audit"] });
    },
  });

  const data = q.data;
  const error =
    q.error ??
    download.error ??
    remove.error ??
    restore.error ??
    rotate.error;
  const busy =
    download.isPending ||
    remove.isPending ||
    restore.isPending ||
    rotate.isPending;
  const deleting = data?.deletion.deleted === true;
  const codeMatches =
    !!data && confirm.trim().toLowerCase() === data.slug.toLowerCase();

  return (
    <SubScreen
      title={tx("Данные и приватность")}
      subtitle={tx("Что хранит сервер, сколько и кто это видел")}
      onBack={onBack}
    >
      {q.isLoading && <Skeleton className="h-32" />}

      {q.isError && (
        <p className="rounded-tile bg-tg-secondary-bg p-3 text-sm text-tg-hint">
          {tx("Не удалось загрузить состояние — обнови экран.")}
        </p>
      )}

      {data && (
        <>
          <section className="rounded-tile bg-tg-secondary-bg/60 p-3">
            <div className="text-2xs uppercase tracking-wide text-tg-hint">
              {tx("Сроки хранения")}
            </div>
            <dl className="mt-2 space-y-1 text-sm">
              {[
                ["Журнал доступа", data.retention.audit_days],
                ["Корзина уволенных", data.retention.fired_trash_days],
                ["Отсрочка удаления", data.retention.deletion_grace_days],
                ["Копии бэкапов", data.retention.backup_artifact_days],
              ].map(([label, days]) => (
                <div key={String(label)} className="flex items-baseline justify-between gap-3">
                  <dt className="text-tg-text">{tx(String(label))}</dt>
                  <dd className="shrink-0 text-tg-hint">
                    {tx("{days} дней", { days: String(days) })}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="rounded-tile bg-tg-secondary-bg/60 p-3">
            <div className="text-sm font-semibold text-tg-text">
              {tx("Копия данных")}
            </div>
            <p className="mt-1 text-xs text-tg-hint">
              {tx(
                "Структура, люди, доступы и счета — файл JSON. Выгрузка попадает в журнал.",
              )}
            </p>
            <button
              type="button"
              disabled={busy}
              aria-busy={busy}
              onClick={() => download.mutate(data.slug)}
              className="mt-2 min-h-11 w-full rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
            >
              <BusyLabel busy={download.isPending}>
                {download.isPending
                  ? tx("Скачиваем…")
                  : tx("Скачать копию данных")}
              </BusyLabel>
            </button>
          </section>

          {canRotate && (
            <section className="rounded-tile bg-tg-secondary-bg/60 p-3">
              <div className="text-sm font-semibold text-tg-text">
                {tx("Ссылки на фото и календарь")}
              </div>
            <p className="mt-1 text-xs text-tg-hint">
              {tx(
                "Если ссылка утекла или сотрудник уволен, отзовите ключ организации. Чужие календари и фото не затронуты.",
              )}
            </p>
            {confirmRotate ? (
              <div className="mt-2 space-y-2">
                <p className="text-xs text-tg-text">
                  {tx(
                    "Отозвать все ссылки этой организации? Старые продолжат работать 30 дней — чтобы открытые вкладки и календари не отвалились сразу.",
                  )}
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    aria-busy={rotate.isPending}
                    onClick={() => rotate.mutate()}
                    className="min-h-11 flex-1 rounded-tile bg-red-500/10 text-sm font-semibold text-red-600 disabled:opacity-50"
                  >
                    <BusyLabel busy={rotate.isPending}>
                      {rotate.isPending ? tx("Отзываем…") : tx("Да, отозвать")}
                    </BusyLabel>
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setConfirmRotate(false)}
                    className="min-h-11 flex-1 rounded-tile bg-tg-bg/60 text-sm text-tg-text disabled:opacity-50"
                  >
                    {tx("Отмена")}
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirmRotate(true)}
                className="mt-2 min-h-11 w-full rounded-tile bg-red-500/10 text-sm font-semibold text-red-600 disabled:opacity-50"
              >
                {tx("Отозвать ссылки")}
              </button>
            )}
            </section>
          )}

          <section
            className={[
              "rounded-tile p-3",
              deleting ? "bg-amber-500/10" : "bg-tg-secondary-bg/60",
            ].join(" ")}
          >
            <div className="text-sm font-semibold text-tg-text">
              {tx("Удаление организации")}
            </div>
            {deleting ? (
              <>
                <p className="mt-1 text-xs text-tg-text">
                  {tx("Удаление запланировано: данные исчезнут через {days} дн.", {
                    days: String(data.deletion.days_left ?? 0),
                  })}
                </p>
                <p className="mt-1 text-xs text-tg-hint">
                  {tx("Пока срок не вышел, доступ у команды закрыт, а отменить можно здесь.")}
                </p>
                <button
                  type="button"
                  disabled={busy}
                  aria-busy={busy}
                  onClick={() => restore.mutate()}
                  className="mt-2 min-h-11 w-full rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
                >
                  <BusyLabel busy={busy}>{tx("Отменить удаление")}</BusyLabel>
                </button>
              </>
            ) : (
              <>
                <p className="mt-1 text-xs text-tg-hint">
                  {tx(
                    "Данные удаляются через {days} дн. после запроса — всё это время удаление можно отменить.",
                    { days: String(data.retention.deletion_grace_days) },
                  )}
                </p>
                <FormField
                  id="privacy-confirm-slug"
                  label={tx("Код организации")}
                  hint={tx("Введите код {slug}, чтобы подтвердить — это необратимо.", {
                    slug: data.slug,
                  })}
                  labelClassName="mt-2 block text-xs font-semibold text-tg-hint"
                >
                  {(field) => (
                    <input
                      {...field}
                      value={confirm}
                      onChange={(event) => setConfirm(event.target.value)}
                      placeholder={data.slug}
                      autoCapitalize="none"
                      autoCorrect="off"
                      spellCheck={false}
                      className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg px-3 text-sm font-normal text-tg-text"
                    />
                  )}
                </FormField>
                <p className="mt-1 text-2xs text-tg-hint">
                  {tx("Введите код {slug}, чтобы подтвердить — это необратимо.", {
                    slug: data.slug,
                  })}
                </p>
                <button
                  type="button"
                  disabled={busy || !codeMatches}
                  aria-busy={busy}
                  onClick={() => remove.mutate()}
                  className="mt-2 min-h-11 w-full rounded-tile bg-red-500/10 text-sm font-semibold text-red-600 disabled:opacity-50"
                >
                  <BusyLabel busy={busy}>{tx("Запросить удаление")}</BusyLabel>
                </button>
              </>
            )}
          </section>

          <section>
            <div className="mb-2 px-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
              {tx("Последние события доступа")}
            </div>
            {audit.data && audit.data.length > 0 ? (
              <ul className="overflow-hidden rounded-card border border-tg-secondary-bg">
                {audit.data.map((event, index) => (
                  <li
                    key={event.id}
                    className={[
                      "px-3 py-2 text-sm",
                      index > 0 ? "border-t border-tg-secondary-bg" : "",
                    ].join(" ")}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="min-w-0 truncate font-medium text-tg-text">
                        {tx(ACTION_TEXT[event.action] ?? event.action)}
                      </span>
                      <span className="shrink-0 text-2xs text-tg-hint">
                        {formatDateTime(event.created_at)}
                      </span>
                    </div>
                    <div className="truncate text-xs text-tg-hint">
                      {event.actor_name ?? "—"}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
                {tx("Пока никто не выгружал данные и не менял доступы.")}
              </p>
            )}
          </section>
        </>
      )}

      {note && (
        <p className="rounded-tile bg-tg-link/10 p-3 text-xs text-tg-link" role="status">
          {note}
        </p>
      )}

      {error && (
        <p className="rounded-tile bg-red-500/10 p-3 text-xs text-red-600" role="alert">
          {humanizeApiError(error)}
        </p>
      )}
    </SubScreen>
  );
}
