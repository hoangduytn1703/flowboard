import { api } from "./client";

/** One slot on the posting calendar ("Lịch đăng"). Times are ISO UTC. */
export interface Slot {
  id: number;
  kind: "post" | "clip";
  post_id: number | null;
  board_id: number | null;
  channel_id: number | null;
  scheduled_at: string;
  status: "planned" | "posted" | "failed" | "skipped";
  /** planned and the time has passed */
  due: boolean;
  /** publish through the channel's Facebook Page when the time comes */
  auto: boolean;
  /** how a video goes out on Facebook: a feed post or a Reel */
  fb_format: FbFormat;
  note: string;
  result: { by?: string; post_id?: string; permalink?: string; comment_id?: string; error?: string } | null;
  posted_at: string | null;
  created_at: string | null;
  title: string;
  thumbnail: string | null;
  channel: string;
  platforms: string[];
  /** the channel can auto-publish (Facebook Page connected) */
  fb_connected: boolean;
}

export type FbFormat = "post" | "reel";

/** Can the item go out as a Reel (`/api/schedule/reel-check`)? */
export interface ReelCheck {
  has_video: boolean;
  ok: boolean;
  reason: string | null;
  /** may be turned down by Facebook (e.g. longer than the API's documented 90 s) — said, not blocked */
  warning?: string | null;
}

export function reelCheck(t: { kind: "post" | "clip"; postId?: number | null; boardId?: number | null }): Promise<ReelCheck> {
  const p = new URLSearchParams({ kind: t.kind });
  if (t.postId) p.set("post_id", String(t.postId));
  if (t.boardId) p.set("board_id", String(t.boardId));
  return api<ReelCheck>(`/api/schedule/reel-check?${p}`);
}

export interface SlotSuggestion {
  at: string;
  label: string;
}

export function listSchedule(opts: { from?: Date; to?: Date; channelId?: number | null; status?: string } = {}): Promise<Slot[]> {
  const p = new URLSearchParams();
  if (opts.from) p.set("from", opts.from.toISOString());
  if (opts.to) p.set("to", opts.to.toISOString());
  if (opts.channelId) p.set("channel_id", String(opts.channelId));
  if (opts.status) p.set("status", opts.status);
  const qs = p.toString();
  return api<{ items: Slot[] }>(`/api/schedule${qs ? `?${qs}` : ""}`).then((r) => r.items);
}

export function listDue(): Promise<Slot[]> {
  return api<{ items: Slot[] }>("/api/schedule/due").then((r) => r.items);
}

export function suggestSlots(channelId: number, limit = 6): Promise<SlotSuggestion[]> {
  return api<{ items: SlotSuggestion[] }>(`/api/schedule/suggest?channel_id=${channelId}&limit=${limit}`).then((r) => r.items);
}

export function createSlot(input: {
  kind: "post" | "clip"; post_id?: number | null; board_id?: number | null; channel_id?: number | null;
  at: string; auto?: boolean; note?: string; fb_format?: FbFormat;
}): Promise<Slot> {
  return api<Slot>("/api/schedule", { method: "POST", body: JSON.stringify(input) });
}

export function updateSlot(id: number, patch: {
  at?: string; channel_id?: number | null; auto?: boolean; note?: string; status?: Slot["status"]; fb_format?: FbFormat;
}): Promise<Slot> {
  return api<Slot>(`/api/schedule/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function deleteSlot(id: number): Promise<{ ok: true }> {
  return api<{ ok: true }>(`/api/schedule/${id}`, { method: "DELETE" });
}

export function publishSlot(id: number): Promise<Slot> {
  return api<Slot>(`/api/schedule/${id}/publish`, { method: "POST" });
}

/** "T3 28/10 · 20:00" in Vietnam time. */
export function slotLabel(iso: string): string {
  const d = new Date(iso);
  const wd = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"][d.getDay()];
  return `${wd} ${d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" })} · ${d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}`;
}

/** The value a `datetime-local` input wants, in local time. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
