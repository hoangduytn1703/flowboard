import { api } from "./client";

/** The Flowboard login (not the Google / Flow account). */
export interface AccountMe {
  auth: boolean;
  username: string;
  created_at?: string | null;
  backend?: string;
  /** the admin account (the seed account): the only one that manages accounts */
  is_admin?: boolean;
  /** the account's plan ("gói"); the admin's is "Toàn quyền". `trial` = the built-in "Dùng thử"; `expires_at` = when the plan
   * (trial or a paid term) runs out — null = forever */
  plan?: { id: string; name: string; trial?: boolean; expires_at?: string | null };
  /** feature keys the plan includes (see lib/features.ts); missing = an older agent, everything allowed */
  features?: string[];
  /** what the account filled in on "Tài khoản của tôi" */
  profile?: AccountProfile;
  /** Phase C: the DFlow website this machine logs in through (account admin, sign-up, renewals) — null on the direct line */
  site?: SiteLinks | null;
}

export interface SiteLinks {
  url: string;
  host: string;
  account?: string;
  admin?: string;
  signup?: string;
  forgot?: string;
}

export interface AccountProfile {
  display_name: string;
  phone: string;
  email: string;
  contact: string;
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

/** "Tài khoản của tôi": name to show, phone, email, how to reach you. Returns the new /me. */
export function saveProfile(profile: AccountProfile) {
  return call<AccountMe>("/api/account/profile", { method: "PUT", body: JSON.stringify(profile) });
}

/** This account's upgrade requests, newest first (the transaction history). */
export function listMyUpgrades() {
  return call<{ requests: UpgradeRequest[] }>("/api/account/upgrades");
}

/** Log this account out on every other machine / browser (this one stays in). */
export function logoutOthers() {
  return call<{ ok: boolean; logged_out: number }>("/api/account/logout-others", { method: "POST" });
}

/** Naive-UTC time from the agent → Date. */
export function agentDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "còn 5 ngày" / "còn 3 giờ" / "đã hết hạn" for a trial end. */
export function timeLeft(iso: string | null | undefined): { text: string; days: number; over: boolean } {
  const d = agentDate(iso);
  if (!d) return { text: "", days: Infinity, over: false };
  const ms = d.getTime() - Date.now();
  if (ms <= 0) return { text: "đã hết hạn", days: 0, over: true };
  const hours = ms / 3_600_000;
  if (hours < 24) return { text: `còn ${Math.max(1, Math.ceil(hours))} giờ`, days: hours / 24, over: false };
  return { text: `còn ${Math.ceil(hours / 24)} ngày`, days: hours / 24, over: false };
}

export function dayText(iso: string | null | undefined): string {
  const d = agentDate(iso);
  if (!d) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
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
  /** plan id; null = the default plan */
  plan: string | null;
  /** the trial ends then (naive UTC); null = no end */
  plan_expires: string | null;
  /** the trial has ended: the account cannot log in until extended / moved to a plan */
  expired: boolean;
  display_name: string;
  logged_out?: number;
  /** the admin's signature over this account's rights */
  license?: SignState;
  /** the row says something else than the signature (edited by hand — the signature wins) */
  tampered?: boolean;
}

export interface AccountList {
  accounts: ManagedAccount[];
  me: string;
  /** this machine has the cloud database: new accounts can live there */
  cloud: boolean;
  min_password: number;
  /** signed licences (agent licensing.py): active = rights come from the admin's signatures; can_sign = this machine has the key */
  licensing?: { active: boolean; strict: boolean; can_sign: boolean; key_path: string; fingerprint: string };
}

/** "ok" = signed by the admin; "missing" = never signed; "invalid" = changed after signing (edited by hand) */
export type SignState = "ok" | "missing" | "invalid";

export function listAccounts() {
  return call<AccountList>("/api/admin/accounts");
}

/** months = a paid term (0 = forever), days = the trial's length */
export function createAccount(body: { username: string; password: string; note?: string; cloud?: boolean; plan?: string; months?: number; days?: number }) {
  return call<ManagedAccount>("/api/admin/accounts", { method: "POST", body: JSON.stringify(body) });
}

/** plan + months (0 = forever) or days (trial); stack = add onto the time left on the same plan; expires_on = "YYYY-MM-DD" */
export function updateAccount(username: string, body: { disabled?: boolean; note?: string; plan?: string; months?: number; days?: number; stack?: boolean; expires_on?: string }) {
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

/** Trial: starts over from today. Paid plan: `months` more on top of the time left (0 = forever). */
export function extendPlan(username: string, body: { months?: number; days?: number } = {}) {
  return call<ManagedAccount>(`/api/admin/accounts/${encodeURIComponent(username)}/extend`, { method: "POST", body: JSON.stringify(body) });
}

// ── plans ("gói") — admin only ──────────────────────────────────────────────

export interface PlanFeature {
  key: string;
  icon: string;
  label: string;
  desc: string;
}

export interface Plan {
  id: string;
  name: string;
  features: string[];
  /** the trial only: how many days it lasts */
  days?: number;
  /** paid plans: the terms it is sold for (1 month 49k, 1 year 490k, forever 980k…); none = "liên hệ" */
  terms?: PlanTerm[];
}

export interface PlansData {
  /** in the order shown everywhere; the trial is always first */
  plans: Plan[];
  /** plan id new accounts get (always the trial) */
  default: string;
  features: PlanFeature[];
  /** accounts per plan id (the admin not counted) */
  counts: Record<string, number>;
  max_plans: number;
  trial_id: string;
  /** the lengths a trial can have */
  trial_days: number[];
  /** the terms a paid plan can be sold / given for, in months; 0 = forever */
  term_months: number[];
  /** the stored plans vs the admin's signature */
  signed?: SignState;
  can_sign?: boolean;
}

export function getPlans() {
  return call<PlansData>("/api/admin/plans");
}

/** Replace every plan in this order (a new plan has no id yet); accounts on a removed plan move to the trial. */
export function savePlans(plans: Plan[]) {
  return call<PlansData>("/api/admin/plans", { method: "PUT", body: JSON.stringify({ plans }) });
}

// ── upgrades by bank transfer (checked by hand) ─────────────────────────────

export interface UpgradeRequest {
  id: number;
  username: string;
  plan_id: string;
  plan_name: string;
  amount: number;
  /** the term bought; 0 = forever */
  months: number;
  term: string;
  content: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  created_at: string | null;
  decided_at: string | null;
}

export interface UpgradeOffer {
  current: { id: string; name: string; trial?: boolean; expires_at?: string | null };
  plans: (Plan & { terms: PlanTerm[]; current: boolean })[];
  features: PlanFeature[];
  /** the admin has set up the receiving bank account */
  ready: boolean;
  note: string;
  pending: UpgradeRequest | null;
}

/** One way a paid plan is sold: for `months` (0 = forever) at `price`; `list_price` (struck through) when on sale. */
export interface PlanTerm {
  months: number;
  price: number;
  list_price: number;
}

export interface UpgradeQuote {
  plan_id: string;
  plan_name: string;
  months: number;
  term: string;
  amount: number;
  list_price: number;
  /** buying more of the plan the account is on (time left is kept) */
  renew: boolean;
  /** the end date this buys; null = forever */
  ends_at: string | null;
  content: string;
  bank_name: string;
  account_no: string;
  account_name: string;
  note: string;
  /** NAPAS VietQR payload — draw it as a QR code */
  qr: string;
}

export function getUpgradeOffer() {
  return call<UpgradeOffer>("/api/account/upgrade");
}

export function quoteUpgrade(planId: string, months: number) {
  return call<UpgradeQuote>("/api/account/upgrade/quote", { method: "POST", body: JSON.stringify({ plan_id: planId, months }) });
}

/** "Tôi đã chuyển khoản": a request the admin checks against the bank statement. */
export function fileUpgrade(planId: string, months: number) {
  return call<UpgradeRequest>("/api/account/upgrade/request", { method: "POST", body: JSON.stringify({ plan_id: planId, months }) });
}

export function cancelUpgrade() {
  return call<{ ok: boolean }>("/api/account/upgrade/cancel", { method: "POST" });
}

export interface BillingSettings {
  bank_bin: string;
  account_no: string;
  account_name: string;
  /** {username}, {plan} and {term} are filled in */
  template: string;
  note: string;
}

export interface BillingData {
  settings: BillingSettings;
  banks: { bin: string; code: string; name: string }[];
  ready: boolean;
  default_template: string;
  text_max: number;
  term_months: number[];
  /** the stored bank settings vs the admin's signature */
  signed?: SignState;
  can_sign?: boolean;
  bank_name: string;
  sample: { plan_name: string; term: string; amount: number; content: string; qr: string };
  requests: UpgradeRequest[];
}

export function getBilling() {
  return call<BillingData>("/api/admin/billing");
}

export function saveBilling(settings: BillingSettings) {
  return call<BillingData>("/api/admin/billing", { method: "PUT", body: JSON.stringify(settings) });
}

export function decideUpgrade(id: number, approve: boolean) {
  return call<BillingData>(`/api/admin/billing/requests/${id}/${approve ? "approve" : "reject"}`, { method: "POST" });
}

export function vnd(amount: number): string {
  return `${amount.toLocaleString("vi-VN")}đ`;
}

export function termLabel(months: number): string {
  if (!months) return "Vĩnh viễn";
  return months % 12 === 0 ? `${months / 12} năm` : `${months} tháng`;
}

/** "-17%" off the list price (0 when not on sale). */
export function discountPct(t: PlanTerm): number {
  return t.list_price > t.price ? Math.round((1 - t.price / t.list_price) * 100) : 0;
}

/** Same day `months` later (the 31st → the last day of a shorter month). */
export function addMonths(start: Date, months: number): Date {
  const d = new Date(start);
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + months);
  d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
  return d;
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

/** Login page of a fresh install: is this machine on the cloud account store yet (no login needed). */
export interface ConnectStatus {
  /** the desktop app (restarts itself) vs start.ps1 */
  app: boolean;
  cloud: boolean;
  /** a line is saved but the agent has not restarted with it */
  restart_pending: boolean;
  /** Phase C: logs in through the DFlow website — no line to paste; sign-up happens there */
  site?: SiteLinks | null;
}

export function getConnectStatus() {
  return call<ConnectStatus>("/api/app/connect");
}

/** Paste the cloud line before logging in: tested, saved, then the app restarts (`restarting`). */
export function connectCloud(line: string) {
  return call<{ ok: boolean; restarting: boolean }>("/api/app/connect", {
    method: "POST", body: JSON.stringify({ central_db_url: line }),
  });
}

/** UI preferences saved with the account (model picks, UI mode …). */
export type AccountPrefs = Record<string, string | number | boolean>;

export function getAccountPrefs() {
  return api<AccountPrefs>("/api/account/prefs");
}

export function putAccountPrefs(prefs: AccountPrefs) {
  return api<AccountPrefs>("/api/account/prefs", { method: "PUT", body: JSON.stringify(prefs) });
}
