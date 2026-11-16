import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import { fetchEmployee } from "@/api/hr";
import {
  createSupply,
  fetchSupplies,
  fetchSupplyMovements,
  moveSupply,
  type Supply,
  type SupplyMovement,
} from "@/api/supplies";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { useTx } from "@/i18n";
import SubScreen from "@/features/admin/SubScreen";

/**
 * Склад расходников.
 *
 * Экран отвечает на два вопроса смены: «сколько осталось» и «кто взял».
 * Поэтому сверху остаток и порог, а история — по раскрытию, а не сразу: в
 * обычной смене она не нужна, а в споре открывается в один тап.
 *
 * Списание доступно любому сотруднику, приход — только руководителю (кнопка
 * скрыта, сервер всё равно проверит): приход означает приёмку товара.
 *
 * Почему количество вводится числом, а не кнопками «+1». Расходники бывают
 * дробными (литры, килограммы), и десять нажатий на «+0.1» — это не работа
 * склада, а наказание.
 */
export default function SuppliesScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["supplies"], queryFn: fetchSupplies });
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const canReceive = !!meQ.data?.is_staff;

  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["supplies"] });
    void qc.invalidateQueries({ queryKey: ["supply-movements"] });
  };

  const items = q.data ?? [];
  const low = items.filter((item) => item.low);

  return (
    <SubScreen
      title={tx("Расходники")}
      subtitle={
        low.length > 0
          ? tx("Мало на складе: {count}", { count: low.length })
          : tx("Остатки и списания")
      }
      onBack={onBack}
    >
      <div className="space-y-3">
        {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
        {q.isLoading && <ListSkeleton rows={4} />}

        {canReceive && (
          <button
            type="button"
            onClick={() => {
              haptic("light");
              setCreating((v) => !v);
            }}
            className="flex min-h-11 w-full items-center justify-center gap-1.5 rounded-tile bg-tg-secondary-bg text-xs font-medium text-tg-text"
          >
            <Icon name="plus" size={14} />
            {tx("Добавить позицию")}
          </button>
        )}
        {creating && canReceive && (
          <CreateForm
            onDone={() => {
              setCreating(false);
              refresh();
            }}
          />
        )}

        {q.data && items.length === 0 && (
          <p className="rounded-card bg-tg-secondary-bg/40 p-4 text-center text-xs text-tg-hint">
            {tx("Склад пока пустой. Добавьте то, что расходуется каждую смену.")}
          </p>
        )}

        <ul className="space-y-2">
          {items.map((item) => (
            <SupplyCard
              key={item.id}
              item={item}
              open={openId === item.id}
              canReceive={canReceive}
              onToggle={() => setOpenId((current) => (current === item.id ? null : item.id))}
              onChanged={refresh}
            />
          ))}
        </ul>
      </div>
    </SubScreen>
  );
}

function SupplyCard({
  item,
  open,
  canReceive,
  onToggle,
  onChanged,
}: {
  item: Supply;
  open: boolean;
  canReceive: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const { tx } = useTx();
  const [kind, setKind] = useState<"in" | "out" | null>(null);
  const [amount, setAmount] = useState("1");
  const [comment, setComment] = useState("");
  const [showHistory, setShowHistory] = useState(false);

  const move = useMutation({
    mutationFn: () =>
      moveSupply(item.id, {
        kind: kind ?? "out",
        quantity: Number(amount.replace(",", ".")),
        comment: comment.trim() || null,
      }),
    onSuccess: () => {
      haptic("success");
      setKind(null);
      setAmount("1");
      setComment("");
      onChanged();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const historyQ = useQuery({
    queryKey: ["supply-movements", item.id],
    queryFn: () => fetchSupplyMovements(item.id),
    enabled: showHistory,
    staleTime: 15_000,
  });

  return (
    <li className="rounded-card bg-tg-secondary-bg/60 p-3">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 text-left"
        aria-expanded={open}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-tg-text">{item.name}</span>
            {item.low && (
              <span className="rounded-full bg-status-busy/15 px-1.5 py-0.5 text-2xs font-medium text-status-busy">
                {tx("мало")}
              </span>
            )}
          </div>
          <div className="mt-0.5 text-2xs text-tg-hint">
            {[item.department, item.unit].filter(Boolean).join(" · ")}
          </div>
        </div>
        <span
          className={[
            "text-sm tabular-nums",
            item.low ? "text-status-busy" : "text-tg-text",
          ].join(" ")}
        >
          {formatQty(item.quantity)} {item.unit}
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-2 border-t border-tg-secondary-bg pt-2">
          {kind === null ? (
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setKind("out")}
                className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs font-medium text-tg-text"
              >
                {tx("Списать")}
              </button>
              {canReceive && (
                <button
                  type="button"
                  onClick={() => setKind("in")}
                  className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs font-medium text-tg-text"
                >
                  {tx("Приход")}
                </button>
              )}
              <button
                type="button"
                onClick={() => setShowHistory((v) => !v)}
                className="min-h-9 rounded-tile px-3 text-xs font-medium text-tg-link"
              >
                {showHistory ? tx("Скрыть историю") : tx("История")}
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-xs text-tg-hint">
                <span className="shrink-0">
                  {kind === "out" ? tx("Сколько списать") : tx("Сколько принять")}
                </span>
                <input
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  min="0"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  className="min-h-9 w-24 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
                />
                <span>{item.unit}</span>
              </label>
              <input
                type="text"
                value={comment}
                maxLength={300}
                onChange={(event) => setComment(event.target.value)}
                placeholder={tx("Куда или зачем (необязательно)")}
                className="min-h-9 w-full rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
              />
              <div className="flex gap-1.5">
                <button
                  type="button"
                  disabled={move.isPending}
                  onClick={() => move.mutate()}
                  className="min-h-9 flex-1 rounded-tile bg-tg-link/15 px-3 text-xs font-medium text-tg-text disabled:opacity-60"
                >
                  {move.isPending
                    ? tx("Отправляем…")
                    : kind === "out"
                      ? tx("Списать")
                      : tx("Оприходовать")}
                </button>
                <button
                  type="button"
                  onClick={() => setKind(null)}
                  className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-hint"
                >
                  {tx("Отмена")}
                </button>
              </div>
            </div>
          )}

          {showHistory && (
            <div className="space-y-1">
              {historyQ.isLoading && (
                <div className="text-2xs text-tg-hint">{tx("Загружаем историю…")}</div>
              )}
              {historyQ.data?.length === 0 && (
                <div className="text-2xs text-tg-hint">{tx("Движений пока нет.")}</div>
              )}
              {(historyQ.data ?? []).map((movement) => (
                <MovementRow key={movement.id} movement={movement} unit={item.unit} />
              ))}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function MovementRow({ movement, unit }: { movement: SupplyMovement; unit: string }) {
  const { tx } = useTx();
  const when = new Date(movement.created_at).toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  const sign = movement.kind === "in" ? "+" : "−";
  return (
    <div className="flex items-start gap-2 text-2xs text-tg-hint">
      <span className={movement.kind === "in" ? "text-status-free" : "text-tg-text"}>
        {sign}
        {formatQty(movement.quantity)} {unit}
      </span>
      <span className="min-w-0 flex-1 truncate">
        {[movement.employee_name, movement.comment].filter(Boolean).join(" · ") ||
          tx("без комментария")}
      </span>
      <span className="shrink-0 tabular-nums">{when}</span>
    </div>
  );
}

function CreateForm({ onDone }: { onDone: () => void }) {
  const { tx } = useTx();
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("шт");
  const [quantity, setQuantity] = useState("0");
  const [minQuantity, setMinQuantity] = useState("0");

  const create = useMutation({
    mutationFn: () =>
      createSupply({
        name: name.trim(),
        unit: unit.trim() || "шт",
        quantity: Number(quantity.replace(",", ".")) || 0,
        min_quantity: Number(minQuantity.replace(",", ".")) || 0,
      }),
    onSuccess: () => {
      haptic("success");
      onDone();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  return (
    <div className="space-y-2 rounded-card bg-tg-secondary-bg/60 p-3">
      <input
        type="text"
        value={name}
        maxLength={160}
        onChange={(event) => setName(event.target.value)}
        placeholder={tx("Название: перчатки, салфетки…")}
        className="min-h-9 w-full rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
      />
      <div className="flex gap-2">
        <label className="flex flex-1 items-center gap-1.5 text-2xs text-tg-hint">
          {tx("Единица")}
          <input
            type="text"
            value={unit}
            maxLength={16}
            onChange={(event) => setUnit(event.target.value)}
            className="min-h-9 w-full min-w-0 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
          />
        </label>
        <label className="flex flex-1 items-center gap-1.5 text-2xs text-tg-hint">
          {tx("Остаток")}
          <input
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            className="min-h-9 w-full min-w-0 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-2xs text-tg-hint">
        {tx("Порог «мало»")}
        <input
          type="number"
          inputMode="decimal"
          step="0.01"
          min="0"
          value={minQuantity}
          onChange={(event) => setMinQuantity(event.target.value)}
          className="min-h-9 w-24 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
        />
      </label>
      <button
        type="button"
        disabled={create.isPending || !name.trim()}
        onClick={() => create.mutate()}
        className="min-h-10 w-full rounded-tile bg-tg-link/15 text-xs font-medium text-tg-text disabled:opacity-50"
      >
        {create.isPending ? tx("Сохраняем…") : tx("Добавить на склад")}
      </button>
    </div>
  );
}

/** Два знака только там, где они есть: «10» читается лучше, чем «10.00». */
function formatQty(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}
