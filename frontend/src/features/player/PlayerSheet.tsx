/**
 * GHG11(17): плеер как верхний вход в ленте вместо колокольчика.
 *
 * Почему колокольчик ушёл. В шапке ленты висел 🔔, но единственным поводом для
 * него были лайки своих треков — редкое событие, ради которого в шапке держали
 * целую кнопку с бейджем. Оператор справедливо не понял, «что он предлагает
 * делать с лайками». Теперь в этом слоте — плеер: он нужен постоянно, а не
 * когда кто-то случайно лайкнул трек.
 *
 * Что даёт шит:
 *  - **выбрать подборку конкретной недели** (из тех, что уже играбельны) и
 *    слушать ровно её;
 *  - **всё подряд** — подборки одна за другой, как раньше;
 *  - **всё вперемешку** — тот же набор, но перемешанный;
 *  - **только лайкнутые**.
 *
 * Главное правило плеера не изменилось и живёт в `GlobalPlayer`/`MiniPlayer`:
 * нажал play — играет бесперебойно, пока человек сам не остановит. Когда
 * выбранная подборка кончается, очередь не зацикливается на ней, а продолжается
 * треками, которые звучали РЕЖЕ ВСЕГО (`leastPlayedOrder`).
 *
 * Уведомления не выброшены — они переехали вниз этого же шита: личные события
 * по-прежнему можно прочитать, но они больше не занимают место в шапке.
 */
import { useEffect } from "react";
import { SOURCE_ALL, SOURCE_LIKED, useGlobalPlayer } from "@/components/GlobalPlayer";
import BottomSheet from "@/features/actions/BottomSheet";
import { useNotifications } from "@/features/notifications/NotificationsBell";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";

/**
 * Кнопка-вход в шит плеера. Живёт в шапке ленты на месте колокольчика.
 *
 * Иконка всегда одна (🎧): подменять её на ⏸ значило бы обещать паузу по тапу,
 * а тап открывает шит. Что музыка идёт — видно точкой, а не подменой символа.
 */
export function PlayerButton() {
  const open = useUI((s) => s.setShowPlayerSheet);
  const player = useGlobalPlayer();
  const label = player.active
    ? `Музыка: играет «${player.title}»`
    : "Музыка: выбрать подборку";
  return (
    <button
      type="button"
      data-testid="player-launcher"
      aria-haspopup="dialog"
      aria-label={label}
      title={label}
      onClick={() => open(true)}
      className="relative shrink-0 rounded-full px-2 py-1 text-base transition-colors active:bg-tg-secondary-bg"
    >
      🎧
      {player.active && (
        <span
          data-testid="player-launcher-dot"
          aria-hidden
          className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-tg-link"
        />
      )}
    </button>
  );
}

/** Кнопка-строка источника звука: подсвечена, если он выбран сейчас. */
function SourceRow({
  active,
  title,
  hint,
  testId,
  onClick,
}: {
  active: boolean;
  title: string;
  hint?: string;
  testId: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={active}
      onClick={onClick}
      className={[
        "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs",
        active ? "bg-tg-button text-tg-button-text" : "bg-tg-secondary-bg/50 text-tg-text",
      ].join(" ")}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{title}</span>
        {hint && (
          <span
            className={[
              "block truncate text-[10px]",
              active ? "text-tg-button-text/80" : "text-tg-hint",
            ].join(" ")}
          >
            {hint}
          </span>
        )}
      </span>
      {active && <span aria-hidden>✓</span>}
    </button>
  );
}

/**
 * Шит плеера: выбор источника + режима порядка. Выбор сразу начинает играть
 * (человек пришёл сюда слушать) и закрывает шит — чтобы не искать закрытие.
 */
export default function PlayerSheet() {
  const close = useUI((s) => s.setShowPlayerSheet);
  const openNotifications = useUI((s) => s.setShowNotificationsSheet);
  const player = useGlobalPlayer();
  const notes = useNotifications();
  const unread = notes.data?.unread ?? 0;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const pick = (key: string, opts?: { shuffle?: boolean }) => {
    haptic("selection");
    player.chooseSource(key, opts);
    close(false);
  };

  const playlistHint = (count: number) => `${count} трек(ов), потом реже звучавшие`;

  return (
    <BottomSheet title="🎧 Музыка" onClose={() => close(false)}>
      <div data-testid="player-sheet" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <div className="text-[11px] text-tg-hint">
            Играет, пока сам не остановишь. Кончится подборка — плеер подхватит
            треки, которые звучали реже.
          </div>
          <SourceRow
            testId="player-source-all"
            active={player.sourceKey === SOURCE_ALL && !player.shuffle}
            title="▶️ Всё подряд"
            hint="Подборки одна за другой, свежая первой"
            onClick={() => pick(SOURCE_ALL, { shuffle: false })}
          />
          <SourceRow
            testId="player-source-shuffle"
            active={player.sourceKey === SOURCE_ALL && player.shuffle}
            title="🔀 Всё вперемешку"
            hint="Тот же набор в случайном порядке"
            onClick={() => pick(SOURCE_ALL, { shuffle: true })}
          />
          <SourceRow
            testId="player-source-liked"
            active={player.sourceKey === SOURCE_LIKED}
            title={`❤️ Только лайкнутые${
              player.likedCount > 0 ? ` (${player.likedCount})` : ""
            }`}
            hint={
              player.likedCount > 0
                ? "Треки, которым ты поставил лайк"
                : "Пока ни одного лайка"
            }
            onClick={() => pick(SOURCE_LIKED, { shuffle: false })}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="text-[11px] font-medium text-tg-hint">Подборки по неделям</div>
          {player.playlists.length === 0 ? (
            <div data-testid="player-sheet-empty" className="text-xs text-tg-hint">
              Пока нет ни одной подборки с треками, загруженными боту.
            </div>
          ) : (
            player.playlists.map((pl) => (
              <SourceRow
                key={pl.key}
                testId={`player-source-${pl.key}`}
                active={player.sourceKey === pl.key}
                title={pl.title}
                hint={playlistHint(pl.tracks.length)}
                onClick={() => pick(pl.key, { shuffle: false })}
              />
            ))
          )}
        </div>

        {/* Уведомления переехали сюда из шапки: личные лайки своих треков — не
            то, ради чего стоит держать кнопку в верхней строке, но знать о них
            по-прежнему нужно. Открываем ИХ шит (список отмечает прочитанное при
            показе) — то есть переключаем шиты, а не складываем один в другой. */}
        <div className="border-t border-tg-secondary-bg pt-3">
          <button
            type="button"
            data-testid="player-sheet-notifications"
            onClick={() => {
              haptic("selection");
              close(false);
              openNotifications(true);
            }}
            className="flex w-full items-center gap-2 rounded-lg bg-tg-secondary-bg/50 px-2.5 py-2 text-left text-xs text-tg-text"
          >
            <span aria-hidden>🔔</span>
            <span className="min-w-0 flex-1 truncate font-medium">Личные уведомления</span>
            {unread > 0 && (
              <span className="shrink-0 rounded-full bg-status-busy px-1.5 text-[10px] font-semibold text-tg-bg">
                {unread > 9 ? "9+" : unread}
              </span>
            )}
          </button>
        </div>
      </div>
    </BottomSheet>
  );
}
