import { api } from "./client";

export interface CloudStatus {
  account: {
    auth: boolean;
    username: string | null;
    since: number | null;
    storage_dir: string;
    backend: "sqlite" | "postgres";
    central_cloud: boolean;
  };
  files: {
    enabled: boolean;
    endpoint: string | null;
    bucket: string | null;
    pending_uploads: number;
    uploaded: number;
    downloaded: number;
    upload_errors: number;
    download_errors: number;
    last_error: string | null;
  };
  central_cloud: boolean;
  /** Phase C: logs in through the DFlow website — the bucket and the move to cloud are the server's business */
  via_api?: boolean;
}

function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  return api<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
}

export function getCloudStatus() {
  return api<CloudStatus>("/api/cloud/status");
}

export function setCloudS3(body: { endpoint: string; bucket: string; keyId: string; secret: string; region?: string }) {
  return send<{ ok: boolean; message: string }>("/api/cloud/s3", "PUT", body);
}

export function syncCloudFiles() {
  return send<{ queued: number; downloaded: number }>("/api/cloud/files/sync", "POST");
}

export function migrateToCloud() {
  return send<{ moved: boolean; schema?: string; tables?: Record<string, number>; reason?: string }>("/api/cloud/migrate", "POST");
}

/** `api()` keeps only the status; this one surfaces the agent's message. */
export async function withMessage<T>(fn: () => Promise<T>, fallback: string): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    throw new Error(err instanceof Error && !/^\d{3} /.test(err.message) ? err.message : fallback);
  }
}
