import { api } from "./client";

/** Старт сеанса: теневой профиль создаётся на сервере и живёт до выхода. */
export interface SimulationStartResult {
  id: number;
  shadow_employee_id: number;
  subject_employee_id: number;
  subject_name: string;
  department_name: string | null;
  mode: "new" | "as_is";
  started_at: string;
}

export interface SimulationExitResult {
  tasks: number;
  runs: number;
  issues: number;
  already_ended: boolean;
}

export interface SimulationActive {
  id: number;
  subject_name: string;
  department_name: string | null;
  mode: "new" | "as_is";
  started_at: string;
}

export const startSimulation = (employeeId: number, mode: "new" | "as_is") =>
  api<SimulationStartResult>("/api/admin/simulation", {
    method: "POST",
    body: JSON.stringify({ employee_id: employeeId, mode }),
  });

export const exitSimulation = (sessionId: number) =>
  api<SimulationExitResult>(`/api/admin/simulation/${sessionId}/exit`, {
    method: "POST",
  });

export const fetchActiveSimulation = () =>
  api<SimulationActive | null>("/api/admin/simulation/active");
