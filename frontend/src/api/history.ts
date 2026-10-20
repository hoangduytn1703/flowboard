// Job history — `/api/history` (routes/history.py). Read-only projection of
// the Request table with the clip / node joined in and a credit estimate.
import { api, createRequest, type RequestDTO } from "./client";

export type HistoryStatus = "queued" | "running" | "done" | "failed" | "canceled" | "timeout";

export interface HistoryRow {
  id: number;
  type: string;
  type_label_vi: string;
  status: HistoryStatus | string;
  created_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  board: { id: number; name: string } | null;
  node: { id: number; short_id: string; title: string | null; type: string } | null;
  summary: string | null;
  media_ids: string[];
  thumbnail: string | null;
  credits_estimate: number | null;
  error: string | null;
  can_retry: boolean;
}

export interface HistoryDetail extends HistoryRow {
  params: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface HistoryPage {
  items: HistoryRow[];
  next_before_id: number | null;
}

export interface HistoryBucket {
  jobs: number;
  done: number;
  error: number;
  credits_estimate: number;
}

export interface HistorySummary {
  today: HistoryBucket;
  week: HistoryBucket;
  total_media: number;
}

export interface HistoryQuery {
  limit?: number;
  before_id?: number | null;
  /** Comma-separated request types. */
  type?: string;
  /** Comma-separated statuses; `error` covers failed + timeout. */
  status?: string;
  board_id?: number | null;
}

export function listHistory(q: HistoryQuery = {}): Promise<HistoryPage> {
  const p = new URLSearchParams();
  if (q.limit) p.set("limit", String(q.limit));
  if (q.before_id) p.set("before_id", String(q.before_id));
  if (q.type) p.set("type", q.type);
  if (q.status) p.set("status", q.status);
  if (q.board_id) p.set("board_id", String(q.board_id));
  const qs = p.toString();
  return api<HistoryPage>(`/api/history${qs ? `?${qs}` : ""}`);
}

export function getHistorySummary(): Promise<HistorySummary> {
  return api<HistorySummary>("/api/history/summary");
}

export function getHistoryDetail(id: number): Promise<HistoryDetail> {
  return api<HistoryDetail>(`/api/history/${id}`);
}

/**
 * Resubmit a finished job through the ordinary worker queue. Same type,
 * node and params; `__request_id` is the worker's own stamp and must not
 * be carried over.
 */
export function retryHistoryRow(detail: HistoryDetail): Promise<RequestDTO> {
  const params: Record<string, unknown> = { ...detail.params };
  delete params["__request_id"];
  return createRequest({
    type: detail.type,
    node_id: detail.node?.id ?? undefined,
    params,
  });
}

// ── labels / formatting (Vietnamese) ────────────────────────────────────────

/** Types offered in the filter dropdown, in display order. */
export const HISTORY_TYPE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "gen_image", label: "Tạo ảnh" },
  { value: "gen_video,gen_video_omni", label: "Tạo video" },
  { value: "edit_image", label: "Sửa ảnh" },
  { value: "export_video", label: "Ghép video" },
  { value: "vision,auto_prompt,auto_prompt_batch,narration,planner,storyboard_split,chat_agent", label: "AI (prompt / lời đọc)" },
  { value: "upload,upload_url", label: "Tải ảnh lên" },
];

export const HISTORY_STATUS_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "done", label: "Xong" },
  { value: "running,queued", label: "Đang chạy" },
  { value: "error", label: "Lỗi" },
  { value: "canceled", label: "Đã huỷ" },
];

export const STATUS_LABEL_VI: Record<string, string> = {
  queued: "Chờ",
  running: "Đang chạy",
  done: "Xong",
  failed: "Lỗi",
  error: "Lỗi",
  timeout: "Quá giờ",
  canceled: "Đã huỷ",
};

export type StatusTone = "muted" | "running" | "ok" | "fail";

export function statusTone(status: string): StatusTone {
  if (status === "done") return "ok";
  if (status === "running" || status === "queued") return "running";
  if (status === "failed" || status === "error" || status === "timeout") return "fail";
  return "muted";
}

export function statusLabelVi(status: string): string {
  return STATUS_LABEL_VI[status] ?? status;
}

/** "3 phút trước" — Vietnamese relative time; falls back to the date past a week. */
export function relativeTimeVi(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const sec = Math.round((now - t) / 1000);
  if (sec < 10) return "vừa xong";
  if (sec < 60) return `${sec} giây trước`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} phút trước`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} giờ trước`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day} ngày trước`;
  return new Date(iso).toLocaleDateString("vi-VN");
}

export function formatDurationVi(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const min = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${min} ph ${s} s`;
}

export function formatCredits(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("vi-VN");
}

const VIDEO_TYPES = new Set(["gen_video", "gen_video_omni", "export_video"]);

/** Whether a row's media is video (for the thumbnail element and the download name). */
export function isVideoType(type: string): boolean {
  return VIDEO_TYPES.has(type);
}
