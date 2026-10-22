import { api } from "./client";

/** The Flowboard login (not the Google / Flow account). */
export interface AccountMe {
  auth: boolean;
  username: string;
  created_at?: string | null;
  backend?: string;
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

export function changeAccountPassword(current: string, next: string) {
  return api<{ ok: boolean }>("/api/account/password", {
    method: "POST",
    body: JSON.stringify({ current, new: next }),
  });
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
