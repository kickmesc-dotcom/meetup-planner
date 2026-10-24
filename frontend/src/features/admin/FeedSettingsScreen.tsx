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
import Icon, { InlineIcon } from "@/components/Icon";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";
import { Switch } from "@/components/Checkbox";

import { useTx } from "@/i18n";
interface Props {
  onBack: () => void;
}

export default function FeedSettingsScreen({ onBack }: Props) {
  const { tx } = useTx();
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
      title={tx("Вид ленты")}
      subtitle={tx("Компактный (новый) / классический")}
      onBack={onBack}
    >
      {q.isError && (
        <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
          <InlineIcon name="alert" />
          {humanizeApiError(q.error)}
        </div>
      )}

      <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-3">
        <div className="flex items-center gap-2">
          <Icon name="sparkles" size={18} className="text-tg-link" />
          <span className="text-sm font-semibold text-tg-text">
            {tx("Компактный вид")}
          </span>
        </div>
        <div className="text-xs text-tg-hint">
          {tx(
            "Под событием смены — миниатюры участников и бейдж «+XP». Плотнее по вертикали и без отдельных блоков на каждую строку. Выключено — классический вид с карточкой на событие.",
          )}
        </div>
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="text-sm text-tg-text">
            {tx("Включён")}
            {q.isPending && (
              <span className="ml-2 text-xs text-tg-hint">
                {tx("загрузка…")}
              </span>
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
        <div className="text-2xs text-tg-hint">
          {tx("Влияет на ленту у всех участников. Откат — переключить тумблер обратно.")}
        </div>
      </section>
    </SubScreen>
  );
}
