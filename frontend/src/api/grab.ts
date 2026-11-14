// "📡 Cào video kênh" — `/api/grab` (routes/grab.py, services/channel_grab.py): the videos of YouTube / TikTok
// channels listed with views / likes / length / date, picked (by hand, by filters or by the AI) and downloaded so
// "✂️ Cắt video" and "🎙 Lồng tiếng" take them as files.
import { api, extractErrorMessage } from "./client";

export type GrabPlatform = "youtube" | "tiktok" | "douyin" | "bilibili";

export interface GrabStatus {
  /** ``beta`` = still rough; ``note`` = what it covers (Bilibili: bilibili.com only) */
  platforms: { key: GrabPlatform; label: string; example: string; beta?: string; note?: string }[];
  limits: number[];
  /** the most one scan reads ("Tất cả video") */
  max_limit: number;
  /** the ready-made video labels ("Đã xử lý", "Đã đăng"…) */
  mark_presets: string[];
  default_limit: number;
  ytdlp: boolean;
  not_supported: string;
  max_minutes: number;
  pick_max: number;
}

export interface GrabScan {
  status: "running" | "done" | "error";
  phase: string;
  found: number;
  added: number;
  error: string;
  stopping: boolean;
}

export interface GrabChannel {
  id: number;
  platform: GrabPlatform;
  platform_label: string;
  url: string;
  handle: string;
  name: string;
  followers: number | null;
  description: string;
  tags: string[];
  note: string;
  has_avatar: boolean;
  scanned_at: string | null;
  scan_error: string;
  created_at: string | null;
  videos: number;
  downloaded: number;
  /** videos first seen in the newest scan */
  fresh: number;
  /** videos carrying one of the seller's labels */
  marked: number;
  scan: GrabScan | null;
}

export interface GrabVideo {
  id: number;
  channel_id: number;
  url: string;
  title: string;
  kind: "video" | "short";
  duration_s: number | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  published_at: string | null;
  position: number;
  fresh: boolean;
  /** the downloaded file on this machine (null = not here) */
  media_id: string | null;
  downloaded_at: string | null;
  /** downloaded on the other machine: the file is not on this one */
  elsewhere: boolean;
  download: "" | "queued" | "running" | "done";
  download_error: string;
  used: { cut?: string; dub?: string };
  /** the seller's labels ("Đã xử lý", "Đã đăng"…) — kept by the video, so they come back after a rescan */
  marks: string[];
}

export interface GrabMarkTag {
  tag: string;
  videos: number;
  preset: boolean;
}

export interface GrabState {
  scans: Record<string, GrabScan>;
  downloads: Record<string, { status: "queued" | "running"; stopping: boolean }>;
}

async function post<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json() as Promise<T>;
}

export const getGrabStatus = () => api<GrabStatus>("/api/grab/status");
export const listGrabChannels = () => api<GrabChannel[]>("/api/grab/channels");
export const addGrabChannel = (url: string, limit: number, tags: string[] = []) =>
  post<GrabChannel>("/api/grab/channels", { url, limit, tags });
export const editGrabChannel = (id: number, patch: { tags?: string[]; note?: string; name?: string }) =>
  post<GrabChannel>(`/api/grab/channels/${id}`, patch, "PATCH");
export const deleteGrabChannel = (id: number) => api<{ deleted: boolean; videos: number }>(`/api/grab/channels/${id}`, { method: "DELETE" });
export const scanGrabChannel = (id: number, limit: number) => post<GrabChannel>(`/api/grab/channels/${id}/scan`, { limit });
export const stopGrabScan = (id: number) => post<{ ok: boolean }>(`/api/grab/channels/${id}/stop`, {});
export const scanAllGrabChannels = (limit: number) => post<{ channels: number }>("/api/grab/scan-all", { limit });
export const listGrabVideos = () => api<GrabVideo[]>("/api/grab/videos");
export const getGrabState = () => api<GrabState>("/api/grab/state");
export const downloadGrabVideos = (ids: number[]) => post<{ queued: number; skipped: number }>("/api/grab/download", { ids });
export const stopGrabDownloads = (ids: number[] = []) => post<{ stopping: number }>("/api/grab/download/stop", { ids });
/** ``prompts`` = the saved requests afterwards (the one just used goes on top). */
export const pickGrabVideos = (ids: number[], prompt: string) =>
  post<{ picks: { id: number; why: string }[]; note: string; prompts?: string[] }>("/api/grab/pick", { ids, prompt });
/** The account's saved AI requests, newest first — at most 10, the oldest goes when an 11th is saved. */
export const listGrabPrompts = () => api<string[]>("/api/grab/prompts");
export const saveGrabPrompt = (text: string) => post<string[]>("/api/grab/prompts", { text });
export const deleteGrabPrompt = (text: string) => post<string[]>("/api/grab/prompts/delete", { text });
/** The downloaded ones among ``ids`` — what the cut / dubbing pages take as files (`?grab=<ids>`). */
/** ``name`` = the caption made short (no hashtags, ≤ 80 characters); ``title`` = the caption as posted. */
export const grabMedia = (ids: number[]) =>
  post<{ id: number; media_id: string; name: string; title?: string }[]>("/api/grab/media", { ids });
export const markGrabUsed = (ids: number[], tool: "cut" | "dub") => post<{ marked: number }>("/api/grab/used", { ids, tool });
export const listGrabMarks = () => api<GrabMarkTag[]>("/api/grab/marks");
export const setGrabMarks = (ids: number[], add: string[], remove: string[] = []) =>
  post<{ marked: number }>("/api/grab/marks", { ids, add, remove });

/** What became of a downloaded video in a tool (the latest job / cut started from it). */
export interface GrabToolRun {
  state: "running" | "review" | "done" | "error" | "stopped";
  id: string;
  phase: string;
  progress: number;
  error: string;
  at: number;
  /** the page of that job: /tools/dub?job=… or /tools/cut?session=… */
  link: string;
}
export type GrabWork = Record<string, { dub?: GrabToolRun; cut?: GrabToolRun }>;
export const getGrabWork = () => api<GrabWork>("/api/grab/work");

export const grabThumbUrl = (id: number) => `/api/grab/videos/${id}/thumb`;
export const grabAvatarUrl = (id: number) => `/api/grab/channels/${id}/avatar`;

/** 1 234 567 → "1,2 tr", 45 300 → "45,3 N" (how Vietnamese apps write counts). */
export function shortCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const one = (v: number) => v.toFixed(v >= 100 ? 0 : 1).replace(/\.0$/, "").replace(".", ",");
  if (n >= 1e9) return `${one(n / 1e9)} tỷ`;
  if (n >= 1e6) return `${one(n / 1e6)} tr`;
  if (n >= 1e3) return `${one(n / 1e3)} N`;
  return String(n);
}

export function clockOf(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

/** "3 ngày trước", "2 tháng trước" — YouTube's listing only knows the date roughly, so a rough wording fits. */
export function agoOf(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const days = Math.max(0, Math.floor((now - t) / 86400000));
  if (days < 1) return "hôm nay";
  if (days < 2) return "hôm qua";
  if (days < 7) return `${days} ngày trước`;
  if (days < 31) return `${Math.floor(days / 7)} tuần trước`;
  if (days < 365) return `${Math.floor(days / 30)} tháng trước`;
  return `${Math.floor(days / 365)} năm trước`;
}

export function dateOf(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toLocaleDateString("vi-VN") : "";
}
