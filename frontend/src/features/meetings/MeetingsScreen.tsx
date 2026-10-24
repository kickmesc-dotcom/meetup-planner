import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addMonths, format } from "date-fns";
import { enGB, ru } from "date-fns/locale";
import { motion } from "framer-motion";
import {
  cancelMeeting,
  fetchIcalUrl,
  fetchMeetings,
  setRsvp,
  type MeetingDetail,
} from "@/api/meetings";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import { CardSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Icon, { InlineIcon } from "@/components/Icon";

import { currentLocale, useTx } from "@/i18n";
// P1.4: ответ на встречу — слово, а не эмодзи. В чипе у имени текст ещё и
// читается скринридером, в отличие от картинки ОС.
// Подписи — ключи словаря: переводятся в месте показа, а не при импорте
// модуля.
const RSVP_LABELS: Record<number, string> = {
  0: "—",
  1: "идёт",
  2: "может",
  3: "нет",
};

interface Props {
  users: User[];
  meId: number;
}

export default function MeetingsScreen({ users, meId }: Props) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const now = new Date();
  const horizon = addMonths(now, 3);

  const meetings = useQuery({
    queryKey: ["meetings", now.toDateString()],
    queryFn: () => fetchMeetings(now, horizon),
    staleTime: 15_000,
  });

  const rsvpMut = useMutation({
    mutationFn: ({ id, rsvp }: { id: number; rsvp: number }) => setRsvp(id, rsvp),
    onMutate: async ({ id, rsvp }) => {
      // Оптимистично переключаем my_rsvp + статус себя в attendees, чтобы тап
      // ощущался мгновенным. На откате (onError) возвращаем снимок.
      await qc.cancelQueries({ queryKey: ["meetings"] });
      const snapshot = qc.getQueriesData<MeetingDetail[]>({ queryKey: ["meetings"] });
      qc.setQueriesData<MeetingDetail[] | undefined>({ queryKey: ["meetings"] }, (old) => {
        if (!old) return old;
        return old.map((m) => {
          if (m.id !== id) return m;
          const attendees = m.attendees.some((a) => a.user_id === meId)
            ? m.attendees.map((a) => (a.user_id === meId ? { ...a, rsvp } : a))
            : [...m.attendees, { user_id: meId, rsvp }];
          return { ...m, my_rsvp: rsvp, attendees };
        });
      });
      return { snapshot };
    },
    onError: (_err, _vars, ctx) => {
      haptic("error");
      if (ctx?.snapshot) {
        for (const [key, data] of ctx.snapshot) qc.setQueryData(key, data);
      }
    },
    onSuccess: () => haptic("light"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["meetings"] }),
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) => cancelMeeting(id),
    onSuccess: () => {
      haptic("medium");
      qc.invalidateQueries({ queryKey: ["meetings"] });
    },
    onError: () => haptic("error"),
  });

  if (meetings.isPending) {
    return (
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }
  if (meetings.isError) {
    return (
      <ErrorState error={meetings.error} onRetry={() => meetings.refetch()} />
    );
  }
  const list = (meetings.data ?? []).filter((m) => m.status !== "cancelled");
  if (list.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-6 text-center">
        <Icon name="inbox" size={34} className="mb-2 text-tg-hint" />
        <div className="text-tg-hint">
          {tx("Запланированных встреч пока нет.")}
        </div>
        <div className="text-xs text-tg-hint mt-2">
          {tx("Открой «Календарь» и запусти авто-подбор лучших слотов.")}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <IcalSubscribeButton />
      {list.map((m) => (
        <Card
          key={m.id}
          meeting={m}
          users={users}
          meId={meId}
          onRsvp={(rsvp) => {
            haptic("selection");
            rsvpMut.mutate({ id: m.id, rsvp });
          }}
          onCancel={() => {
            haptic("warning");
            cancelMut.mutate(m.id);
          }}
        />
      ))}
    </div>
  );
}

function Card({
  meeting,
  users,
  meId,
  onRsvp,
  onCancel,
}: {
  meeting: MeetingDetail;
  users: User[];
  meId: number;
  onRsvp: (rsvp: number) => void;
  onCancel: () => void;
}) {
  const { tx } = useTx();
  const start = new Date(meeting.starts_at);
  const end = new Date(meeting.ends_at);
  const my = meeting.my_rsvp;
  const isCreator = meeting.created_by === meId;

  return (
    <motion.div
      initial={{ y: 8, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="rounded-card bg-tg-secondary-bg/60 p-3 shadow-sm"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-base font-semibold truncate">{meeting.title}</div>
          <div className="text-xs text-tg-hint">
            {format(start, "EEE d MMM, HH:mm", { locale: currentLocale() === "en" ? enGB : ru })} –{" "}
            {format(end, "HH:mm", { locale: currentLocale() === "en" ? enGB : ru })}
          </div>
          {meeting.location && (
            <div className="text-xs text-tg-hint mt-0.5">
              <InlineIcon name="pin" />
              {meeting.location}
            </div>
          )}
        </div>
        {meeting.auto_picked && meeting.score != null && (
          <div className="rounded-full bg-tg-link/15 px-2 py-0.5 text-2xs font-medium text-tg-link shrink-0">
            <Icon name="star" size={12} className="mr-0.5 inline-block align-[-2px]" />
            {meeting.score.toFixed(1)}
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {users.map((u) => {
          const att = meeting.attendees.find((a) => a.user_id === u.id);
          const rsvp = att?.rsvp ?? 0;
          return (
            <div
              key={u.id}
              className="flex items-center gap-1 rounded-full bg-tg-bg/60 px-2 py-0.5 text-xs"
              title={`${u.display_name}: ${tx(RSVP_LABELS[rsvp])}`}
            >
              <span
                className="w-4 h-4 rounded-full overflow-hidden inline-flex items-center justify-center text-white text-3xs"
                style={{ background: u.color_hex }}
              >
                {u.avatar_url ? (
                  <img src={u.avatar_url} alt="" className="w-full h-full object-cover" />
                ) : (
                  u.display_name[0]
                )}
              </span>
              <span className="text-tg-text/90 truncate max-w-[60px]">
                {u.display_name.split(/\s+/)[0]}
              </span>
              <span>{tx(RSVP_LABELS[rsvp])}</span>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex gap-1.5">
        <RsvpBtn label={tx("Приду")} active={my === 1} onClick={() => onRsvp(1)} />
        <RsvpBtn label={tx("Может")} active={my === 2} onClick={() => onRsvp(2)} />
        <RsvpBtn label={tx("Нет")} active={my === 3} onClick={() => onRsvp(3)} />
      </div>

      {isCreator && (
        <button
          type="button"
          onClick={() => {
            if (confirm(tx("Отменить встречу?"))) onCancel();
          }}
          className="mt-2 w-full min-h-11 rounded-tile bg-status-busy/15 px-3 text-xs font-medium text-status-busy"
        >
          {tx("Отменить встречу")}
        </button>
      )}
    </motion.div>
  );
}

function RsvpBtn({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex-1 min-h-11 rounded-tile px-2 text-xs font-medium transition-colors",
        active
          ? "bg-tg-button text-tg-button-text"
          : "bg-tg-bg/50 text-tg-text active:bg-tg-bg",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

function IcalSubscribeButton() {
  const { tx } = useTx();
  const ical = useQuery({
    queryKey: ["meetings", "ical-url"],
    queryFn: fetchIcalUrl,
    staleTime: Infinity,
    retry: false,
  });
  if (ical.isPending || ical.isError || !ical.data) return null;
  const onTap = () => {
    haptic("light");
    // iOS открывает webcal:// в системном Календаре; Android — обычно https + .ics.
    const url = /iPhone|iPad|Macintosh/.test(navigator.userAgent)
      ? ical.data.webcal
      : ical.data.https;
    window.open(url, "_blank");
  };
  return (
    <button
      type="button"
      onClick={onTap}
      className="w-full min-h-11 rounded-card bg-tg-secondary-bg/60 px-3 py-2 text-sm text-tg-text active:bg-tg-secondary-bg"
    >
      <Icon name="calendar" size={15} className="mr-1 inline-block align-[-2px]" />
      {tx("Подписаться в системный календарь")}
    </button>
  );
}
