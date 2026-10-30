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
  /** once published: its numbers on Facebook (read back by "Đồng bộ từ Facebook") */
  stats?: FbStats | null;
}

/** A post's numbers on Facebook, read back by "Đồng bộ từ Facebook". Views need the token's read_insights;
 * a Reel adds plays, watch time and `retention` (41 points: share still watching from 0 to 100 % of the video). */
export interface FbStats {
  views?: number;
  viewers?: number;
  clicks?: number;
  reactions?: number;
  comments?: number;
  shares?: number;
  plays?: number;
  replays?: number;
  avg_watch_s?: number;
  watch_time_s?: number;
  followers?: number;
  length_s?: number;
  retention?: number[];
  /** ISO UTC: when they were read */
  at?: string;
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

/** A post that went up BY HAND on a connected Facebook Page (read back from the Graph API). */
export interface FbHandPost {
  id: number;
  channel_id: number;
  channel: string;
  fb_id: string;
  /** ISO UTC: when it went out */
  at: string;
  kind: string;
  reel: boolean;
  title: string;
  message: string;
  permalink: string;
  /** a Facebook CDN picture URL ("" = none) */
  picture: string;
  /** the saved post (Bài đã lưu) whose text it carries */
  post_id: number | null;
  post_title: string;
  stats: FbStats | null;
}

/** When each connected Page was last read back. */
export interface FbSyncState {
  channel_id: number;
  channel: string;
  at: string | null;
  error: string | null;
  manual?: number | null;
  fetched?: number | null;
  /** the posts were read but their numbers were not (e.g. no read_insights) */
  stats_error?: string | null;
}

export function listFacebookPosts(opts: { from: Date; to: Date; channelId?: number | null }): Promise<{ items: FbHandPost[]; channels: FbSyncState[] }> {
  const p = new URLSearchParams({ from: opts.from.toISOString(), to: opts.to.toISOString() });
  if (opts.channelId) p.set("channel_id", String(opts.channelId));
  return api(`/api/schedule/facebook?${p}`);
}

export interface FbSyncResult {
  busy: boolean;
  channels: (FbSyncState & { matched?: number; added?: number; removed?: number; skipped_slots?: number })[];
}

/** Read the connected Pages back now; `maxAge` (s) = only the ones read longer ago than that. */
export function syncFacebook(opts: { channelId?: number; maxAge?: number } = {}): Promise<FbSyncResult> {
  return api<FbSyncResult>("/api/schedule/facebook/sync", {
    method: "POST",
    body: JSON.stringify({ channel_id: opts.channelId ?? null, max_age: opts.maxAge ?? null }),
  });
}
