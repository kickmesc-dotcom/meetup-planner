import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchEmployee,
  fetchNotifyPrefs,
  setMyName,
  setNotifyPref,
  setProfilePrivacy,
  setProfileVisibility,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import Icon, { type IconName } from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { CardSkeleton } from "@/components/Skeleton";
import FeedbackScreen from "@/features/hr/FeedbackScreen";
import PrivacyRow from "@/features/hr/PrivacyRow";
import PushCard from "@/features/hr/PushCard";
import { NOTIFY_KINDS } from "@/features/hr/notifyKinds";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { useTx } from "@/i18n";

/**
 * «Настройки» — одна дверь к личным настройкам.
 *
 * Почему отдельный экран. До 06.11.2026 личные настройки были разбросаны:
 * язык и тема — в шапке профиля, уведомления — только в «Сводке дня», обратная
 * связь — строкой в «Разделах», публичность — в блоке «кто я», тариф и оплата
 * — только в кабинете руководителя. Человек, которому нужно было выключить
 * уведомление, искал это в трёх местах и в двух не находил.
 *
 * Граница с `admin/SettingsScreen`. Тот экран настраивает предприятие (языки
 * команды, тексты, данные и приватность организации). Этот — только себя:
 * имя, что видят коллеги, что приходит в Telegram, язык, обратная связь и —
 * у руководителя — деньги. Смешивать их нельзя: сотрудник не должен видеть
 * кнопки, которые меняют чужие данные.
 *
 * Уведомления — по явному выбору. Все виды выключены по умолчанию, и это
 * правило сервера: здесь его нельзя «улучшить» галочкой.
 */
function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-card bg-tg-secondary-bg/60 p-3">
      <h2 className="text-sm font-semibold text-tg-text">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-tg-hint">{hint}</p>}
      <div className="mt-2 space-y-2">{children}</div>
    </section>
  );
}

function LinkRow({
  icon,
  title,
  hint,
  onClick,
}: {
  icon: IconName;
  title: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        haptic("light");
        onClick();
      }}
      className="flex min-h-11 w-full items-center gap-2 rounded-tile bg-tg-bg/50 px-2 text-left text-xs text-tg-text active:bg-tg-bg/70"
    >
      <Icon name={icon} size={16} className="shrink-0 text-tg-hint" />
      <span className="min-w-0 flex-1">
        {title}
        <span className="block text-2xs text-tg-hint">{hint}</span>
      </span>
      <Icon name="chevron" size={14} className="shrink-0 text-tg-hint" />
    </button>
  );
}

export default function MySettingsScreen({ onClose }: { onClose: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const setMode = useUI((s) => s.setMode);
  const setPendingAdminSection = useUI((s) => s.setPendingAdminSection);
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const prefsQ = useQuery({
    queryKey: ["notify-prefs"],
    queryFn: fetchNotifyPrefs,
    staleTime: 30_000,
  });
  const [name, setName] = useState("");
  const [busyKind, setBusyKind] = useState<string | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);

  const me = meQ.data;

  // Имя подставляется из профиля, но дальше живёт отдельно: иначе каждый
  // фоновый рефетч затирал бы набранный текст.
  useEffect(() => {
    setName(me?.display_name ?? "");
  }, [me?.display_name]);

  const saveName = useMutation({
    mutationFn: (value: string) => setMyName(value),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void qc.invalidateQueries({ queryKey: ["hr-feed"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const visibility = useMutation({
    mutationFn: (isPublic: boolean) => setProfileVisibility(isPublic),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void qc.invalidateQueries({ queryKey: ["hr-feed"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const privacy = useMutation({
    mutationFn: (body: { show_last_seen?: boolean; show_last_media?: boolean }) =>
      setProfilePrivacy(body),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void qc.invalidateQueries({ queryKey: ["hr-profile-card"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const toggleNotify = useMutation({
    mutationFn: ({ kind, enabled }: { kind: string; enabled: boolean }) =>
      setNotifyPref(kind, enabled),
    onSuccess: (data) => {
      qc.setQueryData(["notify-prefs"], data);
      setBusyKind(null);
    },
    onError: (error) => {
      setBusyKind(null);
      void showAlert(humanizeApiError(error));
    },
  });

  const enabledOf = (kind: string) =>
    prefsQ.data?.prefs.find((p) => p.kind === kind)?.enabled ?? false;

  // «У руководителей» — это те, кому сервер разрешил кабинет: руководитель
  // подразделения, админ организации и админ платформы. У сотрудника секции
  // оплаты нет вообще, а не «есть, но неактивна».
  const canManage = !!(me?.is_aup || me?.is_admin || me?.is_staff);
  const openManage = (section: string) => {
    setPendingAdminSection(section);
    setMode("manage");
  };

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-tg-bg">
      <header className="flex items-center gap-3 border-b border-tg-secondary-bg py-3 pl-4 pr-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-base font-medium text-tg-text">
            <Icon name="settings" size={16} />
            {tx("Настройки")}
          </div>
          <div className="text-xs text-tg-hint">
            {tx("Профиль, уведомления, язык и оплата")}
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          className="min-h-9 shrink-0 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-text"
        >
          {tx("Закрыть")}
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {meQ.isLoading && <CardSkeleton />}
        {meQ.isError && (
          <ErrorState error={meQ.error} onRetry={() => void meQ.refetch()} />
        )}

        {me && (
          <>
            <Section
              title={tx("Профиль")}
              hint={tx("Коллеги видят это имя в ленте, команде и отчёте смены")}
            >
              <label className="block text-xs text-tg-hint" htmlFor="my-name">
                {tx("Имя в приложении")}
              </label>
              <div className="flex gap-2">
                <input
                  id="my-name"
                  value={name}
                  maxLength={64}
                  onChange={(event) => setName(event.target.value)}
                  autoComplete="name"
                  className="min-h-11 min-w-0 flex-1 rounded-tile bg-tg-bg px-2 text-sm text-tg-text"
                />
                <button
                  type="button"
                  disabled={
                    saveName.isPending ||
                    !name.trim() ||
                    name.trim() === me.display_name
                  }
                  onClick={() => saveName.mutate(name.trim())}
                  className="min-h-11 shrink-0 rounded-tile bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
                >
                  {tx("Сохранить")}
                </button>
              </div>
              <p className="text-2xs text-tg-hint">
                {tx(
                  "Это не имя из Telegram: рабочее имя можно поставить любое, аккаунт в мессенджере не меняется.",
                )}
              </p>
            </Section>

            <Section
              title={tx("Публичность профиля")}
              hint={tx("Кто видит твою активность, цифры и отметки")}
            >
              <div className="flex items-center gap-2 rounded-tile bg-tg-bg/50 p-2">
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-tg-text">
                    {me.profile_public
                      ? tx("Профиль открыт")
                      : tx("Профиль закрыт")}
                  </div>
                  <div className="text-2xs text-tg-hint">
                    {me.profile_public
                      ? tx(
                          "Коллеги видят твою активность и цифры. Руководитель видит их всегда.",
                        )
                      : tx(
                          "Коллеги видят только имя и отдел. Руководитель и админ — всё.",
                        )}
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={me.profile_public}
                  aria-label={tx("Публичность профиля")}
                  disabled={visibility.isPending || me.profile_locked}
                  onClick={() => visibility.mutate(!me.profile_public)}
                  className={[
                    "min-h-9 shrink-0 rounded-full px-3 text-xs transition-colors disabled:opacity-60",
                    me.profile_public
                      ? "bg-tg-button text-tg-button-text"
                      : "bg-tg-secondary-bg text-tg-text",
                  ].join(" ")}
                >
                  {me.profile_locked
                    ? tx("Так решили")
                    : me.profile_public
                      ? tx("Открыт")
                      : tx("Закрыт")}
                </button>
              </div>
              <PrivacyRow
                title={tx("Последний заход")}
                hint={
                  me.can_toggle_last_seen
                    ? tx("Коллеги видят, когда ты последний раз открывал приложение.")
                    : tx("Включено руководителем — выключить нельзя.")
                }
                value={me.show_last_seen}
                locked={!me.can_toggle_last_seen}
                busy={privacy.isPending}
                onToggle={() =>
                  privacy.mutate({ show_last_seen: !me.show_last_seen })
                }
              />
              <PrivacyRow
                title={tx("Последнее медиа")}
                hint={
                  me.can_toggle_last_media
                    ? tx("Коллеги видят твоё последнее фото из отчёта.")
                    : tx("Включено руководителем — выключить нельзя.")
                }
                value={me.show_last_media}
                locked={!me.can_toggle_last_media}
                busy={privacy.isPending}
                onToggle={() =>
                  privacy.mutate({ show_last_media: !me.show_last_media })
                }
              />
            </Section>

            <Section
              title={tx("Уведомления")}
              hint={tx(
                "В Telegram — только то, что ты выбрал сам; всё выключено по умолчанию",
              )}
            >
              {prefsQ.isError && (
                <p className="rounded-tile bg-tg-bg/50 p-2 text-xs text-tg-hint">
                  {tx("Не удалось загрузить уведомления — обнови экран.")}
                </p>
              )}
              {NOTIFY_KINDS.map((item) => {
                const enabled = enabledOf(item.kind);
                return (
                  <div
                    key={item.kind}
                    className="flex items-center gap-2 rounded-tile bg-tg-bg/50 p-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-tg-text">{tx(item.label)}</div>
                      <div className="text-2xs text-tg-hint">{tx(item.hint)}</div>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={enabled}
                      aria-label={tx(item.label)}
                      disabled={prefsQ.isLoading || busyKind === item.kind}
                      onClick={() => {
                        haptic("light");
                        setBusyKind(item.kind);
                        toggleNotify.mutate({
                          kind: item.kind,
                          enabled: !enabled,
                        });
                      }}
                      className={[
                        "min-h-9 shrink-0 rounded-full px-3 text-xs transition-colors disabled:opacity-60",
                        enabled
                          ? "bg-tg-button text-tg-button-text"
                          : "bg-tg-secondary-bg text-tg-text",
                      ].join(" ")}
                    >
                      {enabled ? tx("Вкл") : tx("Выкл")}
                    </button>
                  </div>
                );
              })}
              <p className="text-2xs text-tg-hint">
                {tx(
                  "Уведомления в приложении не отключаются: это лента, куда заходят сами. Здесь — то, что приходит в Telegram.",
                )}
              </p>
              <PushCard />
            </Section>

            <Section
              title={tx("Язык и вид")}
              hint={tx("Язык меняется без перезагрузки — так же, как тема")}
            >
              <div className="flex items-center justify-between gap-3 rounded-tile bg-tg-bg/50 p-2">
                <div className="min-w-0">
                  <div className="text-xs text-tg-text">{tx("Язык")}</div>
                  <div className="text-2xs text-tg-hint">
                    {tx("Русский, English или O‘zbekcha")}
                  </div>
                </div>
                <LanguageSwitcher />
              </div>
              <div className="flex items-center justify-between gap-3 rounded-tile bg-tg-bg/50 p-2">
                <div className="min-w-0">
                  <div className="text-xs text-tg-text">{tx("Тема")}</div>
                  <div className="text-2xs text-tg-hint">
                    {tx("Светлая или тёмная — по клику")}
                  </div>
                </div>
                <ThemeSwitcher />
              </div>
            </Section>

            <Section
              title={tx("Обратная связь")}
              hint={tx("Ответы уходят руководителю, а не в общий чат")}
            >
              <LinkRow
                icon="edit"
                title={tx("Как прошла смена")}
                hint={tx("Несколько вопросов — можно ответить сейчас")}
                onClick={() => setShowFeedback(true)}
              />
            </Section>

            {canManage && (
              <Section
                title={tx("Оплата и тариф")}
                hint={tx("Оплата по счёту: списаний с карты нет")}
              >
                <LinkRow
                  icon="award"
                  title={tx("Тариф и лимиты")}
                  hint={tx("Места, подразделения и срок пробного периода")}
                  onClick={() => openManage("plan")}
                />
                <LinkRow
                  icon="award"
                  title={tx("Оплата и счета")}
                  hint={tx("Выставить счёт, «я оплатил» и история платежей")}
                  onClick={() => openManage("billing")}
                />
                <p className="text-2xs text-tg-hint">
                  {tx(
                    "Тариф не переключается одним нажатием: смена тарифа — это деньги, её подтверждает платформа после оплаты.",
                  )}
                </p>
              </Section>
            )}
          </>
        )}
      </div>

      {showFeedback && (
        <FeedbackScreen onClose={() => setShowFeedback(false)} />
      )}
    </div>
  );
}
