// "✂️ Cắt video" — `/api/cut` (routes/cut.py, services/video_cut.py): links / files → many short videos, no dubbing.
// Every part is a clip ("Clip của tôi") and an editing project (a dub job of kind "cut") opened in the dubbing editor.
import { api, extractErrorMessage } from "./client";
import type { DubCutRow, DubJob } from "./dub";

export type CutHow = "ai" | "prompt" | "even";
export type CutStatus = "queued" | "running" | "review" | "cutting" | "done" | "error";

export interface CutToolStatus {
  /** Whisper (pyvideotrans) on this machine: the AI can pick by what is said */
  whisper: boolean;
  whisper_reason: string;
  remotion: boolean;
  max_minutes: number;
  max_links: number;
  max_parts: number;
  prompt_max: number;
  /** languages offered for the titles the AI writes */
  title_langs?: string[];
  default_min: number;
  default_max: number;
}

export interface CutPartView {
  index: number;
  start: number;
  end: number;
  title: string;
  job_id: string;
  board_id: number | null;
  /** the part's current video: the raw cut until it is exported from the editor */
  media_id: string;
  name?: string;
  /** its editing project's state ("missing" = the project is gone from this machine) */
  status?: string;
  phase?: string;
  progress?: number;
  error?: string | null;
  /** exported from the editor at least once */
  edited?: boolean;
  duration_s?: number;
  lines?: number;
  sub_lang?: string;
}

export interface CutSession {
  id: string;
  run_id: string;
  url: string | null;
  source_media_id: string | null;
  source_url?: string;
  how: CutHow;
  prompt: string;
  min_s: number;
  max_s: number;
  max_parts: number;
  review: boolean;
  channel_id: number | null;
  status: CutStatus;
  phase: string;
  progress: number;
  title: string;
  duration_s: number;
  width: number;
  height: number;
  language: string;
  heard: boolean;
  prepared: boolean;
  lines: number;
  rows: DubCutRow[];
  by: string;
  note: string;
  /** one title for the whole video, when the request asked for one ("Name") */
  name?: string;
  /** the language the AI writes the titles in ("" = what the request says, else Vietnamese) */
  title_lang?: string;
  parts: CutPartView[];
  error: string | null;
  started_at: number;
  position: number;
}

export interface CutStart {
  links: string[];
  media: { media_id: string; name: string }[];
  how: CutHow;
  prompt: string;
  min_s: number;
  max_s: number;
  max_parts: number;
  review: boolean;
  channel_id: number | null;
  title_lang?: string;
  /** a saved "★ Mẫu chỉnh sửa" (frame, background, sticker, blur boxes…) every part is rendered in; null = raw pieces */
  look_preset_id?: number | null;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json() as Promise<T>;
}

export const getCutStatus = () => api<CutToolStatus>("/api/cut/status");
export const listCutSessions = () => api<CutSession[]>("/api/cut/sessions");
export const getCutSession = (id: string) => api<CutSession>(`/api/cut/sessions/${id}`);
export const startCut = (body: CutStart) => post<{ run_id: string; sessions: CutSession[] }>("/api/cut/sessions", body);
export const suggestCut = (id: string, body: { how: CutHow; prompt: string; min_s: number; max_s: number; max_parts: number; title_lang?: string }) =>
  post<{ rows: DubCutRow[]; by: string; note: string; name?: string }>(`/api/cut/sessions/${id}/suggest`, body);
export const cutNow = (id: string, rows: DubCutRow[]) => post<CutSession>(`/api/cut/sessions/${id}/cut`, { rows });
export const stopCut = (id: string) => post<CutSession>(`/api/cut/sessions/${id}/stop`, {});
export const cutAgain = (id: string) => post<CutSession>(`/api/cut/sessions/${id}/again`, {});
export const deleteCutSessions = (ids: string[]) =>
  post<{ deleted: string[]; skipped: { id: string; reason: string }[] }>("/api/cut/sessions/delete", { ids });
/** The parts' editing projects (dub jobs of kind "cut") of a run (links pasted together) or of one video, in cut order. */
export const listCutParts = (q: { run?: string; session?: string }) =>
  api<DubJob[]>(`/api/cut/parts?${q.run ? `run=${encodeURIComponent(q.run)}` : `session=${encodeURIComponent(q.session ?? "")}`}`);
/** The finished video of clips — the dubbing page dubs videos picked from "Clip của tôi". */
export const clipVideos = (boardIds: number[]) =>
  post<{ board_id: number; name: string; media_id: string }[]>("/api/cut/clips", { board_ids: boardIds });

/** A saved cut prompt ("Prompt đã lưu") — kept with the account, so every machine has them. */
export interface CutPrompt { id: string; name: string; text: string }
export const listCutPrompts = () => api<CutPrompt[]>("/api/cut/prompts");
export const saveCutPrompts = (prompts: CutPrompt[]) =>
  api<CutPrompt[]>("/api/cut/prompts", { method: "PUT", body: JSON.stringify({ prompts }) });

const clock = (v: number) => {
  const s = Math.max(0, Math.round(v));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
};
/** ``Name: X | start_1: mm:ss | end_1: mm:ss | title_bottom_1: Y | …`` — the one-line form other clip tools take. */
export function pipeText(name: string, rows: { start: number; end: number; title?: string }[]): string {
  const out = [`Name: ${name.trim() || "Video"}`];
  rows.forEach((r, i) => out.push(`start_${i + 1}: ${clock(r.start)}`, `end_${i + 1}: ${clock(r.end)}`, `title_bottom_${i + 1}: ${(r.title ?? "").trim()}`));
  return out.join(" | ");
}

/** Length presets of one short video (seconds). */
export const LENGTHS: { key: string; label: string; min: number; max: number }[] = [
  { key: "15-30", label: "15–30 giây", min: 15, max: 30 },
  { key: "30-60", label: "30–60 giây", min: 30, max: 60 },
  { key: "60-90", label: "1–1,5 phút", min: 60, max: 90 },
  { key: "90-180", label: "1,5–3 phút", min: 90, max: 180 },
  { key: "180-600", label: "3–10 phút", min: 180, max: 600 },
];

export const PROMPT_IDEAS = [
  "Mỗi đoạn là một mẹo / một ý chính",
  "Chỉ giữ những đoạn hài, bất ngờ nhất",
  "Chỉ giữ phần review sản phẩm, bỏ phần chào hỏi",
  "Mỗi đoạn một câu hỏi và câu trả lời",
  "Cắt theo từng bước hướng dẫn",
];

export const isBusy = (s: CutSession) => s.status === "queued" || s.status === "running" || s.status === "cutting";
