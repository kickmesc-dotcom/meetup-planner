import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import { fetchDepartments } from "@/api/hr";
import {
  addEmployeeByTelegramId,
  createRosterSnapshot,
  deleteRosterSnapshot,
  fetchRosterSnapshots,
  restoreRosterSnapshot,
  type HrRosterSnapshot,
} from "@/api/hrOps";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";

/**
 * Ручное заведение по Telegram-ID.
 *
 * Зачем: человек может ещё не открыть бота, а место в пуле уже нужно — выдать
 * поручение в первый день, поставить в график, добавить в подразделение.
 * Раньше для этого приходилось ждать его захода или лезть в базу.
 *
 * Поле фильтрует ввод до цифр: ID копируют из Telegram, и любой мусор в строке
 * превращался бы в 422 вместо понятной подсказки.
 */
export function AddPersonPanel({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [tgId, setTgId] = useState("");
  const [name, setName] = useState("");
  const [position, setPosition] = useState("");
  const [departmentId, setDepartmentId] = useState("");

  const departments = useQuery({
    queryKey: ["hr", "departments"],
    queryFn: fetchDepartments,
    staleTime: 60_000,
    enabled: open,
  });

  const add = useMutation({
    mutationFn: () =>
      addEmployeeByTelegramId({
        telegram_id: Number(tgId),
        display_name: name.trim() || undefined,
        department_id: departmentId ? Number(departmentId) : undefined,
        position: position.trim() || undefined,
      }),
    onSuccess: (card) => {
      haptic("success");
      setTgId("");
      setName("");
      setPosition("");
      onAdded();
      void showAlert(`${card.display_name} заведён(а) в боте.`);
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  return (
    <section className="rounded-card bg-tg-secondary-bg/60">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen((current) => !current);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        <span aria-hidden>➕</span>
        <span className="min-w-0 flex-1 text-sm font-medium text-tg-text">
          Добавить по Telegram ID
        </span>
        <span className="shrink-0 text-tg-hint" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="space-y-2 px-3 pb-3">
          <label className="block text-xs text-tg-hint">
            Telegram ID
            <input
              type="text"
              inputMode="numeric"
              value={tgId}
              placeholder="например, 123456789"
              onChange={(event) =>
                setTgId(event.target.value.replace(/\D/g, "").slice(0, 15))
              }
              className="mt-1 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            />
          </label>
          <label className="block text-xs text-tg-hint">
            Имя (необязательно)
            <input
              type="text"
              value={name}
              maxLength={64}
              placeholder="как показывать в боте"
              onChange={(event) => setName(event.target.value)}
              className="mt-1 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            />
          </label>
          <label className="block text-xs text-tg-hint">
            Подразделение (необязательно)
            <select
              value={departmentId}
              onChange={(event) => setDepartmentId(event.target.value)}
              className="mt-1 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            >
              <option value="">без подразделения</option>
              {(departments.data ?? []).map((department) => (
                <option key={department.id} value={department.id}>
                  {department.emoji ? `${department.emoji} ` : ""}
                  {department.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-tg-hint">
            Должность (необязательно)
            <input
              type="text"
              value={position}
              maxLength={64}
              placeholder="например, су-шеф"
              onChange={(event) => setPosition(event.target.value)}
              className="mt-1 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            />
          </label>

          <button
            type="button"
            disabled={tgId.length < 4 || add.isPending}
            onClick={() => add.mutate()}
            className="min-h-9 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
          >
            {add.isPending ? "Добавляем…" : "Добавить в бот"}
          </button>
          <p className="text-2xs text-tg-hint">
            Доступ появится сразу: человек сможет открыть мини-апп и писать боту.
            Существующий профиль не перезаписывается.
          </p>
        </div>
      )}
    </section>
  );
}

/**
 * Снапшоты состава — страховка от потери пула ID.
 *
 * Снимок хранит людей по `telegram_id`, а не по внутренним номерам строк, и
 * восстановление не трогает активных сотрудников: снимок — это «вернуть
 * пропавших», а не «откатить всё назад».
 */
export function RosterSnapshotsPanel() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  const q = useQuery({
    queryKey: ["admin", "roster-snapshots"],
    queryFn: fetchRosterSnapshots,
    staleTime: 15_000,
    enabled: open,
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "roster-snapshots"] });
    void qc.invalidateQueries({ queryKey: ["admin", "employees-pool"] });
  };

  const create = useMutation({
    mutationFn: () =>
      createRosterSnapshot(
        `Снимок ${new Date().toLocaleString("ru-RU", {
          day: "2-digit",
          month: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })}`,
      ),
    onSuccess: (data) => {
      haptic("success");
      refresh();
      void showAlert(`Снимок готов: людей в составе — ${data.snapshot.people_count}.`);
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const restore = useMutation({
    mutationFn: (id: number) => restoreRosterSnapshot(id),
    onSuccess: (result) => {
      haptic("success");
      refresh();
      const lines = [
        `Заведено заново: ${result.created}`,
        `Возвращено из корзины: ${result.restored}`,
        `Не тронуто (уже есть): ${result.skipped}`,
      ];
      if (result.departments_missing.length > 0) {
        lines.push(`Нет отделов: ${result.departments_missing.join(", ")}`);
      }
      void showAlert(lines.join("\n"));
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteRosterSnapshot(id),
    onSuccess: refresh,
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const askRestore = async (snapshot: HrRosterSnapshot) => {
    haptic("medium");
    const ok = await showConfirm(
      `Вернуть людей из снимка «${snapshot.label || "без названия"}» от ${formatMoment(
        snapshot.created_at,
      )}?\n\nАктивных сотрудников не трогаем — вернутся только пропавшие.`,
    );
    if (ok) restore.mutate(snapshot.id);
  };

  const askRemove = async (snapshot: HrRosterSnapshot) => {
    haptic("medium");
    const ok = await showConfirm(
      `Удалить снимок от ${formatMoment(snapshot.created_at)}? Восстановить по нему будет нельзя.`,
    );
    if (ok) remove.mutate(snapshot.id);
  };

  const items = q.data?.items ?? [];
  const busy = create.isPending || restore.isPending || remove.isPending;

  return (
    <section className="rounded-card bg-tg-secondary-bg/60">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen((current) => !current);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        <span aria-hidden>📸</span>
        <span className="min-w-0 flex-1 text-sm font-medium text-tg-text">
          Снапшоты состава
        </span>
        <span className="shrink-0 text-tg-hint" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="space-y-2 px-3 pb-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => create.mutate()}
            className="min-h-9 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
          >
            {create.isPending ? "Снимаем…" : "Снять снапшот сейчас"}
          </button>
          <p className="text-2xs text-tg-hint">
            Перед удалением сотрудника или очисткой тестового пула снимок
            снимается сам. Храним последние {q.data?.max_snapshots ?? 20}.
          </p>

          {q.isLoading && <p className="text-xs text-tg-hint">Загружаем…</p>}
          {q.isError && (
            <p className="text-xs text-status-busy">
              {humanizeApiError(q.error)}
            </p>
          )}
          {q.data && items.length === 0 && (
            <p className="text-xs text-tg-hint">Снимков пока нет.</p>
          )}

          {items.map((snapshot) => (
            <div
              key={snapshot.id}
              className="rounded-tile bg-tg-bg/60 px-2 py-2"
            >
              <div className="flex items-baseline gap-2">
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-tg-text">
                  {snapshot.label || "Без названия"}
                </span>
                <span className="shrink-0 text-2xs text-tg-hint">
                  {snapshot.people_count} чел.
                </span>
              </div>
              <div className="text-2xs text-tg-hint">
                {formatMoment(snapshot.created_at)}
                {snapshot.kind === "auto" ? " · авто" : ""}
                {snapshot.source ? ` · ${snapshot.source}` : ""}
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void askRestore(snapshot)}
                  className="min-h-8 rounded-tile bg-tg-secondary-bg px-2 text-2xs text-tg-text disabled:opacity-50"
                >
                  Восстановить
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void askRemove(snapshot)}
                  className="min-h-8 rounded-tile bg-status-busy/15 px-2 text-2xs text-status-busy disabled:opacity-50"
                >
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function formatMoment(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
