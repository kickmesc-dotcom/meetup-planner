import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import {
  ROLE_LABEL,
  fetchEmployeesPool,
  fireEmployee,
  patchEmployee,
  resetEmployeeProgress,
  restoreEmployee,
  type HrEmployeeCard,
  type HrRole,
} from "@/api/hrOps";
import { ListSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import ChevronToggle from "@/components/ChevronToggle";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { AddPersonPanel, RosterSnapshotsPanel } from "./RosterTools";
import SubScreen from "./SubScreen";

import { useTx } from "@/i18n";
/**
 * Пул сотрудников: правка в одном месте.
 *
 * Зачем именно здесь, а не в профиле человека: переименовать, поставить
 * должность, обнулить знакомство или уволить — это действия управляющего, а не
 * самообслуживание. Увольнение уносит доступ сразу, а данные — по выбору:
 * корзина на 30 дней (восстановимо) или удаление безвозвратно.
 *
 * Сверху два инструмента пула: добавить человека по Telegram-ID (не дожидаясь
 * его первого входа) и снапшоты состава — чтобы удаление не унесло с собой
 * список заведённых ID.
 */
export default function EmployeesScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "employees-pool"],
    queryFn: fetchEmployeesPool,
    staleTime: 30_000,
  });

  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "employees-pool"] });
    void qc.invalidateQueries({ queryKey: ["hr-dashboard"] });
  };

  const onError = (error: unknown) => void showAlert(humanizeApiError(error));

  const save = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: number;
      body: {
        display_name?: string;
        position?: string;
        badge?: string;
        role?: HrRole;
      };
    }) => patchEmployee(id, body),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError,
  });

  const reset = useMutation({
    mutationFn: (id: number) => resetEmployeeProgress(id),
    onSuccess: () => {
      haptic("success");
      refresh();
      void showAlert(tx("Прогресс знакомства обнулён."));
    },
    onError,
  });

  const fire = useMutation({
    mutationFn: ({ id, mode }: { id: number; mode: "trash" | "purge" }) =>
      fireEmployee(id, mode),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError,
  });

  const restore = useMutation({
    mutationFn: (id: number) => restoreEmployee(id),
    onSuccess: () => {
      haptic("success");
      refresh();
      void showAlert(tx("Сотрудник возвращён: доступ открыт."));
    },
    onError,
  });

  const items = q.data?.items ?? [];
  const needle = search.trim().toLowerCase();
  const visible = items.filter(
    (card) =>
      needle === "" ||
      card.display_name.toLowerCase().includes(needle) ||
      (card.position ?? "").toLowerCase().includes(needle) ||
      (card.badge ?? "").toLowerCase().includes(needle) ||
      (card.department_name ?? "").toLowerCase().includes(needle),
  );
  const trashDays = q.data?.trash_days ?? 30;

  const askFire = async (card: HrEmployeeCard) => {
    haptic("medium");
    const first = await showConfirm(
      tx("Уволить {name}? Доступ в приложение и к боту закроется сразу.", {
        name: card.display_name,
      }),
    );
    if (!first) return;
    const toTrash = await showConfirm(
      tx(
        "Что делать с данными? OK — в корзину на {days} дней, отмена — удалить сразу и бесповоротно.",
        { days: trashDays },
      ),
    );
    if (toTrash) {
      const again = await showConfirm(
        tx(
          "Ещё раз: данные уедут в корзину и удалятся сами через {days} дней. Продолжаем?",
          { days: trashDays },
        ),
      );
      if (again) fire.mutate({ id: card.employee_id, mode: "trash" });
      return;
    }
    const purge = await showConfirm(
      tx("Ещё раз: данные сотрудника будут удалены сразу и бесповоротно. Уверен?"),
    );
    if (purge) fire.mutate({ id: card.employee_id, mode: "purge" });
  };

  const askReset = async (card: HrEmployeeCard) => {
    haptic("medium");
    const ok = await showConfirm(
      tx(
        "Обнулить знакомство с приложением у {name}? Уроки и онбординг сбросятся, отдел и опыт останутся.",
        { name: card.display_name },
      ),
    );
    if (ok) reset.mutate(card.employee_id);
  };

  const busy =
    save.isPending || reset.isPending || fire.isPending || restore.isPending;

  return (
    <SubScreen
      title={tx("Пул сотрудников")}
      subtitle={tx("Переименовать, должность, прогресс, увольнение")}
      onBack={onBack}
    >
      <input
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={tx("Найти по имени, должности или отделу")}
        aria-label={tx("Поиск по сотрудникам")}
        className="min-h-10 w-full rounded-tile bg-tg-secondary-bg/60 px-3 text-sm text-tg-text placeholder:text-tg-hint"
      />

      <AddPersonPanel
        onAdded={refresh}
        onFound={(id) => {
          setOpenId(id);
          setSearch("");
        }}
      />
      <RosterSnapshotsPanel />

      {q.isLoading && <ListSkeleton rows={6} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}

      {q.data && visible.length === 0 && (
        <p className="py-8 text-center text-xs text-tg-hint">{tx("Никого не нашли.")}</p>
      )}

      {visible.map((card) => (
        <EmployeeRow
          key={card.employee_id}
          card={card}
          open={openId === card.employee_id}
          busy={busy}
          trashDays={trashDays}
          onToggle={() => {
            haptic("selection");
            setOpenId((current) =>
              current === card.employee_id ? null : card.employee_id,
            );
          }}
          onSave={(body) => save.mutate({ id: card.employee_id, body })}
          onReset={() => void askReset(card)}
          onFire={() => void askFire(card)}
          onRestore={() => restore.mutate(card.employee_id)}
        />
      ))}
    </SubScreen>
  );
}

function EmployeeRow({
  card,
  open,
  busy,
  trashDays,
  onToggle,
  onSave,
  onReset,
  onFire,
  onRestore,
}: {
  card: HrEmployeeCard;
  open: boolean;
  busy: boolean;
  trashDays: number;
  onToggle: () => void;
  onSave: (body: {
    display_name?: string;
    position?: string;
    badge?: string;
    role?: HrRole;
  }) => void;
  onReset: () => void;
  onFire: () => void;
  onRestore: () => void;
}) {
  const { tx } = useTx();
  const [name, setName] = useState(card.display_name);
  const [position, setPosition] = useState(card.position ?? "");
  const [badge, setBadge] = useState(card.badge ?? "");
  const [role, setRole] = useState<HrRole>(card.role as HrRole);

  const fired = card.fired_at !== null;
  return (
    <section className="rounded-card bg-tg-secondary-bg/60">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        <Icon
          name={fired ? "door" : card.is_demo ? "bot" : "profile"}
          size={18}
          className="mt-0.5 shrink-0 text-tg-hint"
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-tg-text">
            {card.display_name}
          </span>
          <span className="block truncate text-xs text-tg-hint">
            {[card.department_name, card.position ?? card.badge]
              .filter(Boolean)
              .join(" · ") || tx("без отдела")}
            {` · ${ROLE_LABEL[card.role as HrRole] ?? card.role}`}
            {fired ? tx(" · уволен") : ""}
          </span>
          <span className="block truncate text-2xs text-tg-hint">
            {card.telegram_id === null
              ? tx("вход по почте")
              : `Telegram ID ${card.telegram_id}`}
          </span>
        </span>
        <span className="shrink-0 text-tg-hint" aria-hidden>
          <ChevronToggle open={open} />
        </span>
      </button>

      {open && (
        <div className="space-y-2 px-3 pb-3">
          {fired && (
            <p className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
              {tx("Доступ закрыт.")}{" "}
              {card.purge_after
                ? tx("Данные в корзине до {date}.", {
                    date: formatDate(card.purge_after),
                  })
                : tx("Данные удалены.")}
            </p>
          )}

          <label className="block text-xs text-tg-hint">{tx("Имя")}<input
              type="text"
              value={name}
              maxLength={64}
              onChange={(event) => setName(event.target.value)}
              className="mt-1 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            />
          </label>
          <label className="block text-xs text-tg-hint">{tx("Должность (влияет на пункты чек-листа)")}<input
              type="text"
              value={position}
              maxLength={64}
              placeholder={tx("например, су-шеф")}
              onChange={(event) => setPosition(event.target.value)}
              className="mt-1 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            />
          </label>
          <label className="block text-xs text-tg-hint">{tx("Плашка под именем")}<input
              type="text"
              value={badge}
              maxLength={64}
              placeholder={tx("например, Управляющий")}
              onChange={(event) => setBadge(event.target.value)}
              className="mt-1 min-h-9 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            />
          </label>

          {/* Роль: сотрудник / руководитель / администратор. Раньше её можно
              было сменить только через «примерить роль» себе — выдать права
              другому из админки было нечем. */}
          <div>
            <div className="text-xs text-tg-hint">{tx("Роль в боте")}</div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {(Object.keys(ROLE_LABEL) as HrRole[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={role === value}
                  disabled={busy}
                  onClick={() => {
                    haptic("selection");
                    setRole(value);
                  }}
                  className={[
                    "min-h-9 rounded-full px-3 text-xs transition-colors disabled:opacity-50",
                    role === value
                      ? "bg-tg-button text-tg-button-text"
                      : "bg-tg-bg/60 text-tg-text",
                  ].join(" ")}
                >
                  {ROLE_LABEL[value]}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                onSave({
                  display_name: name,
                  position,
                  badge,
                  role,
                })
              }
              className="min-h-9 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
            >{tx("Сохранить")}</button>
            <button
              type="button"
              disabled={busy}
              onClick={onReset}
              className="min-h-9 rounded-tile bg-tg-bg/60 px-3 text-xs text-tg-text disabled:opacity-50"
            >{tx("Обнулить прогресс")}</button>
            {fired ? (
              card.purge_after && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={onRestore}
                  className="min-h-9 rounded-tile bg-status-free/15 px-3 text-xs text-status-free disabled:opacity-50"
                >{tx("Вернуть из корзины")}</button>
              )
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={onFire}
                className="min-h-9 rounded-tile bg-status-busy/15 px-3 text-xs text-status-busy disabled:opacity-50"
              >{tx("Уволить")}</button>
            )}
          </div>
          <p className="text-2xs text-tg-hint">
            {tx(
              "Увольнение даёт выбор: корзина на {days} дней или удаление сразу.",
              { days: trashDays },
            )}
          </p>
        </div>
      )}
    </section>
  );
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}
