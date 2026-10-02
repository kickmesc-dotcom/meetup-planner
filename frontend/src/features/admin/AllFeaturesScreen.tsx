/**
 * Э22: «Все функции» — один экран, где включить/выключить можно ВСЁ, что бот
 * делает сам, по отдельности: от базовых публикаций до игровых механик.
 *
 * Зачем: рубильники были размазаны по десятку разделов, и «погасить одну штуку»
 * превращалось в квест. Здесь — плоский список с честными рубильниками, а тонкая
 * настройка остаётся в родных разделах (на них ссылается подпись).
 *
 * Источники — те же ручки, что и у остальной админки: экран ничего не меняет в
 * модели, только собирает существующие рубильники в одно место.
 */
import { type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAdvice,
  fetchBotReactions,
  fetchGameAdmin,
  fetchGameMusic,
  fetchGameSocial,
  fetchMediaSettings,
  fetchMeetingFeedbackSettings,
  fetchRandomPhrases,
  fetchScheduledSettings,
  fetchWormMasterSettings,
  fetchWormSettings,
  updateAdviceEnabled,
  updateBotReactions,
  updateGameAdmin,
  updateGameMusic,
  updateGameSocial,
  updateMediaSettings,
  updateMeetingFeedbackSettings,
  updateRandomPhrases,
  updateScheduledSettings,
  updateWormMasterSettings,
  updateWormSettings,
} from "@/api/admin";
import { haptic } from "@/tg/webapp";
import SubScreen from "./SubScreen";

interface FeatureRow {
  icon: string;
  title: string;
  desc: string;
  /** null — у функции нет отдельного рубильника (только тонкая настройка). */
  on: boolean | null;
  toggle?: (next: boolean) => void;
  busy: boolean;
}

/** Один рубильник: включить/выключить функцию целиком. */
function FeatureRow({ icon, title, desc, on, toggle, busy }: FeatureRow) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="flex min-w-0 items-start gap-2">
        <span className="text-base">{icon}</span>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-tg-text">{title}</div>
          <div className="text-[11px] text-tg-hint">{desc}</div>
        </div>
      </div>
      {on === null ? (
        <span className="shrink-0 text-[11px] text-tg-hint">настройка</span>
      ) : (
        <button
          type="button"
          onClick={() => toggle?.(!on)}
          disabled={busy || !toggle}
          className={[
            "shrink-0 rounded-lg px-3 py-2 text-xs font-medium active:scale-[0.98] disabled:opacity-60",
            on ? "bg-status-busy/20 text-status-busy" : "bg-tg-button text-tg-button-text",
          ].join(" ")}
        >
          {busy ? "…" : on ? "Выключить" : "Включить"}
        </button>
      )}
    </div>
  );
}

function Group({ icon, title, children }: { icon: string; title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2 px-1">
        <span className="text-base">{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wide text-tg-hint">
          {title}
        </span>
      </div>
      {children}
    </section>
  );
}

export default function AllFeaturesScreen({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();

  const scheduled = useQuery({ queryKey: ["admin", "scheduled"], queryFn: fetchScheduledSettings });
  const rp = useQuery({ queryKey: ["admin", "random-phrases"], queryFn: fetchRandomPhrases });
  const reactions = useQuery({ queryKey: ["admin", "bot-reactions"], queryFn: fetchBotReactions });
  const media = useQuery({
    queryKey: ["admin", "media-reactions", "settings"],
    queryFn: fetchMediaSettings,
  });
  const advice = useQuery({ queryKey: ["admin", "advice"], queryFn: fetchAdvice });
  const worm = useQuery({ queryKey: ["admin", "worm"], queryFn: fetchWormSettings });
  const wormMaster = useQuery({ queryKey: ["admin", "worm-master"], queryFn: fetchWormMasterSettings });
  const feedback = useQuery({
    queryKey: ["admin", "meeting-feedback"],
    queryFn: fetchMeetingFeedbackSettings,
  });
  const game = useQuery({ queryKey: ["admin", "game"], queryFn: fetchGameAdmin });
  const social = useQuery({ queryKey: ["admin", "game", "social"], queryFn: fetchGameSocial });
  const music = useQuery({ queryKey: ["admin", "game", "music"], queryFn: fetchGameMusic });

  // Один общий «пуск»: после любого переключения обновляем всю ветку admin-
  // запросов, чтобы бейджи на других экранах не врали.
  const mut = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: () => haptic("error"),
  });
  const busy = mut.isPending;
  const set = (fn: () => Promise<unknown>) => mut.mutate(fn);

  const sched = scheduled.data;

  return (
    <SubScreen title="Все функции" onBack={onBack}>
      <div className="rounded-xl bg-tg-secondary-bg/60 p-3 text-[11px] text-tg-hint">
        Каждая функция бота — со своим рубильником. «Включить/Выключить» гасит
        функцию целиком; тонкая настройка (окна, проценты, тексты) — в родных
        разделах, как указано в подписи.
      </div>

      <Group icon="📣" title="Что бот публикует сам">
        <FeatureRow
          icon="🧩"
          title="Рандомные фразы"
          desc="Автопост фраз-реплик · тонко: «Рандомные фразы»"
          on={rp.data?.enabled ?? null}
          busy={busy || rp.isPending}
          toggle={(next) =>
            rp.data && set(() => updateRandomPhrases({ enabled: next, count: rp.data!.count }))
          }
        />
        <FeatureRow
          icon="⏰"
          title="Напоминания о встречах"
          desc="Тик напоминаний по расписанию · тонко: «Интервалы»"
          on={sched?.reminders.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            sched && set(() => updateScheduledSettings({ ...sched, reminders: { ...sched.reminders, enabled: next } }))
          }
        />
        <FeatureRow
          icon="👑"
          title="Лох дня (авто)"
          desc="Автовыбор и публикация · тонко: «Лох»"
          on={sched?.loser.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            sched && set(() => updateScheduledSettings({ ...sched, loser: { ...sched.loser, enabled: next } }))
          }
        />
        <FeatureRow
          icon="🖼"
          title="Синк аватарок"
          desc="Обновление аватарок участников · тонко: «Запланированные публикации»"
          on={sched?.avatars.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            sched && set(() => updateScheduledSettings({ ...sched, avatars: { ...sched.avatars, enabled: next } }))
          }
        />
        <FeatureRow
          icon="🎂"
          title="Алерты о днях рождения"
          desc="Напоминания о ДР участников · тонко: «Дни рождения»"
          on={sched?.birthdays.alerts_enabled ?? null}
          busy={busy}
          toggle={(next) =>
            sched &&
            set(() =>
              updateScheduledSettings({
                ...sched,
                birthdays: { ...sched.birthdays, alerts_enabled: next },
              }),
            )
          }
        />
        <FeatureRow
          icon="🪦"
          title="Мёртвый чат"
          desc="Пост при долгой тишине · тонко: «Запланированные публикации»"
          on={sched?.dead_chat?.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            sched?.dead_chat &&
            set(() =>
              updateScheduledSettings({ ...sched, dead_chat: { ...sched.dead_chat!, enabled: next } }),
            )
          }
        />
      </Group>

      <Group icon="🤖" title="Реакции бота">
        <FeatureRow
          icon="💬"
          title="Ответы на @упоминание и reply"
          desc="Бот отвечает, когда его зовут · тонко: «Реакции бота»"
          on={reactions.data?.mention_enabled ?? null}
          busy={busy}
          toggle={(next) =>
            reactions.data &&
            set(() => updateBotReactions({ ...reactions.data!, mention_enabled: next }))
          }
        />
        <FeatureRow
          icon="🎭"
          title="Реакции на медиа"
          desc="Мемы и подборки: эмодзи + фразы · тонко: «Реакции на медиа»"
          on={media.data?.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            media.data && set(() => updateMediaSettings({ ...media.data!, enabled: next }))
          }
        />
        <FeatureRow
          icon="🔮"
          title="Магический шар"
          desc="/advice, #совет, «@бот …?» · тонко: «Магический шар»"
          on={advice.data?.enabled ?? null}
          busy={busy}
          toggle={(next) => set(() => updateAdviceEnabled(next))}
        />
        <FeatureRow
          icon="🪱"
          title="Червь-господин"
          desc="Подхалимаж, /punish, анонс · тонко: «Червь-господин»"
          on={wormMaster.data?.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            wormMaster.data && set(() => updateWormMasterSettings({ ...wormMaster.data!, enabled: next }))
          }
        />
        <FeatureRow
          icon="🐛"
          title="Титул «червь» на ролле лоха"
          desc="Шанс выпадения титула · тонко: «Лох»"
          on={worm.data?.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            worm.data && set(() => updateWormSettings({ enabled: next, chance: worm.data!.chance }))
          }
        />
      </Group>

      <Group icon="👥" title="Участники">
        <FeatureRow
          icon="⭐"
          title="Фидбек по встречам (5★)"
          desc="Опрос оценки после встречи + учёт отсутствий · тонко: «Встречи»"
          on={feedback.data?.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            feedback.data &&
            set(() => updateMeetingFeedbackSettings({ ...feedback.data!, enabled: next }))
          }
        />
      </Group>

      <Group icon="🏅" title="Игровая система">
        <FeatureRow
          icon="🎮"
          title="Игра (мастер)"
          desc="Опыт, ачивки, гейтинг — выключение гасит ВСЁ игровое · тонко: «Игра»"
          on={game.data?.enabled ?? null}
          busy={busy}
          toggle={(next) =>
            game.data &&
            set(() => updateGameAdmin({ enabled: next, debug_tg_ids: game.data!.debug_tg_ids }))
          }
        />
        <FeatureRow
          icon="⚡"
          title="Случайные события"
          desc="Вопросы и призывы «первый, кто напишет…»"
          on={social.data?.events_enabled ?? null}
          busy={busy}
          toggle={(next) => social.data && set(() => updateGameSocial({ events_enabled: next }))}
        />
        <FeatureRow
          icon="🎙"
          title="Голосовые задания"
          desc="Творческая задача, ответ голосовым"
          on={social.data?.voice_enabled ?? null}
          busy={busy}
          toggle={(next) => social.data && set(() => updateGameSocial({ voice_enabled: next }))}
        />
        <FeatureRow
          icon="🗳"
          title="Опрос «чей вариант лучше»"
          desc="Голосование после сводки голосовых"
          on={social.data?.voice_poll_enabled ?? null}
          busy={busy}
          toggle={(next) => social.data && set(() => updateGameSocial({ voice_poll_enabled: next }))}
        />
        <FeatureRow
          icon="💰"
          title="Контрабанда слов"
          desc="Опыт владельцу кодового слова"
          on={social.data?.contraband_enabled ?? null}
          busy={busy}
          toggle={(next) => social.data && set(() => updateGameSocial({ contraband_enabled: next }))}
        />
        <FeatureRow
          icon="🕯"
          title="Поминовения"
          desc="Некрологи по ушедшим и «ОН ЗДЕСЬ» при возвращении"
          on={social.data?.memorial_enabled ?? null}
          busy={busy}
          toggle={(next) => social.data && set(() => updateGameSocial({ memorial_enabled: next }))}
        />
        <FeatureRow
          icon="📰"
          title="Дайджест в чат"
          desc="Копит события и вываливает одной сводкой"
          on={social.data?.digest_enabled ?? null}
          busy={busy}
          toggle={(next) => social.data && set(() => updateGameSocial({ digest_enabled: next }))}
        />
        <FeatureRow
          icon="🎧"
          title="Музыкальная предложка"
          desc="Еженедельная подборка треков"
          on={music.data?.enabled ?? null}
          busy={busy}
          toggle={(next) => music.data && set(() => updateGameMusic({ enabled: next }))}
        />
        <FeatureRow
          icon="🎵"
          title="Мьюзик-гейм"
          desc="«Угадай, кто предложил трек»"
          on={music.data?.game_enabled ?? null}
          busy={busy}
          toggle={(next) => music.data && set(() => updateGameMusic({ game_enabled: next }))}
        />
      </Group>
    </SubScreen>
  );
}
