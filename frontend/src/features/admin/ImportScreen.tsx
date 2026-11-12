/**
 * Импорт людей и графика из таблицы (B2B_PLATFORM_PLAN, шаг 6.3).
 *
 * Зачем экран. Первый день клиента — это двадцать человек и неделя смен.
 * Пока импорта не было, их заводили руками мы, то есть продукт требовал
 * нашего времени при каждом внедрении. Здесь три шага: выбрать файл, увидеть
 * разбор, подтвердить.
 *
 * Почему предпросмотр отдельно от применения, а не «загрузить сразу».
 * Таблица из Excel приходит с чужими колонками, пустыми строками и лишними
 * людьми из прошлого сезона. Импорт без показа — лотерея: результат видно
 * только в пуле, и разбирать его там дороже, чем здесь.
 *
 * Почему можно вставить текст, а не только выбрать файл. Из Google Sheets и
 * из открытого CSV в буфере тот, кто правит таблицу, чаще всего копирует
 * строки, а не сохраняет файл. Одно поле `textarea` убирает этот шаг.
 */
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import FormField from "@/components/FormField";
import { Spinner } from "@/components/Spinner";
import {
  applyImport,
  previewImport,
  sampleCsv,
  type ImportKind,
  type ImportPreview,
  type ImportResult,
} from "@/api/imports";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";

/** Коды отказа целиком → текст. Их немного, и они стабильны. */
const PROBLEM_TEXT: Record<string, string> = {
  empty_file: "Файл пустой — вставьте строки из таблицы.",
  file_too_large: "Файл больше 500 КБ: для переноса базы нужен другой путь.",
  no_rows: "В файле только заголовок — нет ни одной строки данных.",
  too_many_rows: "В файле больше 500 строк. Разделите его на части.",
  bad_kind: "Неизвестный тип импорта.",
  no_name_column: "Нет колонки с именем (ожидается «Имя» или «Name»).",
  no_date_column: "Нет колонки с датой (ожидается «Дата» или «Date»).",
  no_person_column: "Нет колонки с сотрудником (имя или telegram_id).",
  import_failed: "Файл не разобрался. Проверьте, что это CSV с заголовком.",
};

const MAX_BYTES = 500_000;
const VISIBLE_ROWS = 60;

/** jsdom и старые WebView могут не иметь `File.text()` — читаем через reader. */
async function readText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file, "utf-8");
  });
}

const ACTION_LABEL: Record<string, string> = {
  create: "Создать",
  update: "Перезаписать",
  skip: "Пропустить",
  error: "Ошибка",
};

const ACTION_CLASS: Record<string, string> = {
  create: "bg-tg-link/15 text-tg-link",
  update: "bg-amber-500/15 text-amber-600",
  skip: "bg-tg-secondary-bg text-tg-hint",
  error: "bg-red-500/15 text-red-600",
};

export default function ImportScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const [kind, setKind] = useState<ImportKind>("people");
  const [text, setText] = useState("");
  const [filename, setFilename] = useState<string | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Два разных ожидания: «разбираем» и «пишем». Общий `busy` гасил обе
  // кнопки, но вторая при этом молчала — человек не понимал, идёт ли импорт.
  const [checking, setChecking] = useState(false);
  const [applying, setApplying] = useState(false);

  const reset = () => {
    setPreview(null);
    setResult(null);
    setProblem(null);
  };

  const pickKind = (next: ImportKind) => {
    if (next === kind) return;
    haptic("selection");
    setKind(next);
    reset();
  };

  const onFile = async (file: File | null | undefined) => {
    if (!file) return;
    reset();
    if (file.size > MAX_BYTES) {
      setProblem(PROBLEM_TEXT.file_too_large);
      return;
    }
    setFilename(file.name);
    try {
      setText(await readText(file));
    } catch {
      setProblem("Файл не прочитался. Сохраните его как CSV UTF-8 и повторите.");
    }
  };

  const check = async () => {
    if (!text.trim()) {
      setProblem("Сначала выберите файл или вставьте строки таблицы.");
      return;
    }
    setBusy(true);
    setChecking(true);
    setProblem(null);
    setResult(null);
    try {
      setPreview(
        await previewImport({ text, filename, kind, overwrite }),
      );
    } catch (error) {
      setPreview(null);
      const detail = error instanceof ApiError ? error.detail : "";
      setProblem(PROBLEM_TEXT[detail] ?? "Не удалось разобрать файл.");
    } finally {
      setChecking(false);
      setBusy(false);
    }
  };

  const run = async () => {
    setBusy(true);
    setApplying(true);
    setProblem(null);
    try {
      const done = await applyImport({ text, filename, kind, overwrite });
      setResult(done);
      setPreview(null);
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["employees-pool"] });
      void qc.invalidateQueries({ queryKey: ["shifts"] });
      void qc.invalidateQueries({ queryKey: ["admin"] });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : "";
      setProblem(PROBLEM_TEXT[detail] ?? "Импорт не применился. Попробуйте ещё раз.");
    } finally {
      setApplying(false);
      setBusy(false);
    }
  };

  const download = () => {
    const blob = new Blob([`\ufeff${sampleCsv(kind)}`], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = kind === "people" ? "people.csv" : "shifts.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  const createCount = preview?.create ?? 0;
  const updateCount = preview?.update ?? 0;
  const willWrite = createCount + updateCount;

  return (
    <SubScreen
      title={tx("Импорт из таблицы")}
      subtitle={tx("Люди и график из CSV — без ручного заведения")}
      onBack={onBack}
    >
      <div className="flex gap-2" role="tablist" aria-label={tx("Что импортируем")}>
        {(
          [
            ["people", tx("Люди")],
            ["shifts", tx("График")],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={kind === id}
            onClick={() => pickKind(id)}
            className={[
              "min-h-10 flex-1 rounded-tile text-sm font-medium press",
              kind === id
                ? "bg-tg-link text-white"
                : "bg-tg-secondary-bg text-tg-text",
            ].join(" ")}
          >
            {label}
          </button>
        ))}
      </div>

      <p className="text-xs text-tg-hint">
        {kind === "people"
          ? tx(
              "Колонки: имя, должность, подразделение, роль, telegram_id. Обязательна только «имя». Подразделение должно уже существовать.",
            )
          : tx(
              "Колонки: имя (или telegram_id), дата, статус, начало, конец. Люди должны быть заведены заранее — сначала импорт людей.",
            )}
      </p>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="min-h-10 rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text press"
        >
          {tx("Выбрать файл")}
        </button>
        <button
          type="button"
          onClick={download}
          className="min-h-10 rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-link press"
        >
          {tx("Скачать пример")}
        </button>
        <input
          aria-label={tx("Файл CSV")}
          ref={fileRef}
          type="file"
          accept=".csv,text/csv,text/plain"
          data-testid="import-file"
          className="hidden"
          onChange={(event) => void onFile(event.target.files?.[0])}
        />
        {filename && (
          <span className="self-center truncate text-xs text-tg-hint">
            {filename}
          </span>
        )}
      </div>

      <FormField
        id="import-text"
        label={tx("Или вставьте строки из таблицы (первая строка — заголовки)")}
      >
        {(field) => (
          <textarea
            {...field}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              reset();
            }}
            rows={5}
            spellCheck={false}
            data-testid="import-text"
            placeholder={"имя;должность;подразделение\nСергей;Управляющий;Зал"}
            className="w-full rounded-tile bg-tg-secondary-bg p-3 font-mono text-xs text-tg-text placeholder:text-tg-hint"
          />
        )}
      </FormField>

      {kind === "shifts" && (
        <label className="flex items-center gap-2 text-sm text-tg-text">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(event) => {
              setOverwrite(event.target.checked);
              setPreview(null);
              setResult(null);
            }}
          />
          {tx("Перезаписать смены, которые уже стоят")}
        </label>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void check()}
          disabled={busy}
          aria-busy={checking}
          className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg text-sm font-medium text-tg-text press disabled:opacity-50"
        >
          {checking ? (
            <span className="inline-flex items-center justify-center gap-1.5">
              <Spinner size={14} />
              {tx("Проверяем…")}
            </span>
          ) : (
            tx("Проверить")
          )}
        </button>
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy || !preview || willWrite === 0}
          aria-busy={applying}
          data-testid="import-apply"
          className="min-h-11 flex-1 rounded-tile bg-tg-link text-sm font-medium text-white press disabled:opacity-50"
        >
          {applying ? (
            <span className="inline-flex items-center justify-center gap-1.5">
              <Spinner size={14} />
              {tx("Импортируем…")}
            </span>
          ) : (
            <>
              {tx("Импортировать")} {willWrite > 0 ? willWrite : ""}
            </>
          )}
        </button>
      </div>

      {problem && (
        <div
          role="alert"
          className="rounded-tile bg-red-500/10 p-3 text-sm text-red-600"
        >
          {problem}
        </div>
      )}

      {preview && (
        <div className="space-y-3" data-testid="import-preview">
          <div className="rounded-tile bg-tg-secondary-bg/60 p-3 text-sm text-tg-text">
            <div>
              {tx("Строк: {count}", { count: preview.total })} ·{" "}
              {tx("создать")} {preview.create} · {tx("пропустить")}{" "}
              {preview.skip} · {tx("ошибок")} {preview.error}
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              {tx("Разделитель: {value}", {
                value: preview.delimiter === "\t" ? "табуляция" : preview.delimiter,
              })}
              {preview.departments.length > 0 && (
                <>
                  {" · "}
                  {tx("Подразделения: {value}", {
                    value: preview.departments.join(", "),
                  })}
                </>
              )}
            </div>
          </div>

          <ul className="space-y-1">
            {preview.rows.slice(0, VISIBLE_ROWS).map((row) => (
              <li
                key={`${row.row}-${row.name}`}
                className="flex items-start gap-2 rounded-tile bg-tg-secondary-bg/40 p-2 text-xs"
              >
                <span className="w-6 shrink-0 text-tg-hint">{row.row}</span>
                <span
                  className={[
                    "shrink-0 rounded-tile px-1.5 py-0.5 text-2xs font-semibold",
                    ACTION_CLASS[row.action] ?? ACTION_CLASS.skip,
                  ].join(" ")}
                >
                  {tx(ACTION_LABEL[row.action] ?? row.action)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-tg-text">{row.name}</span>
                  {row.detail && (
                    <span className="block text-tg-hint">{row.detail}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {preview.rows.length > VISIBLE_ROWS && (
            <p className="text-xs text-tg-hint">
              {tx("Показаны первые {shown} из {total}.", {
                shown: VISIBLE_ROWS,
                total: preview.rows.length,
              })}
            </p>
          )}
        </div>
      )}

      {result && (
        <div
          data-testid="import-result"
          className="rounded-tile bg-tg-link/10 p-3 text-sm text-tg-text"
        >
          <div className="font-medium">
            {result.kind === "people"
              ? tx("Люди заведены")
              : tx("График загружен")}
          </div>
          <div className="mt-1">
            {tx("Создано: {created}", { created: result.created })} ·{" "}
            {tx("перезаписано: {updated}", { updated: result.updated })} ·{" "}
            {tx("пропущено: {skipped}", { skipped: result.skipped })} ·{" "}
            {tx("ошибок: {errors}", { errors: result.errors })}
          </div>
          {result.errors > 0 && (
            <button
              type="button"
              onClick={() =>
                void showAlert(
                  result.rows
                    .filter((row) => row.action === "error")
                    .slice(0, 10)
                    .map((row) => `${row.row}: ${row.detail}`)
                    .join("\n"),
                )
              }
              className="mt-2 text-xs text-tg-link underline"
            >
              {tx("Показать ошибки")}
            </button>
          )}
        </div>
      )}
    </SubScreen>
  );
}
