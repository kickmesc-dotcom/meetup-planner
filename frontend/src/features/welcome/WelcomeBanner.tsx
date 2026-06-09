/**
 * GHG8 P4.1.a–c: приветствие с быстрой инфой по званиям.
 *
 * Показывается над календарём, пока юзер его не закрыл (ui-prefs
 * `hide_greeting`, E7). Блоки: Чухан недели, Главный лох (+счётчик),
 * Лох дня (или «не выбран»), Червь-пидор (только если есть).
 * Формат юзера (name|avatar|both) — единый на все блоки (P4.1.b),
 * настраивается в «Профиле». Закрытие — через confirm «не показывать,
 * вернуть в настройках профиля» (P4.1.c).
 */
import { useQuery } from "@tanstack/react-query";
import { fetchCurrentTitles } from "@/api/birthdays";
import type { WelcomeFormat } from "@/api/availability";
import type { User } from "@/types";
import { haptic, showConfirm } from "@/tg/webapp";

interface Props {
  users: User[];
  meName: string;
  format: WelcomeFormat;
  onHide: () => void;
}

export default function WelcomeBanner({ users, meName, format, onHide }: Props) {
  const titles = useQuery({
    queryKey: ["titles", "current"],
    queryFn: fetchCurrentTitles,
    staleTime: 60_000,
  });

  const byId = Object.fromEntries(users.map((u) => [u.id, u] as const));
  const t = titles.data;

  return (
    <header className="relative px-4 py-3 border-b border-tg-secondary-bg pr-10">
      <div className="text-base font-medium">Привет, {meName} 👋</div>

      {/* P4.1.a: быстрая инфа. Пока грузится — ничего не мигаем (баннер
          и без неё осмыслен), появится со следующим рендером. */}
      {t && (
        <div className="mt-2 grid grid-cols-2 gap-1.5">
          <TitleBlock
            icon="💩"
            label="Чухан недели"
            user={t.chukhan_user_id != null ? byId[t.chukhan_user_id] : undefined}
            format={format}
          />
          <TitleBlock
            icon="🤡"
            label="Главный лох"
            user={t.main_loser_user_id != null ? byId[t.main_loser_user_id] : undefined}
            suffix={t.main_loser_count > 0 ? `×${t.main_loser_count}` : undefined}
            format={format}
          />
          <TitleBlock
            icon="👑"
            label="Лох дня"
            user={
              t.loser_today_user_id != null ? byId[t.loser_today_user_id] : undefined
            }
            format={format}
          />
          {/* Червь — только при наличии (по спеке «если есть»). */}
          {t.worm_user_id != null && (
            <TitleBlock
              icon="🪱"
              label="Червь-пидор"
              user={byId[t.worm_user_id]}
              format={format}
            />
          )}
        </div>
      )}

      <div className="mt-2 text-xs text-tg-hint">
        Не размечен день = считается{" "}
        <span className="text-status-busy">занятым</span>. Тапай по дате,
        чтобы открыть редактор.
      </div>

      <button
        type="button"
        onClick={async () => {
          haptic("warning");
          // P4.1.c: подтверждение с подсказкой, где вернуть.
          const ok = await showConfirm(
            "Не показывать приветствие? Вернуть можно в настройках профиля (👤).",
          );
          if (ok) onHide();
        }}
        aria-label="Скрыть приветствие"
        title="Не показывать в следующий раз"
        className="absolute top-2 right-2 min-h-8 min-w-8 rounded-md text-tg-hint hover:text-tg-text active:scale-95 transition-transform"
      >
        ✕
      </button>
    </header>
  );
}

/**
 * P4.1.b: ячейка звания. Фиксированная высота h-10 на ВСЕ форматы —
 * «дизайн не расползается при смене отображения» (спека).
 */
function TitleBlock({
  icon,
  label,
  user,
  suffix,
  format,
}: {
  icon: string;
  label: string;
  user: User | undefined;
  suffix?: string;
  format: WelcomeFormat;
}) {
  return (
    <div className="h-10 rounded-lg bg-tg-secondary-bg/60 px-2 flex items-center gap-1.5 min-w-0">
      <span className="text-base shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="text-[9px] leading-tight text-tg-hint truncate">{label}</div>
        <div className="flex items-center gap-1 min-w-0">
          {user ? (
            <>
              {format !== "name" && <Avatar user={user} />}
              {format !== "avatar" && (
                <span className="text-[11px] leading-tight truncate">
                  {user.display_name}
                </span>
              )}
              {suffix && (
                <span className="text-[10px] text-tg-hint tabular-nums shrink-0">
                  {suffix}
                </span>
              )}
            </>
          ) : (
            <span className="text-[11px] leading-tight text-tg-hint">
              не выбран
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function Avatar({ user }: { user: User }) {
  return (
    <div
      className="w-5 h-5 rounded-full overflow-hidden flex items-center justify-center text-white text-[9px] font-medium shrink-0"
      style={{ background: user.color_hex ?? "#888" }}
    >
      {user.avatar_url ? (
        <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />
      ) : (
        user.display_name[0]
      )}
    </div>
  );
}
