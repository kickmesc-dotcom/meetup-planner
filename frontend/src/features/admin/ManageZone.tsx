import { lazy, Suspense } from "react";
import Icon from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { Skeleton } from "@/components/Skeleton";
import SimulationBanner from "@/components/SimulationBanner";
import ThemeSwitcher from "@/components/ThemeSwitcher";
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
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2 sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-tile bg-tg-link/15 text-tg-link">
            <Icon name="admin" size={17} />
          </span>
          <div className="hidden min-w-0 sm:block">
            <div className="truncate text-sm font-semibold text-tg-text">
              {tx("Управление")}
            </div>
            <div className="truncate text-2xs text-tg-hint">
              {tx("Кабинет руководителя")}
            </div>
          </div>
        </div>
        {/* Переключатель по центру: он и есть главный элемент этой шапки —
            отсюда человек возвращается к своей смене. */}
        <div className="flex min-w-0 flex-1 justify-center">
          <ModeSwitch className="w-full max-w-[320px]" />
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <LanguageSwitcher />
          <ThemeSwitcher />
        </div>
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
    </div>
  );
}
