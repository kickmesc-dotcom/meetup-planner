/**
 * GHG8 P6.1 — редактор персоналий участников (генератор фраз v2 «Типажи»).
 *
 * Тексты живут только в Neon (`participant_personas`) — проект публикуется
 * открытым гитом, персоналии в репо нельзя. Сидинг — руками отсюда (P6.1.b).
 *
 * Формат текста: секция `[шаблоны]` — по шаблону на строку, `{слот}` —
 * плейсхолдер; любая другая секция `[имя]` — значения слота (по одному на
 * строку). Шаблон с плейсхолдером без заполненного слота помечается «битым»
 * и в генерации не участвует. Пустой текст при сохранении = удаление.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchPersonas,
  previewPersona,
  updatePersona,
  type PersonaRow,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

const FORMAT_HINT = `[шаблоны]
Я блять ненавижу {объект}
{мудрость}... как говорили древние
[объект]
индусов
понедельники
[мудрость]
терпение — путь самурая`;

export default function PersonasScreen({ onBack }: Props) {
  const [editing, setEditing] = useState<PersonaRow | null>(null);

  return (
    <SubScreen
      title="🎭 Персоналии"
      subtitle="Типажи участников для генератора фраз v2"
      onBack={editing ? () => setEditing(null) : onBack}
    >
      {editing ? (
        <PersonaEditor row={editing} onDone={() => setEditing(null)} />
      ) : (
        <PersonaList onEdit={setEditing} />
      )}
    </SubScreen>
  );
}

function PersonaList({ onEdit }: { onEdit: (row: PersonaRow) => void }) {
  const personas = useQuery({
    queryKey: ["admin", "personas"],
    queryFn: fetchPersonas,
  });

  if (personas.isPending) {
    return (
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <ListSkeleton rows={6} />
      </section>
    );
  }
  if (personas.isError || !personas.data) {
    return (
      <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
        ⚠ {humanizeApiError(personas.error)}
      </div>
    );
  }

  return (
    <>
      <div className="text-xs text-tg-hint px-1">
        Тексты хранятся только в БД (не в git). Версия генератора
        переключается в «Рандомные фразы → Версия генератора».
      </div>
      <section className="rounded-xl bg-tg-secondary-bg/60 divide-y divide-tg-bg/40">
        {personas.data.map((row) => (
          <button
            key={row.user_id}
            type="button"
            onClick={() => {
              haptic("selection");
              onEdit(row);
            }}
            className="w-full px-3 py-2.5 flex items-center gap-2 text-left active:bg-tg-bg/30"
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm text-tg-text truncate">{row.display_name}</div>
              <div className="text-[11px] text-tg-hint">
                {row.persona_text == null
                  ? "персоналия не заведена"
                  : `шаблонов: ${row.templates_count}` +
                    (row.broken_templates_count > 0
                      ? ` · битых: ${row.broken_templates_count} ⚠`
                      : "")}
              </div>
            </div>
            <span className="text-tg-hint shrink-0">
              {row.persona_text == null ? "＋" : "›"}
            </span>
          </button>
        ))}
      </section>
    </>
  );
}

function PersonaEditor({ row, onDone }: { row: PersonaRow; onDone: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState(row.persona_text ?? "");
  const [preview, setPreview] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => updatePersona(row.user_id, text),
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "personas"] });
      onDone();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const tryPreview = useMutation({
    mutationFn: () => previewPersona(row.user_id, text),
    onSuccess: (out) => {
      haptic("light");
      setPreview(out.phrase ?? "(ни одного пригодного шаблона)");
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  return (
    <>
      <div className="text-sm font-semibold px-1">{row.display_name}</div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={14}
        placeholder={FORMAT_HINT}
        className="w-full rounded-xl bg-tg-secondary-bg/60 p-3 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link font-mono leading-snug"
      />
      <div className="text-[11px] text-tg-hint px-1">
        [шаблоны] — по одному на строку, «{"{слот}"}» — плейсхолдер. Любая
        другая секция [имя] — значения слота. Пустой текст = удалить
        персоналию.
      </div>

      {preview != null && (
        <div className="rounded-xl bg-tg-bg/50 p-3 text-sm italic">«{preview}»</div>
      )}

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={tryPreview.isPending || !text.trim()}
          onClick={() => tryPreview.mutate()}
          className="min-h-11 rounded-lg bg-tg-secondary-bg py-2 text-sm font-medium text-tg-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {tryPreview.isPending && <Spinner />}
          🎲 Превью
        </button>
        <button
          type="button"
          disabled={save.isPending || text === (row.persona_text ?? "")}
          onClick={() => {
            haptic("medium");
            save.mutate();
          }}
          className="min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {save.isPending && <Spinner />}
          💾 Сохранить
        </button>
      </div>
    </>
  );
}
