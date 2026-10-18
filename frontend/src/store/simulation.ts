import { create } from "zustand";

/**
 * Режим проверки: приложение открыто от имени сотрудника в изолированном
 * сеансе. ID сеанса переживает перезапуск мини-аппа (localStorage), иначе
 * индикатор и подмена профиля терялись бы после каждого сворачивания
 * Telegram. Выход всегда идёт через сервер: он удаляет тестовые данные.
 */

export const SIMULATION_STORAGE_KEY = "ghg.simulation.v1";

export interface SimulationSessionState {
  sessionId: number | null;
  subjectName: string;
  departmentName: string | null;
  mode: "new" | "as_is" | null;
}

const EMPTY: SimulationSessionState = {
  sessionId: null,
  subjectName: "",
  departmentName: null,
  mode: null,
};

function readStored(): SimulationSessionState {
  try {
    if (typeof localStorage === "undefined") return EMPTY;
    const raw = localStorage.getItem(SIMULATION_STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<SimulationSessionState>;
    if (typeof parsed.sessionId !== "number" || !parsed.sessionId) return EMPTY;
    return {
      sessionId: parsed.sessionId,
      subjectName: typeof parsed.subjectName === "string" ? parsed.subjectName : "",
      departmentName:
        typeof parsed.departmentName === "string" ? parsed.departmentName : null,
      mode: parsed.mode === "new" || parsed.mode === "as_is" ? parsed.mode : null,
    };
  } catch {
    return EMPTY;
  }
}

function persist(state: SimulationSessionState): void {
  try {
    if (typeof localStorage === "undefined") return;
    if (state.sessionId === null) {
      localStorage.removeItem(SIMULATION_STORAGE_KEY);
      return;
    }
    localStorage.setItem(SIMULATION_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // приватный режим — сеанс просто не переживёт перезапуск
  }
}

interface SimulationStore extends SimulationSessionState {
  start: (data: Omit<SimulationSessionState, "sessionId"> & { sessionId: number }) => void;
  clear: () => void;
}

const initial = readStored();

export const useSimulation = create<SimulationStore>((set) => ({
  ...initial,
  start: (data) => {
    const next: SimulationSessionState = { ...data };
    persist(next);
    set(next);
  },
  clear: () => {
    persist(EMPTY);
    set(EMPTY);
  },
}));
