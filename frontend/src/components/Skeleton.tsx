interface Props {
  className?: string;
}

export function Skeleton({ className }: Props) {
  return (
    <div
      className={[
        "animate-pulse rounded bg-tg-bg/50",
        className ?? "",
      ].join(" ")}
    />
  );
}

export function CardSkeleton() {
  return (
    <div className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2 animate-pulse">
      <div className="h-4 w-2/3 rounded bg-tg-bg/60" />
      <div className="h-3 w-1/3 rounded bg-tg-bg/40" />
      <div className="mt-2 flex gap-1.5">
        <div className="h-5 w-16 rounded-full bg-tg-bg/40" />
        <div className="h-5 w-16 rounded-full bg-tg-bg/40" />
        <div className="h-5 w-16 rounded-full bg-tg-bg/30" />
      </div>
      <div className="mt-2 flex gap-1.5">
        <div className="h-7 flex-1 rounded-lg bg-tg-bg/40" />
        <div className="h-7 flex-1 rounded-lg bg-tg-bg/40" />
        <div className="h-7 flex-1 rounded-lg bg-tg-bg/40" />
      </div>
    </div>
  );
}

export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-tg-bg/50" />
          <div className="flex-1 h-4 rounded bg-tg-bg/40" />
          <div className="w-7 h-4 rounded bg-tg-bg/40" />
        </div>
      ))}
    </div>
  );
}
