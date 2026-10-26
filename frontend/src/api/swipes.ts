import { api } from "./client";

/** The LLM's breakdown of a post / video that did well. */
export interface SwipeAnalysis {
  title: string;
  summary: string;
  hook_type: string;
  hook: string;
  structure: string[];
  why_it_works: string[];
  triggers: string[];
  format: string;
  cta: string;
  /** a reusable Vietnamese template with [placeholders] */
  skeleton: string;
  tags: string[];
  media_id?: string;
}

export interface Swipe {
  id: number;
  kind: "post" | "video";
  url: string;
  platform: string;
  title: string;
  text: string;
  analysis: SwipeAnalysis | null;
  tags: string[];
  uses: number;
  created_at: string | null;
}

export const HOOK_TYPE_LABEL: Record<string, string> = {
  question: "Câu hỏi", surprise: "Sự thật bất ngờ", pain: "Nỗi khổ quen thuộc", number: "Con số", story: "Kể chuyện",
  contrarian: "Ngược số đông", visual: "Hình ảnh gây chú ý", other: "Khác",
};

export function listSwipes(): Promise<Swipe[]> {
  return api<Swipe[]>("/api/swipes");
}

export function analyzeSwipe(input: { url?: string; text?: string }): Promise<Swipe> {
  return api<Swipe>("/api/swipes/analyze", { method: "POST", body: JSON.stringify(input) });
}

export function deleteSwipe(id: number): Promise<{ ok: true }> {
  return api<{ ok: true }>(`/api/swipes/${id}`, { method: "DELETE" });
}

export type AdaptResult =
  | { as: "post"; post_id: number; title: string; body: string; reply: string }
  | { as: "clip"; board_id: number; name: string; template_id: string; tailored: boolean };

export function adaptSwipe(id: number, input: {
  as: "post" | "clip"; channel_id: number; product_id?: number | null; kind?: string; template_id?: string | null; wish?: string;
}): Promise<AdaptResult> {
  return api<AdaptResult>(`/api/swipes/${id}/adapt`, { method: "POST", body: JSON.stringify(input) });
}
