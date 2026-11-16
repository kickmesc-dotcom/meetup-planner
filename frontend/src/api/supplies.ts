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
  created_at: string;
}

export const fetchSupplies = () => api<Supply[]>("/api/supplies");

export const createSupply = (body: {
  name: string;
  unit?: string;
  quantity?: number;
  min_quantity?: number;
  department_id?: number | null;
}) =>
  api<Supply>("/api/supplies", { method: "POST", body: JSON.stringify(body) });

export const moveSupply = (
  supplyId: number,
  body: { kind: "in" | "out"; quantity: number; comment?: string | null },
) =>
  api<{ supply: Supply; movement: SupplyMovement }>(
    `/api/supplies/${supplyId}/movements`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const fetchSupplyMovements = (supplyId: number) =>
  api<SupplyMovement[]>(`/api/supplies/${supplyId}/movements?limit=20`);
