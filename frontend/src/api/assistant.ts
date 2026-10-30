// 🤖 Trợ lý AI — `/api/assistant` (routes/assistant.py): a chat whose replies can start
// background tasks (create_model today) that carry on when the page closes.
import { api } from "./client";

export interface AssistantMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  /** what a reply shows besides text: a picture it made, a link to open, an error mark */
  data: {
    media_id?: string;
    /** every picture the work made (a model, a post's images, a product photo) */
    media_ids?: string[];
    reference_id?: number;
    link?: string;
    link_label?: string;
    /** where to open what was made: one button each */
    links?: { label: string; href: string }[];
    /** a plan that posts publicly by itself: it waits for "✅ Làm luôn" (this task id) */
    confirm?: number;
    error?: boolean;
    canned?: boolean;
  };
  task_id: number | null;
  at: string | null;
}

export interface AssistantTask {
  id: number;
  kind: string;
  status: "pending" | "running" | "done" | "error" | "canceled";
  title: string;
  /** what it is doing now ("Flow đang vẽ ảnh người mẫu…") */
  step: string;
  media_id: string | null;
  reference_id: number | null;
  error: string | null;
  /** the page of what it makes (the running badge opens it) */
  link: string;
  started_at: string | null;
  updated_at: string | null;
}

export interface AssistantState {
  messages: AssistantMessage[];
  tasks: AssistantTask[];
}

export function getAssistant(): Promise<AssistantState> {
  return api<AssistantState>("/api/assistant");
}

export function sendAssistant(message: string): Promise<{ messages: AssistantMessage[]; task: AssistantTask | null }> {
  return api("/api/assistant/chat", { method: "POST", body: JSON.stringify({ message }) });
}

export function clearAssistant(): Promise<{ removed: number }> {
  return api("/api/assistant", { method: "DELETE" });
}

/** Run a plan that waits for the go-ahead (it would post publicly by itself). */
export function confirmAssistantTask(id: number): Promise<{ task: AssistantTask }> {
  return api(`/api/assistant/tasks/${id}/confirm`, { method: "POST" });
}

export function cancelAssistantTask(id: number): Promise<{ ok: boolean }> {
  return api(`/api/assistant/tasks/${id}/cancel`, { method: "POST" });
}
