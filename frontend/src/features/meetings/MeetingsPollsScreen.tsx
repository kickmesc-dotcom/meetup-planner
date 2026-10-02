import { useState } from "react";
import { haptic } from "@/tg/webapp";
import type { User } from "@/types";
import MeetingsScreen from "./MeetingsScreen";
import PollsScreen from "@/features/polls/PollsScreen";

/**
 * Э21: «Встречи и опросы» — одна вкладка вместо двух.
 *
 * Раньше это были отдельные кнопки внизу; оператор отметил, что ими почти не
 * пользовались, поэтому объединяем в один раздел с переключателем внутри.
 * Внешняя вкладка осталась только одна — `meetings` (см. `store/ui.ts`).
 */
type Section = "meetings" | "polls";

export default function MeetingsPollsScreen({
  users,
  meId,
}: {
  users: User[];
  meId: number;
}) {
  const [section, setSection] = useState<Section>("meetings");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <SectionButton
          active={section === "meetings"}
          onClick={() => setSection("meetings")}
          label="🤝 Встречи"
        />
        <SectionButton
          active={section === "polls"}
          onClick={() => setSection("polls")}
          label="🗳️ Опросы"
        />
      </div>
      {section === "meetings" ? (
        <MeetingsScreen users={users} meId={meId} />
      ) : (
        <PollsScreen users={users} meId={meId} />
      )}
    </div>
  );
}

function SectionButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        if (active) return;
        haptic("selection");
        onClick();
      }}
      className={[
        "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
        active ? "bg-tg-link text-white" : "bg-tg-secondary-bg/70 text-tg-hint",
      ].join(" ")}
    >
      {label}
    </button>
  );
}
