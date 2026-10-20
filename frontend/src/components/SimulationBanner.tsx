import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, humanizeApiError } from "@/api/client";
import { exitSimulation } from "@/api/simulation";
import { useSimulation } from "@/store/simulation";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * Постоянная плашка режима проверки.
 *
 * Требование ТЗ: пока имитация активна, человек не должен забыть, от чьего
 * имени смотрит приложение. Плашка висит над контентом на всех экранах и
 * содержит единственное действие «Выйти», которое очищает тестовые данные на
 * сервере. Если очистка упала, сеанс НЕ закрывается — иначе тестовый мусор
 * остался бы в настоящей истории.
 */
export default function SimulationBanner() {
  const qc = useQueryClient();
  const setTab = useUI((s) => s.setTab);
  const simulation = useSimulation();

  const exit = useMutation({
    mutationFn: () => exitSimulation(simulation.sessionId ?? 0),
    onSuccess: (result) => {
      haptic("success");
      simulation.clear();
      setTab("tasks");
      void qc.invalidateQueries();
      void showAlert(
        result.already_ended
          ? "Сеанс уже был закрыт."
          : `Вышли из режима проверки. Удалено: задач ${result.tasks}, смен ${result.runs}, проблем ${result.issues}.`,
      );
    },
    onError: (error) => {
      // Сеанс не закрываем: сервер мог не довести очистку до конца.
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.detail === "simulation_inactive"
      ) {
        simulation.clear();
        void qc.invalidateQueries();
        return;
      }
      haptic("error");
      void showAlert(humanizeApiError(error));
    },
  });

  if (!simulation.sessionId) return null;

  const place = simulation.departmentName ? ` · ${simulation.departmentName}` : "";
  return (
    <div
      className="flex items-center gap-2 border-b border-status-busy/30 bg-status-busy/15 px-3 py-1.5 text-xs text-tg-text"
      role="status"
    >
      <span aria-hidden>🧪</span>
      <span className="min-w-0 flex-1 truncate">
        Режим проверки · {simulation.subjectName}
        {place}
      </span>
      <button
        type="button"
        disabled={exit.isPending}
        onClick={() => exit.mutate()}
        className="min-h-7 shrink-0 rounded-full bg-tg-bg px-2.5 text-xs font-medium text-tg-link disabled:opacity-50"
      >
        {exit.isPending ? "Чистим…" : "Выйти"}
      </button>
    </div>
  );
}
