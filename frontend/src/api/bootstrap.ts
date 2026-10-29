import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import type { User } from "@/types";

import type { UiPrefs } from "./availability";
import { api } from "./client";
import type { HrEmployee, HrTask, OrgSetup } from "./hr";

/**
 * Быстрый старт: один запрос вместо шести.
 *
 * Почему именно так. Открытие приложения отправляло `/me`, `/users`,
 * `/me/employee`, `/tasks`, `/org-setup`, `/me/ui-prefs` — и каждый с
 * `Authorization`, то есть с отдельным preflight. На ПК это шесть «двойных»
 * кругов до сервера на один экран загрузки (замеры — `docs/DESKTOP_PERF.md`).
 *
 * Как это устроено. Сервер отдаёт те же шесть тел, собранные теми же
 * функциями, что и отдельные ручки. Фронт не заводит второго способа читать
 * данные: он кладёт ответ в кеш react-query ПОД ТЕМИ ЖЕ КЛЮЧАМИ, что у
 * обычных запросов. Экраны по-прежнему зовут `["me"]`, `["hr-tasks", false]`
 * и просто получают готовое — про существование bootstrap они не знают.
 *
 * Что если не сработало. Ручка зависит от `EmployeeDep` (как `/me/employee`),
 * поэтому человек без членства в организации получит 403 — и тогда App
 * включает шесть обычных запросов (`bootFailed`). Никакой второй логики прав:
 * деградация ровно до сегодняшнего поведения плюс один лишний запрос.
 */
export interface Bootstrap {
  me: User;
  users: User[];
  employee: HrEmployee | null;
  tasks: HrTask[] | null;
  org_setup: OrgSetup | null;
  ui_prefs: UiPrefs | null;
}

export const fetchBootstrap = () => api<Bootstrap>("/api/bootstrap");

/**
 * Разложить ответ старта по ключам обычных запросов.
 *
 * `updatedAt` ставим текущим временем: иначе «свежесть» записи считалась бы от
 * момента создания ключа, и запрос с `staleTime` тут же пошёл бы в сеть
 * повторно — то есть выигрыш съелся бы одним лишним кругом.
 */
export function seedBootstrap(qc: QueryClient, data: Bootstrap): void {
  const fresh = { updatedAt: Date.now() };
  qc.setQueryData(["me"], data.me, fresh);
  qc.setQueryData(["users"], data.users, fresh);
  // Пустые куски не подкладываем: отсутствие данных — это «ещё не загружено»,
  // а не «на сервере пусто». Иначе экран показал бы «нет поручений» вместо
  // скелетона и пошёл бы за настоящими данными только по кнопке.
  if (data.employee) qc.setQueryData(["hr-employee"], data.employee, fresh);
  if (data.tasks) qc.setQueryData(["hr-tasks", false], data.tasks, fresh);
  if (data.org_setup) qc.setQueryData(["org-setup"], data.org_setup, fresh);
  if (data.ui_prefs) qc.setQueryData(["ui-prefs"], data.ui_prefs, fresh);
}

/**
 * Запросить старт и разложить ответ по кешу.
 *
 * `retry: false` — не упрямство: это оптимизация, а не единственный путь.
 * Падение должно как можно скорее отдать управление обычным шести запросам, а
 * не растягивать скелетон на три попытки с задержкой.
 */
export function useBootstrap() {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["bootstrap"],
    queryFn: async () => {
      const data = await fetchBootstrap();
      seedBootstrap(qc, data);
      return data;
    },
    staleTime: 60_000,
    retry: false,
  });
}
