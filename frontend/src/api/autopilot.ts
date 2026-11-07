// "🤖 Tự động đăng" — `/api/autopilot` (routes/autopilot.py, services/autopilot.py): a Facebook Page that posts by
// itself on fixed days and times; each slot's post is written ahead (Claude CLI or Gemini), pictured through Flow
// and put on the calendar as an auto slot. A slot with no post ready by its time is skipped.
import { api } from "./client";
import type { PostBrief } from "./posts";

export type AutoAi = "claude" | "gemini";
export type ProductMode = "none" | "fixed" | "rotate";
/** What a slot got: the run's own state, refined by its calendar slot once the post is ready. */
export type AutoRunStatus =
  | "writing" | "pictures" | "waiting" | "failed" | "skipped" | "missed"
  | "scheduled" | "posting" | "posted" | "post_failed";

export interface AutoRun {
  id: number;
  plan_id: number;
  slot_at: string;
  label: string;
  status: AutoRunStatus;
  post_id: number | null;
  post_title: string;
  images: number;
  episode: number;
  schedule_id: number | null;
  link: string;
  ai: string;
  error: string;
  note: string;
  attempts: number;
  updated_at: string;
}

export interface AutoPlanInput {
  name?: string;
  channel_id: number;
  days: number[];
  times: string[];
  lead_minutes: number;
  brief: PostBrief;
  series: string;
  product_mode: ProductMode;
  product_ids: number[];
  ai: AutoAi;
  fb_story: boolean;
  enabled?: boolean;
}

export interface AutoPlan extends AutoPlanInput {
  id: number;
  name: string;
  channel: string;
  connected: boolean;
  enabled: boolean;
  when: string;
  next: { at: string; label: string; run: AutoRun | null }[];
  runs: AutoRun[];
}

export interface AutopilotStatus {
  ai: Record<AutoAi, boolean>;
  lead_minutes: number;
  max_times: number;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function listAutoPlans(): Promise<AutoPlan[]> {
  return api<AutoPlan[]>("/api/autopilot/plans");
}

export function getAutopilotStatus(): Promise<AutopilotStatus> {
  return api<AutopilotStatus>("/api/autopilot/status");
}

export function createAutoPlan(body: AutoPlanInput): Promise<AutoPlan> {
  return api<AutoPlan>("/api/autopilot/plans", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export function updateAutoPlan(id: number, body: Partial<AutoPlanInput>): Promise<AutoPlan> {
  return api<AutoPlan>(`/api/autopilot/plans/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export function deleteAutoPlan(id: number): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>(`/api/autopilot/plans/${id}`, { method: "DELETE" });
}

/** "⚡ Soạn ngay bài kế tiếp": the next free slot's post is written now. */
export function prepareAutoPlan(id: number): Promise<{ run_id: number; slot_at: string; label: string }> {
  return api(`/api/autopilot/plans/${id}/prepare`, { method: "POST" });
}

/** How the page says a run's state. */
export const RUN_STATUS: Record<AutoRunStatus, { label: string; tone: "busy" | "wait" | "ok" | "bad" | "off" }> = {
  writing: { label: "✍️ AI đang viết", tone: "busy" },
  pictures: { label: "🎨 Đang vẽ ảnh", tone: "busy" },
  waiting: { label: "⏳ Chờ thử lại", tone: "wait" },
  scheduled: { label: "📅 Chờ tới giờ đăng", tone: "wait" },
  posting: { label: "🚀 Đang đăng", tone: "busy" },
  posted: { label: "✓ Đã đăng", tone: "ok" },
  post_failed: { label: "⚠ Đăng lỗi", tone: "bad" },
  failed: { label: "⚠ Soạn lỗi", tone: "bad" },
  skipped: { label: "⏭ Bỏ qua", tone: "off" },
  missed: { label: "💤 Bỏ lỡ (máy tắt)", tone: "off" },
};
