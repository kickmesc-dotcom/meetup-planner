/**
 * Языковой пакет организации (план, 8.3).
 *
 * Зачем отдельный экран, а не тумблер в мастере настройки. Мастер проходят
 * один раз при заведении организации, а язык меняется позже: пришла смена,
 * где половина зала — узбеки. Искать это в анкете первого запуска человек не
 * станет.
 *
 * Почему решает владелец, а не руководитель смены. Пакет — будущая платная
 * опция тарифа, то есть решение про деньги. Руководителю тумблер виден, но
 * неактивен, и рядом написано, почему: «нельзя» без объяснения выглядит как
 * поломка.
 *
 * Почему флаг живёт в настройках ОРГАНИЗАЦИИ, а не в личных. Личные настройки
 * означали бы, что каждый сотрудник должен сам догадаться включить себе
 * перевод. Язык команды — решение организации, личный выбор — это только
 * «какой из доступных языков мне удобнее».
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchOrgSetup, saveOrgSetup } from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import Icon, { InlineIcon } from "@/components/Icon";
import { Switch } from "@/components/Checkbox";
import { Skeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";

interface Props {
  onBack: () => void;
}

export default function LanguagesScreen({ onBack }: Props) {
  const { tx } = useTx();
  const qc = useQueryClient();

  // Тот же ключ, что у каркаса приложения: настройка уже в кэше, лишнего
  // запроса при открытии экрана не будет.
  const q = useQuery({
    queryKey: ["org-setup"],
    queryFn: fetchOrgSetup,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const mut = useMutation({
    mutationFn: (enabled: boolean) => saveOrgSetup({ uz_pack: enabled }),
    onSuccess: (out) => {
      haptic("success");
      qc.setQueryData(["org-setup"], out);
      // Переключатель языка читает флаг из каркаса — он обновится сам, но
      // экраны с уже загруженным текстом надо перерисовать: меняется язык
      // интерфейса у всех, кому он был выбран.
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: async (e) => {
      haptic("error");
      await showAlert(humanizeApiError(e));
    },
  });

  const enabled = q.data?.uz_pack ?? true;
  const canManage = q.data?.can_manage_packs ?? false;
  const busy = q.isPending || mut.isPending;

  return (
    <SubScreen
      title={tx("Языки")}
      subtitle={tx("Языковой пакет команды")}
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
          <Icon name="globe" size={18} className="text-tg-link" />
          <span className="text-sm font-semibold text-tg-text">
            {tx("Узбекский язык")}
          </span>
        </div>
        <div className="text-xs text-tg-hint">
          {tx(
            "Переведены рабочие экраны смены: чек-лист и мои задачи. Остальное остаётся русским — непереведённая строка читается, а не превращается в код.",
          )}
        </div>
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="text-sm text-tg-text">
            {enabled ? tx("Включён") : tx("Выключен")}
            {q.isPending && (
              <Skeleton className="ml-2 inline-block h-3 w-10 align-middle" />
            )}
          </div>
          <Switch
            checked={enabled}
            disabled={busy || !canManage}
            onChange={(v) => {
              haptic("selection");
              mut.mutate(v);
            }}
          />
        </div>
        <div className="text-2xs text-tg-hint">
          {tx(
            "Влияет на всех: узбекский появляется в переключателе языка у каждого сотрудника. Выключено — в переключателе остаются русский и английский.",
          )}
        </div>
        <div className="text-2xs text-tg-hint">
          {canManage
            ? tx(
                "Решает владелец организации: языковой пакет — часть тарифа, а не настройка смены.",
              )
            : tx(
                "Менять может только владелец организации: языковой пакет — часть тарифа. Попроси его включить перевод.",
              )}
        </div>
      </section>

      <section className="rounded-card bg-tg-secondary-bg/40 p-3 space-y-2">
        <div className="text-2xs uppercase tracking-wide text-tg-hint">
          {tx("Как работает перевод")}
        </div>
        <p className="text-xs text-tg-hint">
          {tx(
            "Сотрудник выбирает язык сам кнопками RU / EN / UZ — выбор хранится в его устройстве и переживает перезапуск. Организация решает только, доступен ли узбекский.",
          )}
        </p>
        <p className="text-xs text-tg-hint">
          {tx(
            "Русский — оригинал и запасной вариант: если строки нет в пакете, она показывается по-русски. Поэтому пакет можно включать по мере перевода, а не «когда всё готово».",
          )}
        </p>
        <p className="text-xs text-tg-hint">
          {tx(
            "Выключили пакет — те, у кого был выбран узбекский, сразу возвращаются на русский: остаться на языке, которого организация больше не обещает, выглядит как сбой.",
          )}
        </p>
      </section>
    </SubScreen>
  );
}
