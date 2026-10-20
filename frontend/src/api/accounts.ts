import { api } from "./client";

/** One connected Flowboard extension = one Chrome profile = one Google
 * account on Flow. Credits and the e-mail are read off the Flow page's
 * account panel, so they are null until the first read lands. */
export interface FlowAccount {
  id: number;
  active: boolean;
  email: string | null;
  credits: number | null;
  tier: string | null;
  version: string | null;
  connected_at: number;
  account_checked_at: number | null;
  account_error: string | null;
  /** The Flow project pinned the last time this account was active. */
  project_id: string | null;
  project_is_pinned: boolean | null;
}

export interface FlowAccountsResponse {
  accounts: FlowAccount[];
  active_id: number | null;
  pinned_project_id: string;
  repinned_project_id?: string | null;
  results?: Record<string, { error?: string; email?: string | null; credits?: number | null }>;
}

export function listFlowAccounts() {
  return api<FlowAccountsResponse>("/api/auth/accounts");
}

export function refreshFlowAccounts() {
  return api<FlowAccountsResponse>("/api/auth/accounts/refresh", { method: "POST" });
}

export function activateFlowAccount(id: number, pinRememberedProject = true) {
  return api<FlowAccountsResponse>(`/api/auth/accounts/${id}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin_remembered_project: pinRememberedProject }),
  });
}

/** Vietnamese text for an account_error code from the agent. */
export function accountErrorText(code: string | null): string | null {
  if (!code) return null;
  switch (code) {
    case "NO_FLOW_TAB":
      return "Chưa mở tab flow.google.com trong Chrome này";
    case "extension_outdated":
      return "Extension bản cũ — Reload ở chrome://extensions";
    case "ACCOUNT_PANEL_NOT_FOUND":
    case "NO_ACCOUNT_BUTTON":
      return "Không đọc được bảng tài khoản trên trang Flow (đăng nhập lại?)";
    case "timeout":
      return "Extension không trả lời";
    default:
      return code;
  }
}
