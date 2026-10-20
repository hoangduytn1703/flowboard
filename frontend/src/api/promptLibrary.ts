import { api } from "./client";

export type PromptKind = "image" | "video" | "narration";

export interface SavedPrompt {
  id: number;
  kind: PromptKind;
  title: string;
  text: string;
  tags: string[];
  source_board_id: number | null;
  uses: number;
  created_at: string;
}

export const PROMPT_KIND_LABEL: Record<PromptKind, string> = {
  image: "Mô tả ảnh",
  video: "Chuyển động",
  narration: "Lời thoại",
};

export function listSavedPrompts(kind?: PromptKind, q?: string) {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (q) params.set("q", q);
  const qs = params.toString();
  return api<SavedPrompt[]>(`/api/prompt-library${qs ? `?${qs}` : ""}`);
}

export function savePrompt(body: { kind: PromptKind; text: string; title?: string; tags?: string[]; source_board_id?: number | null }) {
  return api<SavedPrompt>("/api/prompt-library", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchSavedPrompt(id: number, body: { title?: string; text?: string; tags?: string[] }) {
  return api<SavedPrompt>(`/api/prompt-library/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteSavedPrompt(id: number) {
  return api<void>(`/api/prompt-library/${id}`, { method: "DELETE" });
}

export function useSavedPrompt(id: number) {
  return api<SavedPrompt>(`/api/prompt-library/${id}/use`, { method: "POST" });
}
