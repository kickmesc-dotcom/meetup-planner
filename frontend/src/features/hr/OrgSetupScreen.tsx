import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDepartments,
  fetchOrgSetupProgress,
  saveOrgSetup,
  type OrgSetup,
  type OrgSetupPatch,
  type OrgProfileVisibility,
} from "@/api/hr";
import { createInvitation, type OrgInvitation } from "@/api/orgs";
import Hint from "@/components/Hint";
import {
  applyShiftTemplate,
  fetchShiftWeek,
  saveShiftTemplate,
} from "@/api/shifts";
import { copyText } from "@/lib/clipboard";
import { clearDraft, readDraft, writeDraft } from "@/lib/formDraft";
import { humanizeApiError } from "@/api/client";
import Icon from "@/components/Icon";
import FormField from "@/components/FormField";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { showToast } from "@/components/toast";
import ProgressBar from "@/components/ProgressBar";
import { SkeletonChips } from "@/components/Skeleton";
import { OPTIONAL_SECTIONS } from "@/features/hr/sections";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";

/**
 * Мастер первой настройки организации для руководителя.
 *
 * Зачем мастер, а не пачка галочек в админке. Новый клиент не знает, какие
 * разделы ему нужны и какие правила приватности приняты у него в коллективе;
 * перечислять это списком — значит требовать от него знания продукта. Поэтому
 * пять коротких вопросов с готовыми вариантами, а на выходе — приложение под
 * его предприятие: подразделения, разделы, видимость профилей и наблюдение
 * между отделами.
 *
 * Ответы сохраняются ПО ШАГАМ: если человек закроет приложение на середине,
 * уже отвеченное не потеряется, и мастер продолжит с того же места.
 *
 * Пропустить можно в любой момент — настройки по умолчанию рабочие, а мастер
 * остаётся доступным из админки.
 *
 * Переключатель языка живёт в шапке мастера на всех пяти шагах. Раньше он был
 * только в профиле: человек, впервые открывший приложение, проходил настройку
 * на языке, который не выбирал, и не мог это исправить на месте.
 */
const ORG_SETUP_DRAFT_KEY = "semitaskbot.org-setup.draft.v1";

type StoredOrgDraft = { draft: OrgSetup; picked: string[] };

export default function OrgSetupScreen({
  setup,
  onClose,
}: {
  setup: OrgSetup;
  onClose: () => void;
}) {
  const { tx } = useTx();
  const qc = useQueryClient();
  // §3 `form-autosave`: мастер проходят один раз и до первой организации,
  // поэтому черновик живёт на устройстве. Перезагрузка страницы или случайный
  // уход не откатывают ответы к началу.
  const restoredDraft = useMemo(
    () => readDraft<StoredOrgDraft>(ORG_SETUP_DRAFT_KEY),
    [],
  );
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<OrgSetup>(() => restoredDraft?.draft ?? setup);
  const [error, setError] = useState<string | null>(null);

  const depsQ = useQuery({
    queryKey: ["hr-departments"],
    queryFn: fetchDepartments,
    staleTime: 5 * 60_000,
  });

  const save = useMutation({
    mutationFn: (patch: OrgSetupPatch) => saveOrgSetup(patch),
    onSuccess: (data) => {
      setDraft(data);
      setError(null);
      qc.setQueryData(["org-setup"], data);
      void qc.invalidateQueries({ queryKey: ["hr-departments"] });
    },
    onError: (err) => setError(humanizeApiError(err)),
  });

  // Выбранные подразделения: ответы мастера + уже существующие отделы, чтобы
  // повторный проход не выглядел как «ничего не настроено».
  const departmentOptions = useMemo(() => {
    const names = new Map<string, string | null>();
    for (const dep of depsQ.data ?? []) names.set(dep.name, dep.emoji);
    for (const preset of draft.presets) {
      if (!names.has(preset.name)) names.set(preset.name, preset.emoji);
    }
    for (const name of draft.departments) {
      if (!names.has(name)) names.set(name, null);
    }
    return [...names.entries()];
  }, [depsQ.data, draft.presets, draft.departments]);

  const [pickedDepartments, setPickedDepartments] = useState<string[]>(
    () => restoredDraft?.picked ?? setup.departments,
  );

  useEffect(() => {
    writeDraft(ORG_SETUP_DRAFT_KEY, {
      draft,
      picked: pickedDepartments,
    });
  }, [draft, pickedDepartments]);

  useEffect(() => {
    if (restoredDraft) showToast(tx("Черновик восстановлен."), "info");
  }, [restoredDraft, tx]);

  // Список отделов приходит асинхронно, а `useState` инициализируется один
  // раз. Поэтому первый раз, когда он загрузился, отмечаем уже существующие
  // отделы — иначе человек видел бы пустой выбор там, где у него всё есть.
  useEffect(() => {
    if (!depsQ.data || setup.departments.length) return;
    setPickedDepartments((cur) =>
      cur.length
        ? cur
        : depsQ.data.map((dep) => dep.name).slice(0, 20),
    );
  }, [depsQ.data, setup.departments.length]);

  const steps = [
    tx("Предприятие"),
    tx("Подразделения"),
    tx("Люди"),
    tx("График"),
    tx("Разделы"),
    tx("Кто что видит"),
    tx("Готово"),
  ];
  const lastStep = steps.length - 1;

  // Сводка нужна только на последнем шаге: до него это лишний запрос на
  // каждый ответ мастера.
  const progressQ = useQuery({
    queryKey: ["org-setup-progress"],
    queryFn: fetchOrgSetupProgress,
    enabled: step === lastStep,
    staleTime: 30_000,
    retry: false,
  });

  const toggleSection = (id: string) => {
    haptic("selection");
    setDraft((cur) => ({
      ...cur,
      sections: cur.sections.includes(id)
        ? cur.sections.filter((x) => x !== id)
        : [...cur.sections, id],
    }));
  };

  /**
   * Что сохранить при уходе с шага. `null` — у шага нет ответов мастера:
   * «Люди» и «График» живут своими ручками (приглашение, шаблон смены),
   * и пустой POST только ради галочки был бы лишним запросом.
   */
  const patchForStep = (target: number): OrgSetupPatch | null => {
    switch (target) {
      case 0:
        return { industry: draft.industry, headcount: draft.headcount };
      case 1:
        return { departments: pickedDepartments, create_departments: true };
      case 4:
        return { sections: draft.sections };
      case 5:
        return {
          profile_visibility: draft.profile_visibility,
          cross_department_watch: draft.cross_department_watch,
          allow_hide_last_seen: draft.allow_hide_last_seen,
          allow_hide_media: draft.allow_hide_media,
        };
      default:
        return null;
    }
  };

  const go = async (target: number) => {
    haptic("light");
    setError(null);
    const patch = patchForStep(step);
    if (target <= lastStep && patch) {
      try {
        // Сохраняем ответы ТОГО шага, с которого уходим. Раньше здесь стоял
        // `patchForStep(target)`, то есть патч следующего шага: отрасль и
        // подразделения молча не доезжали до сервера — человек видел их в
        // итоговой сводке, а следующий экран показывал пустой список отделов.
        await save.mutateAsync(patch);
      } catch {
        return; // ошибка уже в состоянии мутации и на экране
      }
    }
    setStep(Math.max(0, Math.min(lastStep, target)));
  };

  const finish = async () => {
    haptic("success");
    try {
      const data = await save.mutateAsync({
        ...(patchForStep(step) ?? {}),
        done: true,
      });
      qc.setQueryData(["org-setup"], data);
      clearDraft(ORG_SETUP_DRAFT_KEY);
      onClose();
    } catch {
      /* ошибка на экране */
    }
  };

  const skip = async () => {
    haptic("light");
    try {
      const data = await save.mutateAsync({ done: true });
      qc.setQueryData(["org-setup"], data);
      // «Пропустить» — тоже окончание мастера: черновик больше не нужен.
      clearDraft(ORG_SETUP_DRAFT_KEY);
      onClose();
    } catch {
      /* ошибка на экране */
    }
  };

  return (
    <div className="flex h-full flex-col bg-tg-bg">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
              <Icon name="admin" size={16} className="shrink-0" />
              <span className="truncate">{tx("Настроим под вас")}</span>
            </div>
            <div className="truncate text-xs text-tg-hint">
              {tx("Шаг {step} из {total}: {title}", {
                step: step + 1,
                total: steps.length,
                title: steps[step],
              })}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {/* Язык — на каждом шаге: мастер открывается первым, и менять язык
                через профиль на этом экране было невозможно. */}
            <LanguageSwitcher />
            <button
              type="button"
              onClick={skip}
              disabled={save.isPending}
              aria-busy={save.isPending}
              className="min-h-9 rounded-tile px-2 text-xs text-tg-link disabled:opacity-50"
            >
              {tx("Пропустить")}
            </button>
          </div>
        </div>
        <div className="mt-2">
          <ProgressBar value={step + 1} total={steps.length} size="sm" />
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {error && (
          // §3 `error-summary`: ошибка шага объявляется сразу — иначе
          // скринридер узнаёт о ней, только дойдя до конца шага.
          <div
            role="alert"
            className="mb-3 rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy"
          >
            <Icon name="alert" size={13} className="mr-1 inline-block" />
            {error}
          </div>
        )}

        {step === 0 && (
          <section className="space-y-4">
            <div>
              <h2 className="text-heading text-tg-text">
                {tx("Что у вас за предприятие?")}
              </h2>
              <Hint size="xs">
                {tx("От этого зависят подсказки по подразделениям и акценты в приложении.")}
              </Hint>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {INDUSTRIES.map((item) => (
                <Choice
                  key={item.id}
                  label={tx(item.label)}
                  active={draft.industry === item.id}
                  onClick={() => {
                    haptic("selection");
                    // Подсказки подразделений приходят с сервера — сохраняем
                    // отрасль сразу, чтобы следующий шаг был уже под неё.
                    setDraft((cur) => ({ ...cur, industry: item.id }));
                  }}
                />
              ))}
            </div>
            <div>
              <h2 className="text-heading text-tg-text">
                {tx("Сколько человек в штате?")}
              </h2>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {HEADCOUNTS.map((item) => (
                  <Choice
                    key={item.id}
                    label={tx(item.label)}
                    active={draft.headcount === item.id}
                    onClick={() => {
                      haptic("selection");
                      setDraft((cur) => ({ ...cur, headcount: item.id }));
                    }}
                  />
                ))}
              </div>
            </div>
          </section>
        )}

        {step === 1 && (
          <section className="space-y-3">
            <div>
              <h2 className="text-heading text-tg-text">
                {tx("Из кого состоит команда?")}
              </h2>
              <Hint size="xs">
                {tx("Выберите отделы — они появятся в приложении. Свои можно добавить позже в админке.")}
              </Hint>
            </div>
            {/* Пока отделы едут, на их месте — таблетки того же размера.
                Пустой блок выглядел как «отделов нет» и толкал руководителя
                нажимать «Пропустить» на самом важном шаге. */}
            {depsQ.isPending && departmentOptions.length === 0 && (
              <div data-testid="org-setup-departments-skeleton">
                <SkeletonChips count={6} />
              </div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {departmentOptions.map(([name, emoji]) => {
                const active = pickedDepartments.includes(name);
                return (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      haptic("selection");
                      setPickedDepartments((cur) =>
                        cur.includes(name)
                          ? cur.filter((x) => x !== name)
                          : [...cur, name],
                      );
                    }}
                    className={[
                      "inline-flex min-h-9 items-center gap-1 rounded-full px-3 text-xs transition-colors",
                      active
                        ? "bg-tg-link/15 font-medium text-tg-text"
                        : "bg-tg-secondary-bg text-tg-hint",
                    ].join(" ")}
                  >
                    {emoji ? `${emoji} ` : ""}
                    {name}
                    {active && <Icon name="check" size={12} />}
                  </button>
                );
              })}
            </div>
            <CustomDepartment
              onAdd={(name) => {
                setPickedDepartments((cur) =>
                  cur.includes(name) ? cur : [...cur, name],
                );
                setDraft((cur) => ({
                  ...cur,
                  departments: cur.departments.includes(name)
                    ? cur.departments
                    : [...cur.departments, name],
                }));
              }}
            />
          </section>
        )}

        {step === 2 && (
          <PeopleStep
            positions={draft.positions}
            departments={(depsQ.data ?? []).map((dep) => ({
              id: dep.id,
              name: dep.name,
            }))}
          />
        )}

        {step === 3 && (
          <ScheduleStep
            departments={(depsQ.data ?? []).map((dep) => ({
              id: dep.id,
              name: dep.name,
            }))}
          />
        )}

        {step === 4 && (
          <section className="space-y-2">
            <div>
              <h2 className="text-heading text-tg-text">
                {tx("Какие разделы оставить?")}
              </h2>
              <Hint size="xs">
                {tx("События, задачи, чек-лист и профиль остаются всегда — это ядро смены.")}
              </Hint>
            </div>
            {OPTIONAL_SECTIONS.map((item) => (
              <Toggle
                key={item.id}
                title={tx(item.label)}
                hint={tx(item.hint)}
                value={draft.sections.includes(item.id)}
                onToggle={() => toggleSection(item.id)}
              />
            ))}
          </section>
        )}

        {step === 5 && (
          <section className="space-y-3">
            <div>
              <h2 className="text-heading text-tg-text">
                {tx("Кто что видит")}
              </h2>
              <Hint size="xs">
                {tx("Правила действуют сразу и для всех: их проверяет сервер, а не только интерфейс.")}
              </Hint>
            </div>

            <div className="space-y-2">
              {VISIBILITY.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    haptic("selection");
                    setDraft((cur) => ({
                      ...cur,
                      profile_visibility: item.id as OrgProfileVisibility,
                    }));
                  }}
                  className={[
                    "flex w-full items-start gap-2 rounded-card p-3 text-left transition-colors",
                    draft.profile_visibility === item.id
                      ? "bg-tg-link/15"
                      : "bg-tg-secondary-bg/60",
                  ].join(" ")}
                >
                  <span className="mt-0.5 shrink-0 text-tg-link">
                    <Icon
                      name={
                        draft.profile_visibility === item.id
                          ? "check"
                          : "profile"
                      }
                      size={16}
                    />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-xs font-medium text-tg-text">
                      {tx(item.label)}
                    </span>
                    <span className="mt-0.5 block text-2xs text-tg-hint">
                      {tx(item.hint)}
                    </span>
                  </span>
                </button>
              ))}
            </div>

            <div className="pt-1 text-2xs font-medium uppercase tracking-wide text-tg-hint">
              {tx("Наблюдение")}
            </div>
            <Toggle
              title={tx("Руководители видят другие отделы")}
              hint={tx(
                "Выключено: только своё подразделение. Управляющий и админ видят всё в любом случае.",
              )}
              value={draft.cross_department_watch}
              onToggle={() =>
                setDraft((cur) => ({
                  ...cur,
                  cross_department_watch: !cur.cross_department_watch,
                }))
              }
            />

            <div className="pt-1 text-2xs font-medium uppercase tracking-wide text-tg-hint">
              {tx("Что сотрудник может скрыть")}
            </div>
            <Toggle
              title={tx("Последний заход")}
              hint={tx("Если выключить — отметка видна всем и скрыть её нельзя.")}
              value={draft.allow_hide_last_seen}
              onToggle={() =>
                setDraft((cur) => ({
                  ...cur,
                  allow_hide_last_seen: !cur.allow_hide_last_seen,
                }))
              }
            />
            <Toggle
              title={tx("Последнее медиа")}
              hint={tx("Фото из последнего отчёта: видно коллегам, если разрешено.")}
              value={draft.allow_hide_media}
              onToggle={() =>
                setDraft((cur) => ({
                  ...cur,
                  allow_hide_media: !cur.allow_hide_media,
                }))
              }
            />

            <p className="rounded-tile bg-tg-secondary-bg/60 p-2 text-2xs text-tg-hint">
              {tx(
                "Руководитель и администратор видят карточку всегда — иначе им нечем принимать работу.",
              )}
            </p>
          </section>
        )}

        {step === 6 && (
          <section className="space-y-3">
            <div className="rounded-card bg-status-free/10 p-3 text-center">
              <Icon
                name="check"
                size={26}
                className="mx-auto text-status-free"
              />
              <div className="mt-1 text-sm font-medium text-tg-text">
                {tx("Всё готово")}
              </div>
              <Hint size="xs">
                {tx("Настройку можно поменять позже — в профиле, «Настройка организации».")}
              </Hint>
            </div>
            <div className="rounded-tile bg-tg-secondary-bg/60 p-3">
              <div className="text-2xs font-medium uppercase tracking-wide text-tg-hint">
                {tx("Что уже готово")}
              </div>
              {progressQ.isPending ? (
                <div className="mt-2">
                  <SkeletonChips count={2} />
                </div>
              ) : progressQ.data ? (
                <div className="mt-1 space-y-1 text-xs text-tg-text">
                  <div>
                    {tx("Подразделения")}: {progressQ.data.departments}
                  </div>
                  <div>
                    {tx("Сотрудники")}: {progressQ.data.people}
                  </div>
                  <div>
                    {tx("Приглашения")}: {progressQ.data.invites_pending}
                  </div>
                  <div>
                    {tx("Шаблоны смен")}: {progressQ.data.shift_templates}
                  </div>
                  {progressQ.data.checklists.length ? (
                    <ul className="mt-1 space-y-1">
                      {progressQ.data.checklists.slice(0, 6).map((item) => (
                        <li
                          key={`${item.department ?? ""}-${item.title}`}
                          className="text-2xs text-tg-hint"
                        >
                          {tx("Стартовые чек-листы")}: {item.title} ·{" "}
                          {item.department ?? "—"} · {item.items}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-2xs text-tg-hint">
                      {tx(
                        "Чек-листов пока нет — пакет отрасли заведёт их на последнем шаге.",
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div className="mt-1 text-2xs text-tg-hint">
                  {tx("Пока пусто — для новой организации это нормально.")}
                </div>
              )}
              {progressQ.data?.checklists.length ? (
                <div className="mt-2 text-2xs text-tg-hint">
                  {tx(
                    "Первый чек-лист уже ждёт сотрудников в разделе «Чек-лист».",
                  )}
                </div>
              ) : null}
            </div>
            <SummaryRow
              label={tx("Предприятие")}
              value={tx(
                INDUSTRIES.find((x) => x.id === draft.industry)?.label ??
                  draft.industry,
              )}
            />
            <SummaryRow
              label={tx("Штат")}
              value={tx(
                HEADCOUNTS.find((x) => x.id === draft.headcount)?.label ??
                  draft.headcount,
              )}
            />
            <SummaryRow
              label={tx("Подразделения")}
              value={
                pickedDepartments.length
                  ? pickedDepartments.join(", ")
                  : tx("как есть")
              }
            />
            <SummaryRow
              label={tx("Разделы")}
              value={
                draft.sections.length
                  ? draft.sections
                      .map(
                        (id) =>
                          OPTIONAL_SECTIONS.find((x) => x.id === id)?.label ?? id,
                      )
                      .join(", ")
                  : tx("только ядро")
              }
            />
            <SummaryRow
              label={tx("Профили")}
              value={tx(
                VISIBILITY.find((x) => x.id === draft.profile_visibility)
                  ?.label ?? draft.profile_visibility,
              )}
            />
          </section>
        )}
      </div>

      <footer className="flex gap-2 border-t border-tg-secondary-bg px-4 py-3">
        <button
          type="button"
          disabled={step === 0 || save.isPending}
          aria-busy={save.isPending}
          onClick={() => void go(step - 1)}
          className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg text-sm text-tg-text disabled:opacity-40"
        >
          {tx("Назад")}
        </button>
        <button
          type="button"
          disabled={save.isPending}
          aria-busy={save.isPending}
          onClick={() => void (step === lastStep ? finish() : go(step + 1))}
          className="min-h-11 flex-[2] rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
        >
          {step === lastStep ? tx("Начать работу") : tx("Далее")}
        </button>
      </footer>
    </div>
  );
}

// --------------------------------------------------------------------------
// Варианты ответов
// --------------------------------------------------------------------------

const INDUSTRIES = [
  { id: "restaurant", label: "Ресторан" },
  { id: "cafe", label: "Кафе или кофейня" },
  { id: "salon", label: "Салон красоты" },
  { id: "autoservice", label: "Автосервис" },
  { id: "retail", label: "Магазин" },
  { id: "other", label: "Другое" },
];

const HEADCOUNTS = [
  { id: "up_to_10", label: "до 10 человек" },
  { id: "10_30", label: "10–30" },
  { id: "30_100", label: "30–100" },
  { id: "100_plus", label: "больше 100" },
];

const VISIBILITY = [
  {
    id: "colleagues",
    label: "Коллеги видят друг друга",
    hint: "Человек сам решает в профиле, открывать ли активность.",
  },
  {
    id: "managers",
    label: "Только руководители",
    hint: "Коллеги видят имя и отдел; цифры и история — у руководителя.",
  },
  {
    id: "all_open",
    label: "Всё открыто",
    hint: "Профили открыты всем и не закрываются. Обычно для прозрачной команды.",
  },
];

// --------------------------------------------------------------------------
// Мелкие элементы
// --------------------------------------------------------------------------

function Choice({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={[
        "min-h-11 rounded-tile px-3 text-xs transition-colors",
        active
          ? "bg-tg-link/15 font-medium text-tg-text"
          : "bg-tg-secondary-bg/60 text-tg-text",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

function Toggle({
  title,
  hint,
  value,
  onToggle,
}: {
  title: string;
  hint: string;
  value: boolean;
  onToggle: () => void;
}) {
  const { tx } = useTx();
  return (
    <div className="flex items-center gap-2 rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="min-w-0 flex-1">
        <div className="text-xs text-tg-text">{title}</div>
        <div className="mt-0.5 text-2xs text-tg-hint">{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={title}
        onClick={() => {
          haptic("light");
          onToggle();
        }}
        className={[
          "min-h-9 shrink-0 rounded-full px-3 text-xs transition-colors",
          value
            ? "bg-tg-button text-tg-button-text"
            : "bg-tg-bg/70 text-tg-hint",
        ].join(" ")}
      >
        {value ? tx("Да") : tx("Нет")}
      </button>
    </div>
  );
}

function CustomDepartment({ onAdd }: { onAdd: (name: string) => void }) {
  const { tx } = useTx();
  const [value, setValue] = useState("");
  const submit = () => {
    const name = value.trim();
    if (!name) return;
    haptic("light");
    onAdd(name);
    setValue("");
  };
  return (
    <div className="flex gap-1.5">
      <FormField
        id="org-custom-department"
        label={tx("Добавить своё подразделение")}
        labelClassName="sr-only"
        className="min-h-10 min-w-0 flex-1"
      >
        {(field) => (
          <input
            {...field}
            type="text"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              // §8 `ime-composition-enter`: Enter подтверждает выбор в китайской,
              // японской и корейской раскладке, а не отправляет форму. Без этой
              // проверки ввод «добавлял» недописанное подразделение.
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter") submit();
            }}
            maxLength={80}
            placeholder={tx("Своё подразделение")}
            className="h-full w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text placeholder:text-tg-hint"
          />
        )}
      </FormField>
      <button
        type="button"
        onClick={submit}
        disabled={!value.trim()}
        className="min-h-10 shrink-0 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-link disabled:opacity-40"
      >
        {tx("Добавить")}
      </button>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-tile bg-tg-secondary-bg/60 p-2">
      <div className="text-2xs text-tg-hint">{label}</div>
      <div className="mt-0.5 text-xs text-tg-text">{value}</div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Шаг «Люди»: приглашение первых сотрудников
// --------------------------------------------------------------------------

/**
 * Приглашение прямо в мастере.
 *
 * Зачем не «потом в админке». После настройки владелец остаётся один:
 * приложение настроено, а работать в нём некому, и следующая неделя уходит на
 * переписку «пришлите мне ссылку». Ссылка создаётся здесь же, почта
 * необязательна — в смене её чаще передают в мессенджере.
 */
function PeopleStep({
  positions,
  departments,
}: {
  positions: string[];
  departments: { id: number; name: string }[];
}) {
  const { tx } = useTx();
  const [email, setEmail] = useState("");
  const [position, setPosition] = useState<string | null>(null);
  const [departmentId, setDepartmentId] = useState<number | null>(
    departments[0]?.id ?? null,
  );
  const [created, setCreated] = useState<OrgInvitation[]>([]);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const invite = useMutation({
    mutationFn: () =>
      createInvitation({
        email: email.trim() || null,
        role: "staff",
        days: 7,
        position,
        department_id: departmentId,
      }),
    onSuccess: (data) => {
      setCreated((cur) => [...cur, data]);
      setEmail("");
      setCopied(false);
      setError(null);
      haptic("success");
    },
    onError: (err) => setError(humanizeApiError(err)),
  });

  const last = created[created.length - 1];

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-heading text-tg-text">
          {tx("Кого позвать первым?")}
        </h2>
        <p className="mt-1 text-xs text-tg-hint">
          {tx(
            "Сотрудник откроет ссылку и попадёт в вашу организацию. Почту можно не указывать — тогда передайте ссылку лично.",
          )}
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy"
        >
          {error}
        </div>
      )}

      <div className="flex gap-1.5">
        <FormField
          id="org-invite-email"
          label={tx("Почта (необязательно)")}
          labelClassName="sr-only"
          className="min-h-10 min-w-0 flex-1"
        >
          {(field) => (
            <input
              {...field}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              maxLength={120}
              placeholder={tx("Почта (необязательно)")}
              className="h-full w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text placeholder:text-tg-hint"
            />
          )}
        </FormField>
        <button
          type="button"
          disabled={invite.isPending}
          aria-busy={invite.isPending}
          onClick={() => invite.mutate()}
          className="min-h-10 shrink-0 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
        >
          {tx("Создать приглашение")}
        </button>
      </div>

      {positions.length > 0 && (
        <div>
          <div className="text-2xs font-medium uppercase tracking-wide text-tg-hint">
            {tx("Должность")}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {positions.map((item) => {
              const active = position === item;
              return (
                <button
                  key={item}
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    haptic("selection");
                    setPosition(active ? null : item);
                  }}
                  className={[
                    "inline-flex min-h-9 items-center gap-1 rounded-full px-3 text-xs transition-colors",
                    active
                      ? "bg-tg-link/15 font-medium text-tg-text"
                      : "bg-tg-secondary-bg text-tg-hint",
                  ].join(" ")}
                >
                  {item}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {departments.length > 0 && (
        <FormField id="org-invite-department" label={tx("Подразделение")}>
          {(field) => (
            <select
              {...field}
              value={departmentId ?? ""}
              onChange={(event) =>
                setDepartmentId(
                  event.target.value ? Number(event.target.value) : null,
                )
              }
              className="min-h-10 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
            >
              <option value="">{tx("Пока без подразделения")}</option>
              {departments.map((dep) => (
                <option key={dep.id} value={dep.id}>
                  {dep.name}
                </option>
              ))}
            </select>
          )}
        </FormField>
      )}

      {last?.link && (
        <div
          className="rounded-tile bg-tg-secondary-bg/60 p-2"
          data-testid="org-setup-invite-link"
        >
          <div className="text-2xs text-tg-hint">{tx("Ссылка-приглашение")}</div>
          <div className="mt-0.5 break-all text-xs text-tg-text">{last.link}</div>
          <button
            type="button"
            onClick={() => void copyLink()}
            className="mt-1 min-h-9 rounded-tile bg-tg-bg/70 px-3 text-xs text-tg-link"
          >
            {copied ? tx("Скопировано") : tx("Копировать")}
          </button>
        </div>
      )}

      {created.length > 0 && (
        <div className="text-2xs text-tg-hint">
          {tx("Приглашений создано: {n}", { n: created.length })}
        </div>
      )}
      <p className="rounded-tile bg-tg-secondary-bg/60 p-2 text-2xs text-tg-hint">
        {tx("Готовые приглашения всегда в разделе «Приглашения».")}
      </p>
    </section>
  );

  async function copyLink() {
    if (!last?.link) return;
    setCopied(await copyText(last.link));
  }
}

// --------------------------------------------------------------------------
// Шаг «График»: рабочая неделя одной настройкой
// --------------------------------------------------------------------------

const WEEK_PATTERNS = [
  { id: "5_2", code: "5/2", label: "Пять дней", workdays: [0, 1, 2, 3, 4] },
  { id: "6_1", code: "6/1", label: "Шесть дней", workdays: [0, 1, 2, 3, 4, 5] },
  {
    id: "7_0",
    code: "7/0",
    label: "Каждый день",
    workdays: [0, 1, 2, 3, 4, 5, 6],
  },
];

function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * Рабочая неделя без таблицы на сорок клеток.
 *
 * В мастер человек пришёл за «как у нас работает смена», а не за табель:
 * выбрать рисунок недели и часы дешевле, чем ставить каждому сотруднику
 * клетки — которых на этом шаге ещё и нет. Шаблон сохраняется на отдел, а
 * смены ставятся сразу, если люди уже пришли по ссылке; иначе шаблон ждёт их
 * в табеле и применяется одной кнопкой.
 */
function ScheduleStep({
  departments,
}: {
  departments: { id: number; name: string }[];
}) {
  const { tx } = useTx();
  const [patternId, setPatternId] = useState(WEEK_PATTERNS[0].id);
  const [startsAt, setStartsAt] = useState("09:00");
  const [endsAt, setEndsAt] = useState("18:00");
  const [departmentId, setDepartmentId] = useState<number | null>(
    departments[0]?.id ?? null,
  );
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pattern =
    WEEK_PATTERNS.find((item) => item.id === patternId) ?? WEEK_PATTERNS[0];

  const save = useMutation({
    mutationFn: async () => {
      const template = await saveShiftTemplate({
        // Имя без перевода: оно живёт в базе организации, а не на экране, и
        // при смене языка не должно превращаться в другой шаблон.
        name: `Смена ${pattern.code}`,
        department_id: departmentId,
        days: [0, 1, 2, 3, 4, 5, 6].map((weekday) =>
          pattern.workdays.includes(weekday)
            ? {
                weekday,
                status: "planned" as const,
                starts_at: startsAt,
                ends_at: endsAt,
              }
            : {
                weekday,
                status: "dayoff" as const,
                starts_at: null,
                ends_at: null,
              },
        ),
      });
      const week = await fetchShiftWeek(todayIso(), {
        days: 7,
        departmentId,
      });
      if (!week.people.length) return 0;
      const result = await applyShiftTemplate(template.id, {
        employee_ids: week.people.map((person) => person.employee_id),
        week_start: week.start,
        overwrite: false,
      });
      return result.saved;
    },
    onSuccess: (saved) => {
      setError(null);
      haptic("success");
      setNote(
        saved
          ? tx("Шаблон сохранён. Смены поставлены: {n}.", { n: saved })
          : tx("Шаблон сохранён. Поставим смены, когда появятся люди."),
      );
    },
    onError: (err) => setError(humanizeApiError(err)),
  });

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-heading text-tg-text">
          {tx("Рабочая неделя")}
        </h2>
        <p className="mt-1 text-xs text-tg-hint">
          {tx("Смены и часы можно поправить в табеле в любой момент.")}
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy"
        >
          {error}
        </div>
      )}

      <div className="grid grid-cols-3 gap-2">
        {WEEK_PATTERNS.map((item) => (
          <Choice
            key={item.id}
            label={tx(item.label)}
            active={item.id === patternId}
            onClick={() => {
              haptic("selection");
              setPatternId(item.id);
            }}
          />
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <FormField id="org-schedule-start" label={tx("Начало")}>
          {(field) => (
            <input
              {...field}
              type="time"
              value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)}
              className="min-h-10 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
            />
          )}
        </FormField>
        <FormField id="org-schedule-end" label={tx("Конец")}>
          {(field) => (
            <input
              {...field}
              type="time"
              value={endsAt}
              onChange={(event) => setEndsAt(event.target.value)}
              className="min-h-10 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
            />
          )}
        </FormField>
      </div>

      {departments.length > 0 && (
        <FormField id="org-schedule-department" label={tx("Подразделение")}>
          {(field) => (
            <select
              {...field}
              value={departmentId ?? ""}
              onChange={(event) =>
                setDepartmentId(
                  event.target.value ? Number(event.target.value) : null,
                )
              }
              className="min-h-10 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
            >
              <option value="">{tx("Все подразделения")}</option>
              {departments.map((dep) => (
                <option key={dep.id} value={dep.id}>
                  {dep.name}
                </option>
              ))}
            </select>
          )}
        </FormField>
      )}

      <button
        type="button"
        disabled={save.isPending}
        aria-busy={save.isPending}
        onClick={() => save.mutate()}
        className="min-h-11 w-full rounded-tile bg-tg-secondary-bg text-sm font-medium text-tg-text disabled:opacity-50"
      >
        {tx("Сохранить шаблон недели")}
      </button>

      {note && (
        <div
          className="rounded-tile bg-status-free/10 p-2 text-xs text-tg-text"
          data-testid="org-setup-schedule-done"
        >
          {note}
        </div>
      )}
    </section>
  );
}
