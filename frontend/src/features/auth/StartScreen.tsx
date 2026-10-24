import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { clearAllTokens } from "@/api/client";
import { logoutRequest } from "@/api/auth";
import { createOrganization, joinOrganization } from "@/api/orgs";
import Icon from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { useErrorMessage, useTx } from "@/i18n";
import { haptic } from "@/tg/webapp";

/**
 * Первый запуск: прежде чем что-то настраивать, приложение спрашивает, кто
 * перед ним.
 *
 * Почему это первый вопрос, а не выбор внутри анкеты. Дальше сценарии
 * расходятся полностью: сотрудник присоединяется к уже существующей команде и
 * получает готовые отделы и задачи, руководитель заводит организацию с нуля и
 * приглашает людей. Анкета «какое у вас направление» имеет смысл только для
 * второго — спрашивать её у повара, которого позвали в смену, значит просить
 * его отвечать за чужой бизнес.
 *
 * Вход в организацию — только по точному коду или точному названию, которое
 * человек получил от своего руководителя. Список клиентов платформы наружу не
 * показывается: он внутренний. Поэтому здесь нет поиска с подсказками — поле
 * ввода и понятная ошибка.
 *
 * Ссылка-приглашение этот экран обходит: она уже называет организацию и роль,
 * и человек попадает сразу в неё (`InviteScreen`).
 */
const INDUSTRIES = [
  { id: "restaurant", label: "Ресторан" },
  { id: "cafe", label: "Кафе или кофейня" },
  { id: "salon", label: "Салон красоты" },
  { id: "autoservice", label: "Автосервис" },
  { id: "retail", label: "Магазин" },
  { id: "other", label: "Другое" },
];

type Mode = "choose" | "join" | "create";

export default function StartScreen({ onDone }: { onDone: () => void }) {
  const { tx } = useTx();
  const errorText = useErrorMessage();
  const [mode, setMode] = useState<Mode>("choose");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("restaurant");
  const [leaving, setLeaving] = useState(false);

  const join = useMutation({
    mutationFn: () => joinOrganization(code),
    onSuccess: () => {
      haptic("success");
      onDone();
    },
  });

  const create = useMutation({
    mutationFn: () => createOrganization(name, industry),
    onSuccess: () => {
      haptic("success");
      onDone();
    },
  });

  const error = join.error ?? create.error;
  const busy = join.isPending || create.isPending;

  const leave = () => {
    setLeaving(true);
    // Локальный токен забываем в любом случае: «выйти» не должно зависеть от
    // того, ответил ли сервер.
    void logoutRequest()
      .catch(() => undefined)
      .finally(() => {
        clearAllTokens();
        window.location.reload();
      });
  };

  const back = () => {
    haptic("light");
    setMode("choose");
    join.reset();
    create.reset();
  };

  return (
    <div className="flex h-full flex-col bg-tg-bg">
      <header className="flex items-center justify-between gap-2 px-4 pt-4">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-tg-hint">
          <Icon name="bot" size={16} />
          {tx("SemiWorkBot")}
        </div>
        {/* Язык доступен до любого выбора: человек, впервые открывший
            приложение, не должен проходить незнакомый сценарий на чужом
            языке. */}
        <div className="flex items-center gap-1">
          <LanguageSwitcher />
          <ThemeSwitcher />
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-6">
        {mode !== "choose" && (
          <button
            type="button"
            onClick={back}
            disabled={busy}
            className="mb-4 inline-flex min-h-9 items-center gap-1 rounded-tile px-2 text-xs text-tg-link disabled:opacity-50"
          >
            <Icon name="back" size={13} />
            {tx("Назад")}
          </button>
        )}

        {mode === "choose" && (
          <section className="space-y-4">
            <div>
              <h1 className="text-xl font-semibold text-tg-text">
                {tx("Кто вы в компании?")}
              </h1>
              <p className="mt-2 text-sm text-tg-hint">
                {tx(
                  "Сотрудник присоединяется к готовой команде по коду от руководителя. Руководитель создаёт организацию и приглашает людей сам.",
                )}
              </p>
            </div>

            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setMode("join");
              }}
              className="flex w-full items-start gap-3 rounded-card border border-tg-hint/15 bg-tg-secondary-bg/50 p-4 text-left transition-colors active:bg-tg-secondary-bg"
            >
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-link/15 text-tg-link">
                <Icon name="team" size={18} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-tg-text">
                  {tx("Я сотрудник")}
                </span>
                <span className="mt-0.5 block text-xs text-tg-hint">
                  {tx(
                    "Присоединиться к команде: нужен код компании или её точное название.",
                  )}
                </span>
              </span>
            </button>

            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setMode("create");
              }}
              className="flex w-full items-start gap-3 rounded-card border border-tg-hint/15 bg-tg-secondary-bg/50 p-4 text-left transition-colors active:bg-tg-secondary-bg"
            >
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-tg-link/15 text-tg-link">
                <Icon name="admin" size={18} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-tg-text">
                  {tx("Я руководитель")}
                </span>
                <span className="mt-0.5 block text-xs text-tg-hint">
                  {tx(
                    "Создать организацию, пригласить сотрудников и настроить отделы.",
                  )}
                </span>
              </span>
            </button>
          </section>
        )}

        {mode === "join" && (
          <section className="space-y-4">
            <div>
              <h1 className="text-lg font-semibold text-tg-text">
                {tx("Вход в организацию")}
              </h1>
              <p className="mt-1 text-xs text-tg-hint">
                {tx(
                  "Руководитель видит код компании в разделе «Приглашения». Если кода нет, подойдёт точное название — слово в слово, как в приложении.",
                )}
              </p>
            </div>

            <label className="block">
              <span className="text-xs font-medium text-tg-hint">
                {tx("Код или название компании")}
              </span>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                placeholder={tx("ID или название")}
                aria-label={tx("Код или название компании")}
                className="mt-1 w-full rounded-tile border border-tg-hint/20 bg-tg-secondary-bg px-3 py-2 text-sm text-tg-text placeholder:text-tg-hint/70 focus:outline-none focus:ring-2 focus:ring-tg-link/40"
              />
            </label>

            {error && (
              <p className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
                <Icon name="alert" size={13} className="mr-1 inline-block" />
                {errorText(error)}
              </p>
            )}

            <button
              type="button"
              disabled={busy || code.trim().length < 2}
              onClick={() => join.mutate()}
              className="min-h-11 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              {join.isPending ? tx("Проверяем…") : tx("Присоединиться")}
            </button>

            <p className="text-xs text-tg-hint">
              {tx(
                "Если код не подходит, попросите у руководителя ссылку-приглашение — она сразу откроет нужную организацию.",
              )}
            </p>
          </section>
        )}

        {mode === "create" && (
          <section className="space-y-4">
            <div>
              <h1 className="text-lg font-semibold text-tg-text">
                {tx("Новая организация")}
              </h1>
              <p className="mt-1 text-xs text-tg-hint">
                {tx(
                  "Вы станете её владельцем. После этого — короткая настройка: отделы и разделы приложения.",
                )}
              </p>
            </div>

            <label className="block">
              <span className="text-xs font-medium text-tg-hint">
                {tx("Название компании")}
              </span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
                maxLength={120}
                placeholder={tx("Например, «Кофейня на углу»")}
                aria-label={tx("Название компании")}
                className="mt-1 w-full rounded-tile border border-tg-hint/20 bg-tg-secondary-bg px-3 py-2 text-sm text-tg-text placeholder:text-tg-hint/70 focus:outline-none focus:ring-2 focus:ring-tg-link/40"
              />
            </label>

            <div>
              <span className="text-xs font-medium text-tg-hint">
                {tx("Направление")}
              </span>
              <div className="mt-1 grid grid-cols-2 gap-2">
                {INDUSTRIES.map((item) => {
                  const active = industry === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => {
                        haptic("selection");
                        setIndustry(item.id);
                      }}
                      className={[
                        "min-h-11 rounded-tile px-2 text-xs transition-colors",
                        active
                          ? "bg-tg-link/15 font-medium text-tg-text ring-1 ring-tg-link/40"
                          : "bg-tg-secondary-bg text-tg-hint",
                      ].join(" ")}
                    >
                      {tx(item.label)}
                    </button>
                  );
                })}
              </div>
            </div>

            {error && (
              <p className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
                <Icon name="alert" size={13} className="mr-1 inline-block" />
                {errorText(error)}
              </p>
            )}

            <button
              type="button"
              disabled={busy || name.trim().length < 2}
              onClick={() => create.mutate()}
              className="min-h-11 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              {create.isPending
                ? tx("Создаём…")
                : tx("Создать организацию")}
            </button>
            <p className="text-xs text-tg-hint">
              {tx(
                "Сотрудников можно пригласить сразу после настройки — ссылкой или кодом компании.",
              )}
            </p>
          </section>
        )}
      </div>

      <footer className="border-t border-tg-secondary-bg px-4 py-3">
        <button
          type="button"
          disabled={leaving}
          onClick={leave}
          className="min-h-9 text-xs text-tg-hint disabled:opacity-50"
        >
          {leaving ? tx("Выходим…") : tx("Выйти из аккаунта")}
        </button>
      </footer>
    </div>
  );
}
