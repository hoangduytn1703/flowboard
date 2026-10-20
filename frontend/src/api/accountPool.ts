import { api } from "./client";

/** One Google account in the switch list: its own Flow project, the last
 * credit balance read off the Flow tab, and whether it was found dry. */
export interface PoolAccount {
  email: string;
  project_id: string | null;
  label: string;
  credits: number | null;
  credits_at: number | null;
  exhausted_at: number | null;
  enabled: boolean;
  tier: string | null;
  added_at: number;
}

export interface PendingSwitch {
  from_email: string | null;
  to_email: string;
  project_id: string;
  cost: number;
  since: number;
  reason: string;
  seen_at: number | null;
  tab_opened: boolean;
}

export interface PoolStatus {
  auto: boolean;
  accounts: PoolAccount[];
  active_email: string | null;
  pinned_project_id: string;
  pending: PendingSwitch | null;
  last_switch: PendingSwitch | null;
}

export function getPool() {
  return api<PoolStatus>("/api/auth/pool");
}

export function upsertPoolAccount(body: { email: string; project_id?: string | null; label?: string; enabled?: boolean }) {
  return api<PoolStatus>("/api/auth/pool/accounts", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function removePoolAccount(email: string) {
  return api<PoolStatus>(`/api/auth/pool/accounts/${encodeURIComponent(email)}`, { method: "DELETE" });
}

export function setPoolAuto(auto: boolean) {
  return api<PoolStatus>("/api/auth/pool/auto", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto }),
  });
}

export function switchPoolAccount(email: string) {
  return api<PoolStatus>("/api/auth/pool/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export function checkPool() {
  return api<{ ok: boolean; switched?: boolean; email?: string | null; credits?: number | null; error?: string; status: PoolStatus }>(
    "/api/auth/pool/check",
    { method: "POST" },
  );
}

export function openPoolFlowTab(email?: string) {
  return api<{ ok: boolean; email: string }>("/api/auth/pool/open-tab", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(email ? { email } : {}),
  });
}

export function dismissPoolSwitch() {
  return api<PoolStatus>("/api/auth/pool/dismiss", { method: "POST" });
}
