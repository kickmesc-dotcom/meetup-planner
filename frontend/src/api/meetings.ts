import { api } from "./client";

export interface MeetingAttendee {
  user_id: number;
  rsvp: number; // 0=нет ответа, 1=да, 2=может, 3=нет
}

export interface MeetingDetail {
  id: number;
  created_by: number;
  title: string;
  starts_at: string;
  ends_at: string;
  location: string | null;
  status: string;
  auto_picked: boolean;
  score: number | null;
  attendees: MeetingAttendee[];
  my_rsvp: number;
}

export const fetchMeetings = (from: Date, to: Date) =>
  api<MeetingDetail[]>(
    `/api/meetings?from=${from.toISOString()}&to=${to.toISOString()}`,
  );

export const setRsvp = (meetingId: number, rsvp: number) =>
  api<MeetingDetail>(`/api/meetings/${meetingId}/rsvp`, {
    method: "PATCH",
    body: JSON.stringify({ rsvp }),
  });

export const cancelMeeting = (meetingId: number) =>
  api<void>(`/api/meetings/${meetingId}`, { method: "DELETE" });

export interface AutoPickSlot {
  starts_at: string;
  ends_at: string;
  score: number;
  available_user_ids: number[];
  maybe_user_ids: number[];
}

export interface AutoPickResponse {
  slots: AutoPickSlot[];
}

export interface AutoPickRequest {
  window_start: string;
  window_end: string;
  duration_minutes: number;
  step_minutes: number;
  top_n: number;
}

export const autoPick = (body: AutoPickRequest) =>
  api<AutoPickResponse>("/api/meetings/auto-pick", {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface LoserRoll {
  id: number;
  rolled_at: string;
  rolled_by: number;
  loser_user_id: number;
  reason_text: string | null;
}

export interface LoserRollResponse {
  roll: LoserRoll;
  sent_to_chat: boolean;
}

export interface LoserStats {
  counts: Record<number, number>;
  last: LoserRoll | null;
  cooldown_remaining_seconds: number;
}

export const rollLoser = () =>
  api<LoserRollResponse>("/api/loser/roll", { method: "POST" });

export const fetchLoserStats = () => api<LoserStats>("/api/loser/stats");

export const fetchLoserHistory = (limit = 20) =>
  api<LoserRoll[]>(`/api/loser/history?limit=${limit}`);

export interface PollOption {
  id: number;
  starts_at: string;
  label: string | null;
  voter_user_ids: number[];
}

export interface Poll {
  id: number;
  question: string;
  closes_at: string | null;
  options: PollOption[];
  my_vote_option_id: number | null;
}

export interface PollCreateRequest {
  question: string;
  options: string[]; // ISO datetimes
  closes_in_hours?: number | null;
  chat_id?: number | null;
}

export const createPoll = (body: PollCreateRequest) =>
  api<Poll>("/api/polls", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const fetchPolls = () => api<Poll[]>("/api/polls");

export interface PollAutoPickRequest {
  window_start: string;
  window_end: string;
  duration_minutes: number;
  step_minutes: number;
  top_n: number;
  question?: string;
  closes_in_hours?: number | null;
  chat_id?: number | null;
}

export const createAutoPickPoll = (body: PollAutoPickRequest) =>
  api<Poll>("/api/polls/auto-pick", {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface IcalUrl {
  https: string;
  webcal: string;
}

export const fetchIcalUrl = () => api<IcalUrl>("/api/meetings/ical/url");
