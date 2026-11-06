import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createBranch, fetchBranches } from "@/api/orgs";
import { humanizeApiError, setActiveOrg } from "@/api/client";
import { Skeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";
import { haptic, showAlert } from "@/tg/webapp";
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
 */
const ERROR_TEXT: Record<string, string> = {
  branch_limit: "Больше 20 филиалов не поддерживается.",
  branch_of_branch: "У филиала не может быть своих филиалов.",
  branch_owner_required: "Филиалы настраивает владелец сети.",
  bad_name: "Название слишком короткое.",
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
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: (value: string) => createBranch(value),
    onSuccess: () => {
      haptic("success");
      setName("");
      void qc.invalidateQueries({ queryKey: ["org-branches"] });
    },
    onError: (error) => {
      const code = humanizeApiError(error);
      void showAlert(tx(ERROR_TEXT[code] ?? code));
    },
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
      <p className="text-xs text-tg-hint">
        {tx(
          "У филиала свои люди, график и отчёты — данные не смешиваются. Владелец заходит в любой филиал без второй учётки.",
        )}
      </p>

      {q.isLoading && <Skeleton className="mt-3 h-20" />}

      <div className="mt-3 space-y-2">
        {(q.data ?? []).map((branch) => (
          <div
            key={branch.id}
            className="flex items-center justify-between gap-2 rounded-card bg-tg-secondary-bg/40 p-3"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-tg-text">
                {branch.name}
              </div>
              <div className="text-2xs text-tg-hint">
                {branch.is_root ? tx("Головная организация") : tx("Филиал")}
                {branch.is_current ? ` · ${tx("Текущая")}` : ""}
              </div>
            </div>
            {branch.is_current ? (
              <span className="shrink-0 rounded-full bg-green-500/15 px-2 py-0.5 text-2xs text-green-600">
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

      <section className="mt-4 rounded-card bg-tg-secondary-bg/40 p-3">
        <div className="text-sm font-semibold text-tg-text">
          {tx("Новый филиал")}
        </div>
        <p className="mt-1 text-xs text-tg-hint">
          {tx(
            "Филиал получит свой код и отдельные данные. Сотрудников добавляйте уже внутри него.",
          )}
        </p>
        <div className="mt-2 flex gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={tx("Название филиала")}
            className="min-h-11 min-w-0 flex-1 rounded-tile bg-tg-bg px-2 text-sm text-tg-text"
          />
          <button
            type="button"
            disabled={create.isPending || name.trim().length < 2}
            onClick={() => create.mutate(name.trim())}
            className="min-h-11 shrink-0 rounded-tile bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {tx("Создать")}
          </button>
        </div>
      </section>
    </SubScreen>
  );
}
