/**
 * GHG11(4): UI-тумблер `feed.view_compact`.
 *
 * Флаг живёт в `admin_config` (key `feed.view_compact`, default `true`) и
 * применяется к ленте ВСЕХ участников. Новый компактный вид — миниатюры
 * участников голосового задания прямо под блоком (кто сдал и сколько XP),
 * старый — как было. Лента сама читает `feed_view` из `/game/feed`, поэтому
 * переключение подхватывается без рестарта.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchFeedViewFlag, setFeedViewFlag } from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";
import { Switch } from "@/components/Checkbox";

interface Props {
  onBack: () => void;
}

export default function FeedSettingsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["admin", "feed", "view"],
    queryFn: fetchFeedViewFlag,
    staleTime: 30_000,
  });

  const mut = useMutation({
    mutationFn: (compact: boolean) => setFeedViewFlag(compact),
    onSuccess: (out) => {
      haptic("success");
      qc.setQueryData(["admin", "feed", "view"], out);
      // Лента кэшируется отдельно — сбрасываем, чтобы новый вид применился сразу.
      qc.invalidateQueries({ queryKey: ["game-feed"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const compact = q.data?.compact ?? true;
  const busy = q.isPending || mut.isPending;

  return (
    <SubScreen
      title="📰 Вид ленты"
      subtitle="Компактный (новый) / классический"
      onBack={onBack}
    >
      {q.isError && (
        <div className="rounded-lg bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {humanizeApiError(q.error)}
        </div>
      )}

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🆕</span>
          <span className="text-sm font-semibold text-tg-text">
            Компактный вид
          </span>
        </div>
        <div className="text-[11px] text-tg-hint">
          Под каждым блоком (голосовые, музыка, раунд, лох/чухан, активность
          фич) — миниатюры участников с бейджем «+XP»/«❤️лайки». Без «спама»
          отдельными блоками. Выключено — классический вид, как было раньше.
        </div>
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="text-sm text-tg-text">
            Включён
            {q.isPending && (
              <span className="ml-2 text-[11px] text-tg-hint">загрузка…</span>
            )}
          </div>
          <Switch
            checked={compact}
            disabled={busy}
            onChange={(v) => {
              haptic("selection");
              mut.mutate(v);
            }}
          />
        </div>
        <div className="text-[10px] text-tg-hint">
          Влияет на ленту у всех участников. Откат — переключить тумблер обратно.
        </div>
      </section>
    </SubScreen>
  );
}
