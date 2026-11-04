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
 * другой: что происходит с людьми и предприятием.
 *
 * 04.11.2026, жалоба владельца: на десктопе зона сотрудника рисовала сайдбар
 * слева, а кабинет — заголовок сверху и полосу снизу, и при переключении зон
 * навигация прыгала по экрану. Причина была не в стилях, а в двух разных
 * каркасах. Теперь на широком экране каркас один (`DesktopShell`): сайдбар
 * слева, переключатель зон сверху. Этот компонент при `desktop` не рисует ни
 * своей шапки, ни нижней полосы — иначе внутри общего каркаса появился бы
 * второй набор тех же элементов.
 */
export default function ManageZone({
  users,
  platform = false,
  canManage = false,
  desktop = false,
}: {
  users: User[];
  /** Прописанный админ платформы: видит системные разделы (прокси, тексты…). */
  platform?: boolean;
  /** Руководитель: видит команду, приёмку и отчёт смены. */
  canManage?: boolean;
  /** Широкий экран: навигация живёт в сайдбаре `DesktopShell`. */
  desktop?: boolean;
}) {
  const { tx } = useTx();

  const content = (
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
  );

  if (desktop) {
    return (
      <div
        className="flex min-h-0 flex-1 flex-col bg-tg-bg"
        data-testid="manage-zone"
        data-layout="desktop"
      >
        <SimulationBanner />
        {content}
      </div>
    );
  }

  return (
    <div
      className="relative flex h-full w-full flex-col bg-tg-bg"
      style={SAFE_AREA_ROOT}
      data-testid="manage-zone"
    >
      <SimulationBanner />
      {/* В шапке осталось ровно одно решение: в какой я зоне. Язык и тема —
          настройки и живут в «Настройках». */}
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
      {content}
      {/* Полоса разделов управления — только на узком экране: на ПК навигация
          уже в сайдбаре, и вторая полоса внизу — это ровно то, на что жаловался
          владелец. */}
      <ManageTabBar canManage={canManage} platform={platform} />
    </div>
  );
}
