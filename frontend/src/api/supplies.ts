import { api } from "./client";

/**
 * Склад расходников.
 *
 * Сервер отдаёт остаток числом с двумя знаками: литры и килограммы дробные,
 * а штучные позиции просто не используют дробную часть. Клиент не округляет —
 * иначе 0.75 л превратились бы в 1 л и разошлись бы с историей.
 *
 * `low` считает сервер (остаток ≤ порога): правило должно быть одним для
 * мини-аппа и будущего бота.
 */

export interface Supply {
  id: number;
  name: string;
  unit: string;
  quantity: number;
  min_quantity: number;
  low: boolean;
  /** Потолок списания за смену; `null` — без ограничения. */
  max_out_per_shift: number | null;
  department_id: number | null;
  department: string | null;
  updated_at: string;
}

export interface SupplyMovement {
  id: number;
  kind: "in" | "out";
  quantity: number;
  comment: string | null;
  employee_name: string | null;
  is_inventory: boolean;
  created_at: string;
}

export interface SupplyDiscrepancy {
  supply_id: number;
  supply_name: string;
  unit: string;
  delta: number;
  comment: string | null;
  employee_name: string | null;
  created_at: string;
}

export const fetchSupplies = () => api<Supply[]>("/api/supplies");

export const createSupply = (body: {
  name: string;
  unit?: string;
  quantity?: number;
  min_quantity?: number;
  max_out_per_shift?: number | null;
  department_id?: number | null;
}) =>
  api<Supply>("/api/supplies", { method: "POST", body: JSON.stringify(body) });

export const moveSupply = (
  supplyId: number,
  body: { kind: "in" | "out"; quantity: number; comment?: string | null },
) =>
  api<{ supply: Supply; movement: SupplyMovement; crossed_low: boolean }>(
    `/api/supplies/${supplyId}/movements`,
    { method: "POST", body: JSON.stringify(body) },
  );

/** Сверка: фактический остаток. Расхождение сервер запишет движением. */
export const countSupply = (
  supplyId: number,
  body: { quantity: number; comment?: string | null },
) =>
  api<{ supply: Supply; delta: number; movement: SupplyMovement | null }>(
    `/api/supplies/${supplyId}/count`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const fetchDiscrepancies = () =>
  api<SupplyDiscrepancy[]>("/api/supplies/discrepancies?days=30");

export const fetchSupplyMovements = (supplyId: number) =>
  api<SupplyMovement[]>(`/api/supplies/${supplyId}/movements?limit=20`);
