/**
 * «Тексты приложения» — вместо снапшота мемных фраз.
 *
 * Управляющий правит готовые формулировки под свой ресторан: приветствие,
 * подсказки, пустые состояния. Дефолты живут в коде сервера, правки — в
 * `admin_config`; пустое поле возвращает исходный текст. Ничего не «теряется»
 * при обновлении: старый мемный контур сюда не переезжает.
 *
 * Черновик один на весь экран и сохраняется кнопкой: правок обычно несколько,
 * а «сохранить каждую букву» — лишние запросы и случайные полупустые тексты.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchTextsCatalog,
  saveAppTexts,
  type AppTextItem,
} from "@/api/texts";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import Icon, { InlineIcon } from "@/components/Icon";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

export default function AppTextsScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "texts"],
    queryFn: fetchTextsCatalog,
    staleTime: 30_000,
  });

  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!q.data) return;
    setDraft(
      Object.fromEntries(q.data.items.map((item) => [item.code, item.value])),
    );
  }, [q.data]);

  const items = q.data?.items ?? [];
  const groups = useMemo(() => {
    const map = new Map<string, AppTextItem[]>();
    for (const item of items) {
      const list = map.get(item.group) ?? [];
      list.push(item);
      map.set(item.group, list);
    }
    return Array.from(map.entries());
  }, [items]);

  // Отправляем только изменённое: так сохранение не «замораживает» дефолты,
  // которые никто не правил. Пустая строка в теле снимает правку на сервере.
  const changes = useMemo(
    () =>
      Object.fromEntries(
        items
          .filter((item) => (draft[item.code] ?? "") !== item.value)
          .map((item) => [item.code, draft[item.code] ?? ""]),
      ),
    [draft, items],
  );

  const dirty = Object.keys(changes).length > 0;

  const save = useMutation({
    mutationFn: () => saveAppTexts(changes),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "texts"], data);
      qc.invalidateQueries({ queryKey: ["app-texts"] });
      void showAlert("Тексты сохранены.");
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  // «Как было» — это пустая строка: сервер снимает правку и отдаёт дефолт.
  const reset = (item: AppTextItem) => {
    haptic("selection");
    setDraft((cur) => ({ ...cur, [item.code]: "" }));
  };

  return (
    <SubScreen
      title="Тексты приложения"
      subtitle="Подписи, которые видит сотрудник"
      onBack={onBack}
    >
      <div className="rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
        Меняй формулировки под свой ресторан. Пустое поле — вернуть исходный
        текст. Кнопки и юридически значимые подписи здесь не редактируются:
        их нельзя сломать случайной правкой.
      </div>

      {q.isPending && <ListSkeleton rows={4} />}
      {q.isError && (
        <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
          <InlineIcon name="alert" />
          {humanizeApiError(q.error)}
        </div>
      )}

      {groups.map(([group, groupItems]) => (
        <section key={group} className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-3">
          <div className="text-sm font-semibold text-tg-text">{group}</div>
          {groupItems.map((item) => (
            <label key={item.code} className="block space-y-1">
              <span className="block text-xs text-tg-text">{item.title}</span>
              {item.hint && (
                <span className="block text-2xs text-tg-hint">{item.hint}</span>
              )}
              <textarea
                value={draft[item.code] ?? ""}
                placeholder={item.default}
                onChange={(e) => {
                  const value = e.target.value;
                  setDraft((cur) => ({ ...cur, [item.code]: value }));
                }}
                rows={2}
                maxLength={600}
                className="w-full resize-none rounded-tile bg-tg-bg/70 p-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
              />
              <span className="flex items-center justify-between gap-2">
                <span className="text-2xs text-tg-hint">
                  {(draft[item.code] ?? "").trim()
                    ? `${(draft[item.code] ?? "").length}/600`
                    : "по умолчанию"}
                </span>
                {(draft[item.code] ?? "").trim() &&
                  (draft[item.code] ?? "") !== item.value && (
                  <button
                    type="button"
                    onClick={() => reset(item)}
                    className="min-h-9 rounded-tile bg-tg-bg/70 px-2 text-xs text-tg-link active:scale-95 transition-transform"
                  >
                    ↺ Как было
                  </button>
                )}
              </span>
            </label>
          ))}
        </section>
      ))}

      {items.length > 0 && (
        <div className="sticky bottom-0 -mx-3 px-3 pb-3 pt-2 bg-tg-bg/95 backdrop-blur">
          <button
            type="button"
            disabled={!dirty || save.isPending}
            onClick={() => {
              haptic("medium");
              save.mutate();
            }}
            className="w-full min-h-11 rounded-tile bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
          >
            {save.isPending && <Spinner />}
            {save.isPending ? (
              "Сохраняем…"
            ) : dirty ? (
              <>
                <Icon name="save" size={16} />
                Сохранить тексты
              </>
            ) : (
              <>
                <Icon name="check" size={16} />
                Сохранено
              </>
            )}
          </button>
        </div>
      )}
    </SubScreen>
  );
}
