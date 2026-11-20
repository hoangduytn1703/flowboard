import { api } from "./client";

/** One line of the first-run guide (agent: services/setup_status.py). */
export interface SetupStep {
  id: "extension" | "flow" | "project" | "ai" | "product" | "clip";
  required: boolean;
  ok: boolean;
  title: string;
  detail: string;
}

export interface SetupStatus {
  /** every required step is done: a generation can start */
  ready: boolean;
  /** extension connected + a Flow project chosen: enough to send Flow a job */
  can_generate: boolean;
  steps: SetupStep[];
  flow: {
    connected: boolean;
    version: string | null;
    email: string | null;
    credits: number | null;
    tier: string | null;
    project_id: string | null;
    /** the project the Flow tab has open right now, when it is inside one */
    tab_project: string | null;
    plan: string;
    /** the Flow tab's account is not the pinned project's owner: Flow drops every video sent like that */
    mismatch: FlowMismatch | null;
  };
  counts: { products: number; clips: number; channels: number };
  extension_dir: string;
  flow_url: string;
  /** only from ``checkSetup``: what the agent set on its own ("gói Flow Ultra", "dự án Flow đang mở") */
  changed?: string[];
}

/** agent: account_pool.mismatch() */
export interface FlowMismatch {
  /** the account signed in on the Flow tab */
  email: string;
  project_id: string;
  /** the account(s) the pinned project belongs to */
  owners: string[];
  /** a project of ``email`` DFlow can pin instead, when it knows one */
  suggest_project: string | null;
}

export interface CheckOptions {
  /** pin the project the Flow tab has open even when another one is pinned */
  useTabProject?: boolean;
  /** mismatch: pin the project of the tab's account */
  useAccountProject?: boolean;
  /** mismatch: the tab's account may use the pinned project too */
  keepProject?: boolean;
}

export const getSetup = () => api<SetupStatus>("/api/setup/status");

/** Ask the extension to look at the Flow tab again; the agent pins the open project / plan when it can. */
export const checkSetup = (opts: CheckOptions = {}) =>
  api<SetupStatus>("/api/setup/check", {
    method: "POST",
    body: JSON.stringify({
      use_tab_project: !!opts.useTabProject, use_account_project: !!opts.useAccountProject, keep_project: !!opts.keepProject,
    }),
  });

export const openFlowTab = () => api<{ ok: boolean }>("/api/setup/open-flow", { method: "POST" });
