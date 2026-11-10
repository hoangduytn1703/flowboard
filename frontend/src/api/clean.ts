/** Client for `/api/clean` — the "Xoá chữ / logo / watermark" tool.
 *  The video goes up through the reference-video upload route (same asset
 *  store); every other call takes the resulting `media_id`. */

export interface CleanVideo {
  media_id: string;
  url: string;
  duration_s: number;
  width: number;
  height: number;
  has_audio?: boolean;
}

/** Fractions 0–1 of the decoded frame. */
export interface CleanBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface CleanBand {
  y0: number;
  y1: number;
  hits?: number;
}

export type EraseMethod = "delogo" | "blur";

export interface AiStatus {
  available: boolean;
  reason?: string;
  python?: string;
  root?: string;
  model_cached?: boolean;
}

export interface CleanJob {
  /** the video being cleaned (GET /api/clean/jobs/{id} returns it) */
  source_media_id?: string;
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  media_id?: string;
  url?: string;
  duration_s?: number | null;
  error?: string;
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : body;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") return detail[0].msg;
  } catch {
    /* not JSON */
  }
  return `${res.status} ${res.statusText}`;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await errorText(res));
  return res.json() as Promise<T>;
}


export async function uploadCleanVideo(file: File): Promise<CleanVideo> {
  const form = new FormData();
  form.append("file", file);
  const up = await json<{ media_id: string; duration_s: number | null; width: number | null; height: number | null }>(
    await fetch("/api/reference-video/upload", { method: "POST", body: form }),
  );
  // The upload reports the stored size; `info` reports the display size
  // (rotation applied), which is what the canvas and ffmpeg both use.
  return cleanInfo(up.media_id);
}

export async function cleanInfo(mediaId: string): Promise<CleanVideo> {
  return json<CleanVideo>(await fetch(`/api/clean/${encodeURIComponent(mediaId)}/info`));
}

export function frameUrl(mediaId: string, t: number): string {
  return `/api/clean/${encodeURIComponent(mediaId)}/frame?t=${Math.max(0, t).toFixed(2)}`;
}

export async function aiStatus(): Promise<AiStatus> {
  return json<AiStatus>(await fetch("/api/clean/ai-status"));
}

export async function detectBands(mediaId: string): Promise<{ bands: CleanBand[]; info: string; preview_t: number }> {
  return json(await fetch(`/api/clean/${encodeURIComponent(mediaId)}/detect`, { method: "POST" }));
}

export async function eraseBoxes(mediaId: string, boxes: CleanBox[], method: EraseMethod): Promise<CleanVideo> {
  return json<CleanVideo>(
    await fetch(`/api/clean/${encodeURIComponent(mediaId)}/erase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "box", boxes, method }),
    }),
  );
}

/** Fast fallback: the detected bands blurred with ffmpeg only. */
export async function blurBands(mediaId: string, bands: CleanBand[]): Promise<CleanVideo> {
  return json<CleanVideo>(
    await fetch(`/api/clean/${encodeURIComponent(mediaId)}/erase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "ai-blur", bands: bands.map((b) => ({ y0: b.y0, y1: b.y1 })) }),
    }),
  );
}

export async function startAiErase(mediaId: string, bands: CleanBand[]): Promise<{ job_id: string }> {
  return json(
    await fetch(`/api/clean/${encodeURIComponent(mediaId)}/erase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "ai", bands: bands.map((b) => ({ y0: b.y0, y1: b.y1 })) }),
    }),
  );
}

export async function getCleanJob(jobId: string): Promise<CleanJob> {
  return json<CleanJob>(await fetch(`/api/clean/jobs/${encodeURIComponent(jobId)}`));
}

export async function stopCleanJob(jobId: string): Promise<CleanJob> {
  return json<CleanJob>(await fetch(`/api/clean/jobs/${encodeURIComponent(jobId)}/stop`, { method: "POST" }));
}
