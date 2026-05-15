export type Status = 1 | 2 | 3; // 1=free, 2=maybe, 3=busy

export interface User {
  id: number;
  telegram_id: number;
  display_name: string;
  username: string | null;
  avatar_url: string | null;
  color_hex: string;
  timezone: string;
  created_at: string;
  is_admin?: boolean;
}

export interface AvailabilityRange {
  id: number;
  user_id: number;
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  status: Status;
  confidence: number;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface NewAvailabilityRange {
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  status: Status;
  confidence: number;
  note?: string | null;
}
