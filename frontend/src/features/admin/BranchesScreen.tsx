import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createBranch,
  fetchBranchEmployees,
  fetchBranches,
  transferEmployee,
} from "@/api/orgs";
import { humanizeApiError, setActiveOrg } from "@/api/client";
import FormField from "@/components/FormField";
import Hint from "@/components/Hint";
import { Skeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";
import { haptic, showAlert } from "@/tg/webapp";
import { showToast } from "@/components/toast";
import { useTx } from "@/i18n";

/**
 * «Филиалы сети» (06.11.2026).
 *
 * Зачем экран. У сети один владелец и несколько коллективов. Владелец должен
 * видеть все филиалы и заходить в любой, не заводя вторую учётку: вход у него
 * один, а организация запроса — та, которую он выбрал.
 *
 * Почему переключение перезагружает приложение. Организация вшита в каждый
 * запрос и в каждый кэш экрана. Точечно сбрасывать полтора десятка ключей —
 * значит однажды забыть один и показать владельцу людей прежнего филиала.
 * Пустой кэш после перезагрузки честнее.
 *
 * Перенос сотрудника (06.11.2026). Переводится человек из текущего филиала в
 * другой филиал сети. Прошлые смены остаются в отчётах прежнего филиала —
 * выручка и дисциплина считаются там, где он работал; будущие смены едут с ним,
 * иначе он вышел бы на смену, которой нет в графике нового филиала.
 */
const ERROR_TEXT: Record<string, string> = {
  branch_limit: "Больше 20 филиалов не поддерживается.",
  branch_of_branch: "У филиала не может быть своих филиалов.",
  branch_owner_required: "Филиалы настраивает владелец сети.",
  bad_name: "Название слишком короткое.",
  employee_not_found: "Сотрудник не найден в этом филиале.",
  transfer_self: "Нельзя перевести самого себя.",
  transfer_demo: "Демо-сотрудников переводить нельзя.",
  already_in_branch: "У этого человека уже есть профиль в филиале.",
  same_org: "Он уже в этом филиале.",
  org_not_in_network: "Этот филиал не входит в вашу сеть.",
};

export default function BranchesScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["org-branches"],
    queryFn: fetchBranches,
    retry: false,
    staleTime: 30_000,
  });
  const people = useQuery({
    queryKey: ["branch-employees"],
    queryFn: fetchBranchEmployees,
    retry: false,
    staleTime: 30_000,
  });
  const [name, setName] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [moveShifts, setMoveShifts] = useState(true);

  const branches = q.data ?? [];
  const current = branches.find((row) => row.is_current);
  const targets = branches.filter((row) => !row.is_current);

  useEffect(() => {
    if (!targetId && targets.length > 0) setTargetId(String(targets[0].id));
  }, [targetId, targets]);

  // Ошибка создания — у поля, а не только тостом: человек остаётся в форме
  // и видит, что именно поправить (имя занято, нет прав).
  const [createError, setCreateError] = useState<string | null>(null);
  const [nameTouched, setNameTouched] = useState(false);
  const nameError =
    nameTouched && name.trim().length < 2
      ? tx("Название — хотя бы 2 символа, иначе филиалы не отличить.")
      : null;

  const fail = (error: unknown) => {
    const code = humanizeApiError(error);
    void showAlert(
      tx(
        ERROR_TEXT[code] ?? code,
      ),
    );
  };

  const create = useMutation({
    mutationFn: (value: string) => createBranch(value),
    onSuccess: () => {
      haptic("success");
      setName("");
      setCreateError(null);
      void qc.invalidateQueries({ queryKey: ["org-branches"] });
    },
    onError: (error) => {
      haptic("error");
      const code = humanizeApiError(error);
      setCreateError(ERROR_TEXT[code] ?? code);
    },
  });

  const transfer = useMutation({
    mutationFn: () =>
      transferEmployee({
        employee_id: Number(employeeId),
        target_org_id: Number(targetId),
        move_shifts: moveShifts,
      }),
    onSuccess: (result) => {
      haptic("success");
      setEmployeeId("");
      void qc.invalidateQueries({ queryKey: ["branch-employees"] });
      showToast(
        tx("Сотрудник переведён: перенесено смен — {count}.", {
          count: result.shifts_moved,
        }),
      );
    },
    onError: fail,
  });

  const pick = (id: number) => {
    haptic("selection");
    setActiveOrg(id);
    window.location.reload();
  };

  return (
    <SubScreen
      title={tx("Филиалы сети")}
      subtitle={tx("Несколько салонов под одним владельцем")}
      onBack={onBack}
    >
      <Hint size="xs" className="mt-0">
        {tx(
          "У филиала свои люди, график и отчёты — данные не смешиваются. Владелец заходит в любой филиал без второй учётки.",
        )}
      </Hint>

      {q.isLoading && <Skeleton className="mt-3 h-20" />}

      <div className="mt-3 space-y-2">
        {branches.map((branch) => (
          <div
            key={branch.id}
            className="flex items-center justify-between gap-2 rounded-card bg-tg-secondary-bg/40 p-3"
          >
            <div className="min-w-0">
              <div
                className="truncate text-sm font-semibold text-tg-text"
                title={branch.name}
              >
                {branch.name}
              </div>
              <div className="text-2xs text-tg-hint">
                {branch.is_root ? tx("Головная организация") : tx("Филиал")}
                {branch.is_current ? ` · ${tx("Текущая")}` : ""}
              </div>
            </div>
            {branch.is_current ? (
              <span className="shrink-0 rounded-full bg-green-500/15 px-2 py-1 text-2xs text-green-600">
                {tx("Вы здесь")}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => pick(branch.id)}
                className="min-h-9 shrink-0 rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text"
              >
                {tx("Переключиться")}
              </button>
            )}
          </div>
        ))}
      </div>

      {current && targets.length > 0 && (
        <section className="mt-4 rounded-card bg-tg-secondary-bg/40 p-3">
          <div className="text-sm font-semibold text-tg-text">
            {tx("Перевести сотрудника")}
          </div>
          <Hint size="xs">
            {tx(
              "Прошлые смены остаются в отчётах прежнего филиала, будущие переезжают вместе с человеком.",
            )}
          </Hint>

          <FormField
            id="transfer-person"
            label={tx("Кто переезжает")}
            className="mt-2"
            labelClassName="block text-xs text-tg-hint"
          >
            {(field) => (
              <select
                {...field}
                value={employeeId}
                onChange={(event) => setEmployeeId(event.target.value)}
                className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg px-2 text-sm text-tg-text"
              >
                <option value="">{tx("Выберите сотрудника")}</option>
                {(people.data ?? []).map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.position ? `${person.name} · ${person.position}` : person.name}
                  </option>
                ))}
              </select>
            )}
          </FormField>

          <FormField
            id="transfer-branch"
            label={tx("В какой филиал")}
            className="mt-2"
            labelClassName="block text-xs text-tg-hint"
          >
            {(field) => (
              <select
                {...field}
                value={targetId}
                onChange={(event) => setTargetId(event.target.value)}
                className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg px-2 text-sm text-tg-text"
              >
                {targets.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name}
                  </option>
                ))}
              </select>
            )}
          </FormField>

          <label className="mt-2 flex items-center gap-2 text-xs text-tg-text">
            <input
              type="checkbox"
              checked={moveShifts}
              onChange={(event) => setMoveShifts(event.target.checked)}
            />
            {tx("Перенести будущие смены")}
          </label>

          <button
            type="button"
            disabled={transfer.isPending || !employeeId || !targetId}
            aria-busy={transfer.isPending}
            onClick={() => transfer.mutate()}
            className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-tile bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {transfer.isPending && <Spinner size={14} />}
            {tx("Перевести")}
          </button>
        </section>
      )}

      <section className="mt-4 rounded-card bg-tg-secondary-bg/40 p-3">
        <div className="text-sm font-semibold text-tg-text">
          {tx("Новый филиал")}
        </div>
        <Hint size="xs">
          {tx(
            "Филиал получит свой код и отдельные данные. Сотрудников добавляйте уже внутри него.",
          )}
        </Hint>
        <FormField
          id="branch-name"
          label={tx("Название филиала")}
          hint={tx("Сотрудники увидят это название в переключателе филиалов.")}
          error={createError ?? nameError ?? undefined}
          required
          className="mt-2"
        >
          {(field) => (
            <div className="mt-1 flex gap-2">
              <input
                {...field}
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setCreateError(null);
                }}
                onBlur={() => setNameTouched(true)}
                placeholder={tx("Название филиала")}
                className="min-h-11 min-w-0 flex-1 rounded-tile bg-tg-bg px-2 text-sm text-tg-text"
              />
              <button
                type="button"
                disabled={create.isPending || name.trim().length < 2}
                aria-busy={create.isPending}
                onClick={() => create.mutate(name.trim())}
                className="inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 rounded-tile bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {create.isPending && <Spinner size={14} />}
                {tx("Создать")}
              </button>
            </div>
          )}
        </FormField>
      </section>
    </SubScreen>
  );
}
