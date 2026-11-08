/**
 * Бренд организации (B2B_PLATFORM_PLAN, шаг 4.4).
 *
 * Зачем экран. Продукт назывался SemiTaskBot у всех клиентов: салон показывал
 * команде чужое имя, а логотип и цвет были платформенными. Это последнее, что
 * мешает продать приложение как «своё» — клиент видит не свой бренд.
 *
 * Почему цвет — поле с превью, а не палитра. Палитра навязывает палитру
 * платформы; у клиента уже есть фирменный цвет, и ему нужен ровно `#rrggbb`.
 *
 * Почему логотип — ссылка. Загрузка файла требует хранилища и чистки сирот;
 * у клиента логотип уже лежит на его сайте или CDN. Сервер принимает только
 * `https`: `http` браузер заблокирует на телефоне как смешанный контент.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchBrand, resetBrand, updateBrand, type OrgBrand } from "@/api/brand";
import { Skeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";

/** Коды ошибок сервера → ключ текста. Текст живёт в i18n, не на сервере. */
const ERROR_TEXT: Record<string, string> = {
  bad_color: "Проверьте цвет: нужен формат #1c6fb8.",
  bad_logo: "Логотип должен быть https-ссылкой на картинку.",
  bad_name: "Название не может быть пустым.",
};

export default function BrandScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["brand"],
    queryFn: fetchBrand,
    staleTime: 30_000,
    retry: false,
  });

  const [name, setName] = useState("");
  const [color, setColor] = useState("#1c6fb8");
  const [logo, setLogo] = useState("");

  useEffect(() => {
    if (!q.data) return;
    setName(q.data.name);
    setColor(q.data.color);
    setLogo(q.data.logo_url ?? "");
  }, [q.data]);

  const save = useMutation({
    mutationFn: () => updateBrand({ name, color, logo_url: logo }),
    onSuccess: (data: OrgBrand) => {
      qc.setQueryData(["brand"], data);
      setName(data.name);
      setColor(data.color);
      setLogo(data.logo_url ?? "");
    },
  });
  const reset = useMutation({
    mutationFn: () => resetBrand(),
    onSuccess: (data: OrgBrand) => {
      qc.setQueryData(["brand"], data);
      setName(data.name);
      setColor(data.color);
      setLogo(data.logo_url ?? "");
    },
  });

  const errorCode =
    (save.error as { detail?: string } | null)?.detail ??
    (reset.error as { detail?: string } | null)?.detail ??
    null;
  const errorText = errorCode ? ERROR_TEXT[errorCode] : undefined;
  const busy = save.isPending || reset.isPending;

  return (
    <SubScreen title={tx("Бренд")} onBack={onBack}>
      {q.isLoading && <Skeleton className="h-32" />}

      {q.isError && (
        <p className="rounded-tile bg-tg-secondary-bg p-3 text-sm text-tg-hint">
          {tx("Не удалось загрузить бренд — обнови экран.")}
        </p>
      )}

      {q.data && (
        <>
          <div className="rounded-tile bg-tg-secondary-bg/60 p-3">
            <div className="text-2xs uppercase tracking-wide text-tg-hint">
              {tx("Сейчас команда видит")}
            </div>
            <div className="mt-2 flex items-center gap-2">
              {q.data.logo_url ? (
                <img
                  src={q.data.logo_url}
                  alt=""
                  className="h-9 w-9 rounded-tile object-cover"
                />
              ) : (
                <span
                  className="h-9 w-9 rounded-tile"
                  style={{ background: q.data.color }}
                  aria-hidden="true"
                />
              )}
              <span className="text-base font-semibold text-tg-text">{q.data.name}</span>
            </div>
            {q.data.bot_username && (
              <p className="mt-1 text-xs text-tg-hint">
                {tx("Бот: @{username}", { username: q.data.bot_username })}
              </p>
            )}
          </div>

          <label className="block text-xs font-semibold text-tg-hint">
            {tx("Название")}
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={64}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm font-normal text-tg-text"
            />
          </label>

          <label className="block text-xs font-semibold text-tg-hint">
            {tx("Цвет")}
            <span className="mt-1 flex items-center gap-2">
              <input
                type="color"
                value={/^#[0-9a-fA-F]{6}$/.test(color) ? color : "#1c6fb8"}
                onChange={(event) => setColor(event.target.value)}
                className="h-11 w-14 rounded-tile bg-tg-secondary-bg"
                aria-label={tx("Цвет")}
              />
              <input
                value={color}
                onChange={(event) => setColor(event.target.value)}
                maxLength={9}
                className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg px-3 text-sm font-normal text-tg-text"
                aria-label={tx("Цвет в формате #1c6fb8")}
              />
            </span>
          </label>

          <label className="block text-xs font-semibold text-tg-hint">
            {tx("Логотип (ссылка https)")}
            <input
              value={logo}
              onChange={(event) => setLogo(event.target.value)}
              placeholder="https://example.com/logo.png"
              maxLength={500}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm font-normal text-tg-text"
            />
          </label>

          {errorText && (
            <p className="rounded-tile bg-red-500/10 p-3 text-xs text-red-600" role="alert">
              {tx(errorText)}
            </p>
          )}

          <button
            type="button"
            disabled={busy}
            aria-busy={busy}
            onClick={() => save.mutate()}
            className="min-h-11 w-full rounded-tile bg-tg-link/15 text-sm font-semibold text-tg-link disabled:opacity-50"
          >
            {tx("Сохранить")}
          </button>
          <button
            type="button"
            disabled={busy}
            aria-busy={busy}
            onClick={() => reset.mutate()}
            className="min-h-11 w-full rounded-tile bg-tg-secondary-bg text-sm font-semibold text-tg-hint disabled:opacity-50"
          >
            {tx("Сбросить бренд")}
          </button>

          <p className="rounded-tile bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
            {tx(
              "Название, цвет и логотип применяются сразу после сохранения — у всей команды, а не только у вас.",
            )}
          </p>
        </>
      )}
    </SubScreen>
  );
}
