import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  TASK_MODE_LABEL,
  fetchChecklist,
  fetchEmployee,
  attachTaskPhoto,
  fetchTasks,
  isTaskClosedForMe,
  ownTaskStatus,
  reportTaskIssue,
  runTaskAction,
  type HrTask,
  type TaskAction,
  type TaskStatus,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import { useAppText } from "@/api/texts";
import type { MediaItem } from "@/api/media";
import Icon, { InlineIcon } from "@/components/Icon";
import PhotoAttach, { PhotoThumbs } from "@/components/PhotoAttach";
import { fetchIssues } from "@/api/issues";
import Badge from "@/features/hr/Badge";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { tx, useTx, type Locale } from "@/i18n";
import { useUI } from "@/store/ui";

/**
 * SemiTaskBot: «Мои задачи» — главный экран смены.
 *
 * Здесь только личные поручения (scope=employee + поручения своего
 * подразделения): сервер сам решает, что показывать, поэтому экран не
 * фильтрует данные повторно и не имеет доступа к чужим задачам.
 *
 * Порядок действий: принять → начать → выполнить. «Не успеваю» открывает
 * встроенную форму причины: она не отменяет поручение, а отправляет
 * руководителю объяснение (и, если указан новый срок, запускает отсчёт заново).
 */

const STATUS_LABEL: Record<TaskStatus, string> = {
  new: "Новое",
  accepted: "Принято",
  in_progress: "В работе",
  on_review: "На проверке",
  rework: "На доработке",
  done: "Выполнено",
  overdue: "Просрочено",
  failed: "Не выполнено",
};

const STATUS_CLASS: Record<TaskStatus, string> = {
  new: "bg-tg-link/15 text-tg-link",
  accepted: "bg-tg-link/15 text-tg-link",
  in_progress: "bg-status-maybe/20 text-status-maybe",
  on_review: "bg-tg-link/15 text-tg-link",
  rework: "bg-status-busy/20 text-status-busy",
  done: "bg-status-free/20 text-status-free",
  overdue: "bg-status-busy/20 text-status-busy",
  failed: "bg-status-busy/20 text-status-busy",
};

/** «смена 14.05» из ISO-даты смены. */
function fmtShift(iso: string | null): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}.${m}` : null;
}

const PRIORITY_LABEL: Record<HrTask["priority"], string> = {
  low: "низкий",
  normal: "обычный",
  high: "высокий",
};

const ISSUE_REASONS: { code: string; label: string }[] = [
  { code: "no_time", label: "Не хватает времени" },
  { code: "need_help", label: "Нужна помощь" },
  { code: "no_materials", label: "Нет материалов/доступа" },
  { code: "equipment", label: "Оборудование не работает" },
  { code: "other", label: "Другое" },
];

/** «Сегодня 18:00», «Завтра 09:30», иначе «14.05 18:00». */
function fmtDue(iso: string | null, locale: Locale): string {
  if (!iso) return tx(locale, "без срока");
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return tx(locale, "без срока");
  const time = d.toLocaleTimeString(locale === "en" ? "en-GB" : "ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    // Секунды показываем только когда они реально заданы: в обычном
    // «до 18:00» они не мешают, а точный срок не теряет информацию.
    ...(d.getSeconds() ? { second: "2-digit" as const } : {}),
  });
  const today = new Date();
  const dayOf = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((dayOf(d) - dayOf(today)) / 86_400_000);
  if (diff === 0) return tx(locale, "сегодня {time}", { time });
  if (diff === 1) return tx(locale, "завтра {time}", { time });
  if (diff === -1) return tx(locale, "вчера {time}", { time });
  const day = d.toLocaleDateString(locale === "en" ? "en-GB" : "ru-RU", {
    day: "2-digit",
    month: "2-digit",
  });
  return `${day} ${time}`;
}

export default function MyTasksScreen() {
  const { tx } = useTx();
  const qc = useQueryClient();
  const setTab = useUI((s) => s.setTab);
  const [showClosed, setShowClosed] = useState(false);
  const [issueFor, setIssueFor] = useState<number | null>(null);
  // Подписи пустого состояния меняет управляющий (админка → «Тексты»).
  const emptyTitle = useAppText("tasks.empty.title", "На сегодня всё");
  const emptyHint = useAppText(
    "tasks.empty.hint",
    "Задач нет — можно проверить чек-лист смены.",
  );

  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const tasksQ = useQuery({
    queryKey: ["hr-tasks", showClosed],
    queryFn: () => fetchTasks(showClosed),
  });
  // Личная панель отвечает «что делать сейчас», поэтому прогресс смены
  // подтягивается сюда же: без него главный экран не знал, открыта ли смена.
  const checklistQ = useQuery({
    queryKey: ["hr-checklist"],
    queryFn: () => fetchChecklist(),
    staleTime: 30_000,
  });
  // Значимые проблемы и напоминания — четвёртый пункт личной панели: открытые
  // карточки журнала, которые сейчас висят (свои или по подразделению).
  const issuesQ = useQuery({
    queryKey: ["hr-issues", "panel"],
    queryFn: () => fetchIssues({ statuses: ["open", "in_progress"], limit: 1 }),
    staleTime: 60_000,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["hr-tasks"] });
    void qc.invalidateQueries({ queryKey: ["hr-feed"] });
  };

  const action = useMutation({
    mutationFn: ({ id, act }: { id: number; act: TaskAction }) =>
      runTaskAction(id, act),
    onSuccess: () => {
      haptic("light");
      invalidate();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  if (meQ.isError)
    return <ErrorState error={meQ.error} onRetry={() => void meQ.refetch()} />;
  if (tasksQ.isError)
    return (
      <ErrorState error={tasksQ.error} onRetry={() => void tasksQ.refetch()} />
    );

  const tasks = tasksQ.data ?? [];
  const checklist = checklistQ.data;
  const issues = issuesQ.data?.summary;
  const openIssues = issues?.total_open ?? 0;
  const urgentIssues = issues?.attention ?? 0;
  const firstName = (meQ.data?.display_name ?? "")
    .replace("[BOT]", "")
    .trim()
    .split(" ")[0];
  const shiftPercent =
    checklist && checklist.total > 0
      ? Math.round((100 * checklist.done) / checklist.total)
      : 0;
  // «Активные» считаем по своему статусу: в режиме «каждый сам» задача ещё
  // открыта для коллег, хотя я свою часть уже закрыл. `on_review` тоже
  // активна: работа сдана, но пока не принята — это ещё не закрыто.
  const open = tasks.filter((t) => !isTaskClosedForMe(t));
  const overdue = open.filter((t) => t.is_overdue).length;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          {/* VISUAL_AUDIT P3.17: плашка стояла в одной строке с приветствием.
              На узком экране (и при крупном системном шрифте) три кнопки +
              «🛠 Разработчик» съедали всю ширину, и вместо имени оставалось
              «Привет,…». Теперь приветствие — своя строка, плашка — под ним. */}
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-semibold leading-tight text-tg-text">
              {firstName ? tx("Привет, {name}", { name: firstName }) : tx("Мои задачи")}
            </h1>
            {meQ.data && (
              <div className="mt-1 flex min-w-0">
                <Badge
                  text={meQ.data.badge}
                  emoji={meQ.data.badge_emoji}
                  demo={meQ.data.is_demo}
                />
              </div>
            )}
          </div>
          <span className="flex shrink-0 items-center gap-1.5">
            {/* «Спросить» в шапке смены: вопрос возникает в работе, а не в
                профиле, поэтому вход должен быть здесь. */}
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setTab("ask");
              }}
              className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg text-tg-text leading-none"
              aria-label={tx("Спросить: поиск по инструкциям")}
              title={tx("Спросить: поиск по инструкциям")}
            >
              <Icon name="search" size={18} />
            </button>
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setTab("standards");
              }}
              className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg text-tg-text leading-none"
              aria-label={tx("База стандартов")}
              title={tx("База стандартов")}
            >
              <Icon name="book" size={18} />
            </button>
            {meQ.data?.is_aup && (
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  setTab("review");
                }}
                className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg text-tg-text leading-none"
                aria-label={tx("Приёмка работ")}
                title={tx("Приёмка работ")}
              >
                <Icon name="search" size={18} />
              </button>
            )}
            {/* Конец смены начинается здесь: сдача того, что осталось. */}
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setTab("handovers");
              }}
              className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg text-tg-text leading-none"
              aria-label={tx("Передача смены")}
              title={tx("Передача смены")}
            >
              <Icon name="send" size={18} />
            </button>
          </span>
        </div>
        <p className="mt-1 text-xs text-tg-hint">
          {tx("Что нужно сделать сегодня")}
          {open.length > 0
            ? ` · ${tx("задач {count}", { count: open.length })}${overdue ? `, ${tx("просрочено {count}", { count: overdue })}` : ""}`
            : ""}
        </p>
        <div className="mt-3 flex items-center gap-1.5">
          {[
            { v: false, label: tx("Активные") },
            { v: true, label: tx("Все") },
          ].map((o) => (
            <button
              key={String(o.v)}
              type="button"
              onClick={() => {
                haptic("light");
                setShowClosed(o.v);
              }}
              className={[
                "min-h-11 rounded-full px-3 text-xs transition-colors",
                // P3.16: выбранный фильтр — не главная кнопка экрана. Заливка
                // `bg-tg-button` остаётся за действием («Продолжить чек-лист»).
                // Текст нейтральный, а не `text-tg-link`: на 15%-подложке
                // ссылочный цвет даёт 3.1:1 — ниже AA для 12px.
                showClosed === o.v
                  ? "bg-tg-link/15 font-medium text-tg-text"
                  : "bg-tg-secondary-bg text-tg-hint",
              ].join(" ")}
            >
              {o.label}
            </button>
          ))}
          {/* Журнал проблем не в нижней полосе: проблем меньше, чем задач, и
              заводить их бегут именно отсюда. */}
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setTab("issues");
            }}
            className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-full bg-tg-secondary-bg px-2.5 text-xs text-tg-hint"
          >
            <Icon name="alert" size={14} />
            {tx("Проблемы")}
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {checklist && checklist.total > 0 && (
          <section className="rounded-card bg-tg-secondary-bg/60 p-3">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-tg-text">{tx("Смена сегодня")}</span>
              <span className="text-xs tabular-nums text-tg-hint">
                {checklist.done}/{checklist.total}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-tg-bg">
              <div
                className="h-full rounded-full bg-tg-link"
                style={{ width: `${shiftPercent}%` }}
              />
            </div>
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setTab("checklist");
              }}
              className="mt-2 min-h-11 rounded-full bg-tg-bg px-3 text-xs text-tg-link"
            >
              {checklist.status === "done" ? tx("Смена закрыта") : tx("Открыть чек-лист")}
            </button>
          </section>
        )}

        {/* Проблемы, которые сейчас висят: личная панель не должна говорить
            «всё сделано», если рядом лежит просроченная карточка. */}
        {openIssues > 0 && (
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setTab("issues");
            }}
            className="w-full rounded-card bg-tg-secondary-bg/60 p-3 text-left"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-tg-text">
                <Icon name="alert" size={15} />
                {tx("Проблемы")}
              </span>
              <span className="text-xs tabular-nums text-tg-hint">
                {tx("открыто {count}", { count: openIssues })}
              </span>
            </div>
            <p className="mt-1 text-xs text-tg-hint">
              {urgentIssues > 0
                ? tx("{count} ждут внимания: срок или повтор.", { count: urgentIssues })
                : tx("Все в работе — открой журнал, если нужен статус.")}
            </p>
          </button>
        )}

        {/* На широком экране карточки идут двумя колонками: на ПК список
            из трёх поручений растягивался на 1000px одной узкой лентой. */}
        <div className="space-y-3 xl:grid xl:grid-cols-2 xl:items-start xl:gap-3 xl:space-y-0">
        {tasksQ.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {!tasksQ.isLoading && tasks.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 text-center xl:col-span-2">
            <Icon name="check" size={30} className="text-tg-hint" />
            <div className="mt-2 text-sm font-medium text-tg-text">
              {tx(emptyTitle)}
            </div>
            <div className="mt-1 text-xs text-tg-hint">{tx(emptyHint)}</div>
            {/* VISUAL_AUDIT P2.12: пустое состояние ведёт к главному делу смены,
                а не в «События» — они и так есть в нижней полосе. */}
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setTab("checklist");
              }}
              className="mt-3 min-h-11 rounded-full bg-tg-button px-4 text-xs text-tg-button-text"
            >
              {checklist && checklist.status === "done"
                ? tx("Посмотреть чек-лист")
                : checklist && checklist.total > 0
                  ? checklist.done > 0
                    ? tx("Продолжить чек-лист")
                    : tx("Начать смену")
                  : tx("Открыть чек-лист")}
            </button>
          </div>
        )}

        {tasks.map((t) => (
          <TaskCard
            key={t.id}
            task={t}
            busy={action.isPending}
            issueOpen={issueFor === t.id}
            onToggleIssue={() => {
              haptic("light");
              setIssueFor(issueFor === t.id ? null : t.id);
            }}
            onAction={(act) => action.mutate({ id: t.id, act })}
            onIssued={() => {
              setIssueFor(null);
              invalidate();
            }}
          />
        ))}
        </div>
      </div>
    </div>
  );
}

function TaskCard({
  task,
  busy,
  issueOpen,
  onToggleIssue,
  onAction,
  onIssued,
}: {
  task: HrTask;
  busy: boolean;
  issueOpen: boolean;
  onToggleIssue: () => void;
  onAction: (a: TaskAction) => void;
  onIssued: () => void;
}) {
  const { tx, locale } = useTx();
  const status = ownTaskStatus(task);
  const closed = status === "done" || status === "failed";
  const shift = fmtShift(task.shift_date);
  const group = task.progress_total > 1;
  // Поручение «по четвергам» в среду остаётся в списке, но помечено: работа
  // не сегодня. Скрывать его целиком было бы хуже — человек ищет его глазами.
  const offSchedule = task.active_today === false && !closed;
  return (
    <article
      className={[
        "rounded-card p-3",
        offSchedule ? "bg-tg-secondary-bg/30" : "bg-tg-secondary-bg/60",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold text-tg-text break-words">
          {task.title}
        </h2>
        <span
          className={[
            "shrink-0 rounded-full px-2 py-0.5 text-xs",
            STATUS_CLASS[status],
          ].join(" ")}
        >
          {tx(STATUS_LABEL[status])}
        </span>
      </div>

      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-tg-hint">
        <span>
          <InlineIcon name="clock" />
          {fmtDue(task.due_at, locale)}
        </span>
        {shift && (
          <span>
            <InlineIcon name="calendar" />
            {tx("смена {date}", { date: shift })}
          </span>
        )}
        {task.schedule_label && (
          <span>
            <InlineIcon name="calendar" />
            {offSchedule ? tx("не сегодня · {label}", { label: task.schedule_label }) : task.schedule_label}
          </span>
        )}
        {task.priority !== "normal" && (
          <span>{tx("приоритет: {label}", { label: tx(PRIORITY_LABEL[task.priority]) })}</span>
        )}
        {task.requires_photo && (
          <span>
            <InlineIcon name="camera" />
            {(task.photos?.length ?? 0) > 0 ? tx("фото есть") : tx("нужен фотоотчёт")}
          </span>
        )}
        {task.requires_review && (
          <span>
            <InlineIcon name="checklist" />{" "}{tx("с приёмкой")}
          </span>
        )}
        {task.is_overdue && !closed && (
          <span className="text-status-busy">{tx("просрочено")}</span>
        )}
      </div>

      {group && (
        <div className="mt-1.5 text-xs text-tg-hint">
          <InlineIcon name="team" />
          {tx(TASK_MODE_LABEL[task.mode])} ·{" "}
          {tx("сделали {done} из {total}", {
            done: task.progress_done,
            total: task.progress_total,
          })}
        </div>
      )}
      {task.my_part && (
        <div className="mt-1 text-xs text-tg-text/90">
          {tx("Моя часть:")} {task.my_part}
        </div>
      )}

      {task.description && (
        <p className="mt-2 text-xs text-tg-text/90 whitespace-pre-wrap break-words">
          {task.description}
        </p>
      )}
      {task.expected_result && (
        <p className="mt-1 text-xs text-tg-hint">
          <span className="text-tg-hint/80">{tx("Результат:")} </span>
          {task.expected_result}
        </p>
      )}

      <TaskPhotos task={task} closed={closed} />

      {!closed && status === "on_review" && (
        <div className="mt-3 rounded-tile bg-tg-bg/60 px-2.5 py-2 text-xs text-tg-hint">
          {tx("Работа сдана — ждёт приёмки руководителя.")}
        </div>
      )}

      {!closed && status !== "on_review" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {status === "new" && (
            <ActionButton disabled={busy} onClick={() => onAction("accept")}>
              {tx("Принять")}
            </ActionButton>
          )}
          {(status === "new" ||
            status === "accepted" ||
            status === "rework") && (
            <ActionButton disabled={busy} onClick={() => onAction("start")}>
              {status === "rework" ? tx("Взять в работу") : tx("Начать")}
            </ActionButton>
          )}
          {(status === "in_progress" ||
            status === "overdue" ||
            status === "rework") && (
            <ActionButton disabled={busy} onClick={() => onAction("done")}>
              {task.requires_review ? tx("Сдать на проверку") : tx("Выполнено")}
            </ActionButton>
          )}
          <ActionButton disabled={busy} variant="ghost" onClick={onToggleIssue}>
            {issueOpen ? tx("Отмена") : tx("Не успеваю")}
          </ActionButton>
        </div>
      )}


      {closed && task.done_at && (
        <div className="mt-2 text-xs text-tg-hint">
          Закрыто: {new Date(task.done_at).toLocaleString("ru-RU")}
        </div>
      )}

      {issueOpen && <IssueForm taskId={task.id} onDone={onIssued} />}
    </article>
  );
}

/**
 * Фотоотчёт в карточке поручения.
 *
 * Если требуется снимок, а его ещё нет — вместо бесполезной кнопки
 * «Выполнено» (сервер всё равно ответит `photo_report_required`) показываем
 * камеру: снимок сам закроет поручение. Загруженные фото видны сразу.
 */
function TaskPhotos({ task, closed }: { task: HrTask; closed: boolean }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const photos = task.photos ?? [];
  const needsPhoto = task.requires_photo && photos.length === 0 && !closed;

  const attach = useMutation({
    mutationFn: (media: MediaItem) => attachTaskPhoto(task.id, media.id),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["hr-tasks"] });
      void qc.invalidateQueries({ queryKey: ["hr-feed"] });
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <>
      <PhotoThumbs photos={photos} />
      {!closed && (
        <div className="mt-2">
          {needsPhoto && (
            <div className="mb-1 text-xs text-tg-hint">
              <InlineIcon name="camera" />
              {tx("Фотоотчёт: сними или выбери фото — поручение закроется само.")}
            </div>
          )}
          <PhotoAttach
            compact
            label={tx("Добавить фото")}
            disabled={attach.isPending}
            onUploaded={(media) => attach.mutate(media)}
          />
        </div>
      )}
    </>
  );
}

function IssueForm({ taskId, onDone }: { taskId: number; onDone: () => void }) {
  const { tx } = useTx();
  const [reason, setReason] = useState(ISSUE_REASONS[0].code);
  const [comment, setComment] = useState("");
  const [eta, setEta] = useState("");

  const m = useMutation({
    mutationFn: () =>
      reportTaskIssue(taskId, {
        reason_code: reason,
        comment: comment.trim() || null,
        eta_at: eta ? new Date(eta).toISOString() : null,
      }),
    onSuccess: () => {
      haptic("success");
      void showAlert(
        tx("Руководителю отправлено объяснение. Срок отсчитывается заново."),
      );
      onDone();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <div className="mt-3 rounded-tile bg-tg-bg/60 p-3">
      <label className="block text-xs text-tg-hint">
        {tx("Причина")}
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-1 min-h-10 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
        >
          {ISSUE_REASONS.map((r) => (
            <option key={r.code} value={r.code}>
              {tx(r.label)}
            </option>
          ))}
        </select>
      </label>

      <label className="mt-2 block text-xs text-tg-hint">
        {tx("Когда сможешь закончить (необязательно)")}
        <input
          type="datetime-local"
          value={eta}
          onChange={(e) => setEta(e.target.value)}
          className="mt-1 min-h-10 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
        />
      </label>

      <label className="mt-2 block text-xs text-tg-hint">
        {tx("Комментарий")}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          maxLength={500}
          placeholder={tx("Что именно мешает?")}
          className="mt-1 w-full rounded-tile bg-tg-secondary-bg p-2 text-sm text-tg-text"
        />
      </label>

      <button
        type="button"
        disabled={m.isPending}
        onClick={() => m.mutate()}
        className="mt-3 min-h-10 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
      >
        {tx("Отправить руководителю")}
      </button>
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  variant = "primary",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={[
        "min-h-10 rounded-tile px-3 text-xs font-medium transition-transform active:scale-[0.98] disabled:opacity-50",
        variant === "primary"
          ? "bg-tg-button text-tg-button-text"
          : "bg-tg-secondary-bg text-tg-text",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
