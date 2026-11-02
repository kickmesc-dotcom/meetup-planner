import { lazy, Suspense } from "react";
import { Skeleton } from "@/components/Skeleton";
import SimulationBanner from "@/components/SimulationBanner";
import ManageTabBar from "@/features/admin/ManageTabBar";
import ModeSwitch from "@/features/nav/ModeSwitch";
import { SAFE_AREA_ROOT } from "@/tg/safeArea";
import type { User } from "@/types";
import { useTx } from "@/i18n";

// Кабинет грузится отдельным чанком: сотрудник его не открывает никогда, и
// незачем тянуть чужие полторы тысячи строк в первую загрузку его экрана.
const AdminScreen = lazy(() => import("./AdminScreen"));

/**
 * Зона управления — второй экран приложения, а не вкладка внутри первого.
 *
 * Зачем отдельный каркас. Полоса сотрудника отвечает на вопрос «что мне делать
 * сейчас»: смена, чек-лист, задачи, табель, профиль. Кабинет отвечает на совсем
 * другой: что происходит с людьми и предприятием. Пока обе вещи жили в одной
 * полосе, у руководителя она отличалась от сотрудниковой, и граница зон не
 * читалась — ровно та жалоба, с которой начался этот пак.
 *
 * Здесь нет нижней полосы сотрудника вообще: в этой зоне её разделы не нужны,
 * а вернуться к своей смене — одна вкладка вверху.
 */
export default function ManageZone({
  users,
  platform = false,
  canManage = false,
}: {
  users: User[];
  /** Прописанный админ платформы: видит системные разделы (прокси, тексты…). */
  platform?: boolean;
  /** Руководитель: видит команду, приёмку и отчёт смены. */
  canManage?: boolean;
}) {
  const { tx } = useTx();
  return (
    <div
      className="relative flex h-full w-full flex-col bg-tg-bg"
      style={SAFE_AREA_ROOT}
      data-testid="manage-zone"
    >
      <SimulationBanner />
      {/* В шапке осталось ровно одно решение: в какой я зоне.
          До 02.11.2026 здесь стояли подряд декоративный значок с гаечным
          ключом (выглядел кнопкой и не делал ничего), вкладки зон, язык и
          тема — четыре разных типа элементов в одну строку. Язык и тема —
          настройки и уехали в «Настройки» (правая кнопка нижней полосы),
          значок убран совсем: подпись вкладки говорит то же самое словами. */}
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2 sm:px-4">
        <div className="hidden min-w-0 flex-1 md:block">
          <div className="truncate text-sm font-semibold text-tg-text">
            {tx("Управление")}
          </div>
          <div className="truncate text-2xs text-tg-hint">
            {tx("Кабинет руководителя")}
          </div>
        </div>
        <div className="flex min-w-0 flex-1 justify-center md:flex-none">
          <ModeSwitch className="w-full max-w-[320px]" />
        </div>
        {/* На широком экране переключатель слева от заголовка не нужен правый
            отступ: flex-1 у заголовка уже держит его по центру. */}
        <div className="hidden flex-1 md:block" />
      </header>
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="mx-auto flex h-full min-h-0 w-full max-w-[1360px] flex-col">
          <Suspense
            fallback={
              <div className="flex flex-1 flex-col gap-3 p-4">
                <Skeleton className="h-11" />
                <Skeleton className="h-20" />
                <Skeleton className="h-20" />
                <Skeleton className="h-20" />
              </div>
            }
          >
            <AdminScreen
              users={users}
              platform={platform}
              canManage={canManage}
            />
          </Suspense>
        </div>
      </main>
      {/* Полоса разделов управления — внизу, как у сотрудника: главный экран
          зоны не должен требовать возврата в общий список на каждый шаг. */}
      <ManageTabBar canManage={canManage} platform={platform} />
    </div>
  );
}
