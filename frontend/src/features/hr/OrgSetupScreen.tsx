import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDepartments,
  saveOrgSetup,
  type OrgSetup,
  type OrgSetupPatch,
  type OrgProfileVisibility,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import Icon from "@/components/Icon";
import ProgressBar from "@/components/ProgressBar";
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
 */
export default function OrgSetupScreen({
  setup,
  onClose,
}: {
  setup: OrgSetup;
  onClose: () => void;
}) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<OrgSetup>(setup);
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
    () => setup.departments,
  );

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
    tx("Разделы"),
    tx("Кто что видит"),
    tx("Готово"),
  ];

  const toggleSection = (id: string) => {
    haptic("selection");
    setDraft((cur) => ({
      ...cur,
      sections: cur.sections.includes(id)
        ? cur.sections.filter((x) => x !== id)
        : [...cur.sections, id],
    }));
  };

  const patchForStep = (target: number): OrgSetupPatch => {
    switch (target) {
      case 0:
        return { industry: draft.industry, headcount: draft.headcount };
      case 1:
        return { departments: pickedDepartments, create_departments: true };
      case 2:
        return { sections: draft.sections };
      case 3:
        return {
          profile_visibility: draft.profile_visibility,
          cross_department_watch: draft.cross_department_watch,
          allow_hide_last_seen: draft.allow_hide_last_seen,
          allow_hide_media: draft.allow_hide_media,
        };
      default:
        return {};
    }
  };

  const go = async (target: number) => {
    haptic("light");
    setError(null);
    if (target <= 4) {
      try {
        await save.mutateAsync(patchForStep(Math.min(target, 3)));
      } catch {
        return; // ошибка уже в состоянии мутации и на экране
      }
    }
    setStep(Math.max(0, Math.min(4, target)));
  };

  const finish = async () => {
    haptic("success");
    try {
      const data = await save.mutateAsync({ ...patchForStep(3), done: true });
      qc.setQueryData(["org-setup"], data);
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
              <Icon name="admin" size={16} />
              {tx("Настроим под вас")}
            </div>
            <div className="text-xs text-tg-hint">
              {tx("Шаг {step} из {total}: {title}", {
                step: step + 1,
                total: steps.length,
                title: steps[step],
              })}
            </div>
          </div>
          <button
            type="button"
            onClick={skip}
            disabled={save.isPending}
            className="min-h-9 shrink-0 rounded-tile px-2 text-xs text-tg-link disabled:opacity-50"
          >
            {tx("Пропустить")}
          </button>
        </div>
        <div className="mt-2">
          <ProgressBar value={step + 1} total={steps.length} size="sm" />
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {error && (
          <div className="mb-3 rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
            <Icon name="alert" size={13} className="mr-1 inline-block" />
            {error}
          </div>
        )}

        {step === 0 && (
          <section className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-tg-text">
                {tx("Что у вас за предприятие?")}
              </h2>
              <p className="mt-1 text-xs text-tg-hint">
                {tx("От этого зависят подсказки по подразделениям и акценты в приложении.")}
              </p>
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
              <h2 className="text-sm font-semibold text-tg-text">
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
              <h2 className="text-sm font-semibold text-tg-text">
                {tx("Из кого состоит команда?")}
              </h2>
              <p className="mt-1 text-xs text-tg-hint">
                {tx("Выберите отделы — они появятся в приложении. Свои можно добавить позже в админке.")}
              </p>
            </div>
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
          <section className="space-y-2">
            <div>
              <h2 className="text-sm font-semibold text-tg-text">
                {tx("Какие разделы оставить?")}
              </h2>
              <p className="mt-1 text-xs text-tg-hint">
                {tx("События, задачи, чек-лист и профиль остаются всегда — это ядро смены.")}
              </p>
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

        {step === 3 && (
          <section className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold text-tg-text">
                {tx("Кто что видит")}
              </h2>
              <p className="mt-1 text-xs text-tg-hint">
                {tx("Правила действуют сразу и для всех: их проверяет сервер, а не только интерфейс.")}
              </p>
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

        {step === 4 && (
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
              <p className="mt-1 text-xs text-tg-hint">
                {tx("Настройку можно поменять позже — в профиле, «Настройка организации».")}
              </p>
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
          onClick={() => void go(step - 1)}
          className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg text-sm text-tg-text disabled:opacity-40"
        >
          {tx("Назад")}
        </button>
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => void (step === 4 ? finish() : go(step + 1))}
          className="min-h-11 flex-[2] rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
        >
          {step === 4 ? tx("Начать работу") : tx("Далее")}
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
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") submit();
        }}
        maxLength={80}
        placeholder={tx("Своё подразделение")}
        aria-label={tx("Добавить своё подразделение")}
        className="min-h-10 min-w-0 flex-1 rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text placeholder:text-tg-hint"
      />
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
