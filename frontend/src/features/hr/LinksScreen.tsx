import { useQuery } from "@tanstack/react-query";
import { fetchEmployee, fetchLinks } from "@/api/hr";
import ErrorState from "@/components/ErrorState";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic, WebApp } from "@/tg/webapp";

/**
 * SemiTaskBot: «Полезные ссылки».
 *
 * Справочник рабочих ссылок (инструкции, регламенты, CRM, формы отчётности).
 * Ссылки привязаны к подразделениям: сотруднику приходят общие плюс ссылки
 * своего подразделения — отбор делает сервер, клиент просто рисует список.
 */
export default function LinksScreen() {
  const linksQ = useQuery({ queryKey: ["hr-links"], queryFn: fetchLinks });
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });

  if (linksQ.isError)
    return (
      <ErrorState error={linksQ.error} onRetry={() => void linksQ.refetch()} />
    );

  const links = linksQ.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <h1 className="text-lg font-semibold text-tg-text">Полезные ссылки</h1>
        <p className="mt-1 text-xs text-tg-hint">
          {meQ.data?.department_name
            ? `Общие и для подразделения «${meQ.data.department_name}»`
            : "Инструкции, регламенты и рабочие сервисы"}
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {linksQ.isLoading && <ListSkeleton rows={6} />}

        {!linksQ.isLoading && links.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="text-4xl" aria-hidden>
              🔗
            </div>
            <div className="mt-2 text-sm font-medium text-tg-text">
              Ссылок пока нет
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              Руководитель добавит их в админке — здесь появится список.
            </div>
          </div>
        )}

        {links.map((l) => (
          <button
            key={l.id}
            type="button"
            onClick={() => {
              haptic("light");
              // Telegram сам решает, открыть ссылку внутри или во внешнем
              // браузере: обычный `window.open` внутри вебвью часто блокируется.
              const app = WebApp as unknown as {
                openLink?: (url: string) => void;
                openTelegramLink?: (url: string) => void;
              };
              if (app.openLink) app.openLink(l.url);
              else window.open(l.url, "_blank", "noopener,noreferrer");
            }}
            className="block w-full rounded-xl bg-tg-secondary-bg/60 p-3 text-left active:scale-[0.99] transition-transform"
          >
            <div className="flex items-center gap-3">
              <span className="text-xl" aria-hidden>
                {l.emoji ?? "🔗"}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-tg-text">
                  {l.title}
                </span>
                <span className="block truncate text-[11px] text-tg-hint">
                  {l.url}
                </span>
              </span>
              <span className="shrink-0 text-tg-hint" aria-hidden>
                ›
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
