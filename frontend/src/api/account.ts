import { api } from "./client";

/** The Flowboard login (not the Google / Flow account). */
export interface AccountMe {
  auth: boolean;
  username: string;
  created_at?: string | null;
  backend?: string;
  /** the admin account (the seed account): the only one that manages accounts */
  is_admin?: boolean;
}

/** Like api(), but a failed call throws the agent's own message (`detail`), not "400 Bad Request". */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!res.ok) {
    if (res.status === 401) window.dispatchEvent(new Event("flowboard:unauthorized"));
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function getAccountMe() {
  return api<AccountMe>("/api/account/me");
}

export function loginAccount(username: string, password: string) {
  return api<AccountMe>("/api/account/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logoutAccount() {
  return api<{ ok: boolean }>("/api/account/logout", { method: "POST" });
}

/** Change your own password; your other machines are logged out (`logged_out` = how many). */
export function changeAccountPassword(current: string, next: string) {
  return call<{ ok: boolean; logged_out: number }>("/api/account/password", {
    method: "POST",
    body: JSON.stringify({ current, new: next }),
  });
}

// ── account management (admin only) ─────────────────────────────────────────

export interface ManagedAccount {
  username: string;
  role: "admin" | "user";
  disabled: boolean;
  note: string;
  created_at: string | null;
  /** where its data lives: "postgres" = the cloud database, "sqlite" = one machine */
  backend: string;
  /** logged-in sessions (machines / browsers) */
  sessions: number;
  last_seen: string | null;
  last_host: string | null;
  logged_out?: number;
}

export interface AccountList {
  accounts: ManagedAccount[];
  me: string;
  /** this machine has the cloud database: new accounts can live there */
  cloud: boolean;
  min_password: number;
}

export function listAccounts() {
  return call<AccountList>("/api/admin/accounts");
}

export function createAccount(body: { username: string; password: string; note?: string; cloud?: boolean }) {
  return call<ManagedAccount>("/api/admin/accounts", { method: "POST", body: JSON.stringify(body) });
}

export function updateAccount(username: string, body: { disabled?: boolean; note?: string }) {
  return call<ManagedAccount>(`/api/admin/accounts/${encodeURIComponent(username)}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function resetAccountPassword(username: string, next: string) {
  return call<ManagedAccount>(`/api/admin/accounts/${encodeURIComponent(username)}/password`, {
    method: "POST", body: JSON.stringify({ new: next }),
  });
}

export function logoutAccountEverywhere(username: string) {
  return call<ManagedAccount>(`/api/admin/accounts/${encodeURIComponent(username)}/logout`, { method: "POST" });
}

/** A password that is easy to read out / type: no 0/O, 1/l/I. */
export function randomPassword(length = 10): string {
  const chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const buf = new Uint32Array(length);
  crypto.getRandomValues(buf);
  return Array.from(buf, (n) => chars[n % chars.length]).join("");
}

/** The agent's error text for a failed call (`api()` only keeps the status). */
export async function loginWithMessage(username: string, password: string): Promise<AccountMe> {
  const res = await fetch("/api/account/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

/** UI preferences saved with the account (model picks, UI mode …). */
export type AccountPrefs = Record<string, string | number | boolean>;

export function getAccountPrefs() {
  return api<AccountPrefs>("/api/account/prefs");
}

export function putAccountPrefs(prefs: AccountPrefs) {
  return api<AccountPrefs>("/api/account/prefs", { method: "PUT", body: JSON.stringify(prefs) });
}
