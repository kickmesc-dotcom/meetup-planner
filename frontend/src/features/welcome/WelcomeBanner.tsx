/**
 * GHG8 P4.1.a–c: приветствие с быстрой инфой по званиям.
 *
 * Показывается над календарём, пока юзер его не закрыл (ui-prefs
 * `hide_greeting`, E7). Блоки: Чухан недели, Лох дня, Главный лох (+счётчик),
 * Главный чухан (+счётчик), Червь-пидор (только если есть) — сетка 2×N.
 * Формат звания (name|avatar|both) — единый на все блоки (P4.1.b),
 * настраивается в «Профиле». Закрытие — через confirm «не показывать,
 * вернуть в настройках профиля» (P4.1.c).
 *
 * H.2 (фидбек 19.06 #1/#2):
 * - приветствие **схлопывается** в одну строку (плоская стрелка вниз), по
 *   умолчанию развёрнуто; крестик «закрыть» остаётся интерактивным и снаружи;
 * - добавлен 4-й блок сводки («Главный чухан»), чтобы сетка не выглядела
 *   несимметричной: 2×2 (+ червь, если он есть);
 * - убрана плашка-подсказка «Не размечен день = занятым…» — по фидбеку она
 *   занимала место и ничего не добавляла.
 */
import { useState } from "react";
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

  // H.2: по умолчанию развёрнуто (фидбек: «по умолчанию - развернута»).
  const [open, setOpen] = useState(true);

  const byId = Object.fromEntries(users.map((u) => [u.id, u] as const));
  const t = titles.data;

  const toggle = () => {
    haptic("light");
    setOpen((v) => !v);
  };

  return (
    // GHG11(11): `pr-16` + кнопка закрытия на `right-12` — правый верхний угол
    // занят глобальным свитчером темы (оболочка приложения).
    <header className="relative px-4 py-0 border-b border-tg-secondary-bg pr-16">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-label={open ? "Свернуть приветствие" : "Развернуть приветствие"}
        /* min-h-11: сама строка была ~24px, и тап выше/ниже текста уходил в
           никуда. Паддинги переехали из header сюда, поэтому высота баннера
           не изменилась (DESIGN_SYSTEM §6: 44px). */
        className="flex min-h-11 w-full items-center gap-1.5 text-left"
      >
        <span className="text-base font-medium truncate">Привет, {meName} 👋</span>
        <span className="text-tg-hint shrink-0" aria-hidden>
          {open ? "▾" : "▴"}
        </span>
        {!open && (
          <span className="text-[11px] text-tg-hint shrink-0">звания</span>
        )}
      </button>

      {open && (
        <>
          {/* P4.1.a: быстрая инфа. Пока грузится — ничего не мигаем (баннер
              и без неё осмыслен), появится со следующим рендером. */}
          {t && (
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              <TitleBlock
                icon="💩"
                label="Чухан недели"
                ink="stamp"
                user={
                  t.chukhan_user_id != null ? byId[t.chukhan_user_id] : undefined
                }
                format={format}
              />
              <TitleBlock
                icon="👑"
                label="Лох дня"
                ink="stamp"
                user={
                  t.loser_today_user_id != null ? byId[t.loser_today_user_id] : undefined
                }
                format={format}
              />
              <TitleBlock
                icon="🤡"
                label="Главный лох"
                ink="stamp"
                user={
                  t.main_loser_user_id != null ? byId[t.main_loser_user_id] : undefined
                }
                suffix={t.main_loser_count > 0 ? `×${t.main_loser_count}` : undefined}
                format={format}
              />
              {/* H.2: 4-й блок — иначе 2×2 разваливалось на «3 + пустота». */}
              <TitleBlock
                icon="🏆"
                label="Главный чухан"
                ink="stamp"
                user={
                  t.main_chukhan_user_id != null
                    ? byId[t.main_chukhan_user_id]
                    : undefined
                }
                suffix={
                  t.main_chukhan_count > 0 ? `×${t.main_chukhan_count}` : undefined
                }
                format={format}
              />
              {/* Червь — только при наличии (по спеке «если есть»); тогда
                  занимает всю строку, чтобы сетка не «рвалась» посередине. */}
              {t.worm_user_id != null && (
                <div className="col-span-2">
                  <TitleBlock
                    icon="🪱"
                    label="Червь-пидор"
                    ink="moss"
                    user={byId[t.worm_user_id]}
                    format={format}
                  />
                </div>
              )}
            </div>
          )}
        </>
      )}

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
        className="absolute top-2 right-12 min-h-11 min-w-11 rounded-md text-tg-hint hover:text-tg-text active:scale-95 transition-transform"
      >
        ✕
      </button>
    </header>
  );
}

/**
 * P4.1.b: ячейка звания. Фиксированная минимальная высота на ВСЕ форматы —
 * «дизайн не расползается при смене отображения» (спека).
 *
 * Identity: звание — это «печать», а не карточка. Слева — человек (лицо и/или
 * имя по настройке), справа — квадратная плашка-штамп с иконкой звания на
 * собственном цвете приложения. Квадрат — намеренное исключение из
 * «всё скруглено»: печать квадратная, карточка — нет.
 */
function TitleBlock({
  icon,
  label,
  user,
  suffix,
  format,
  ink,
}: {
  icon: string;
  label: string;
  user: User | undefined;
  suffix?: string;
  format: WelcomeFormat;
  /** Цвет штампа: `stamp` для званий позора, `moss` для червя. */
  ink: "stamp" | "moss";
}) {
  return (
    <div className="min-h-11 rounded-lg bg-tg-secondary-bg border border-tg-hint/10 pl-2 pr-1.5 py-1 flex items-center gap-2 min-w-0">
      <div className="flex-1 min-w-0">
        {/* Лейбл — обычным регистром: uppercase с разрядкой раздувал кириллицу
            и «ГЛАВНЫЙ ЧУХАН» обрезался до «ГЛАВНЫЙ …». */}
        {/* `text-muted` (= 62% текста темы), а не `text-tg-hint`: подсказка
            Telegram на светлой теме даёт 2.5:1 — лейбл звания переставал
            читаться ровно там, где он единственный называет блок. */}
        <div className="text-3xs leading-tight text-muted truncate">
          {label}
        </div>
        <div className="mt-0.5 flex items-center gap-1 min-w-0">
          {user ? (
            <>
              {format !== "name" && <Avatar user={user} />}
              {format !== "avatar" && (
                <span className="text-sm font-semibold leading-tight truncate">
                  {user.display_name}
                </span>
              )}
              {suffix && (
                <span className="font-mono text-2xs tabular-nums text-tg-hint shrink-0">
                  {suffix}
                </span>
              )}
            </>
          ) : (
            <span className="text-xs leading-tight text-tg-hint">—</span>
          )}
        </div>
      </div>
      {/* Штамп звания. Квадрат, белый глиф, всегда одинаковый размер. */}
      <span
        aria-hidden
        className={[
          "grid h-7 w-7 shrink-0 place-items-center text-[15px] leading-none text-white",
          ink === "moss" ? "bg-ink-moss" : "bg-ink-stamp",
        ].join(" ")}
      >
        {icon}
      </span>
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
