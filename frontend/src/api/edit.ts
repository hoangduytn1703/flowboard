// "🎞 Chỉnh sửa video" — /api/edit (routes/edit.py, services/video_edit.py): the list of videos being edited.
// A video on it is a dubbing-editor project (DubJob); the editor itself works through api/dub.ts.
import { api } from "./client";

export interface HearState {
  /** "" = not asked; wait = behind another video; run; done; error */
  state: "" | "wait" | "run" | "done" | "error";
  progress: number;
  error: string;
}

export interface EditItem {
  job_id: string;
  name: string;
  /** import = a file / a clip brought in here; cut = a part of "✂️ Cắt video"; dub = a dubbed video */
  origin: "import" | "cut" | "dub";
  status: string;
  phase: string;
  progress: number;
  error: string | null;
  stopping: boolean;
  duration_s: number | null;
  width: number;
  height: number;
  /** the video as it is now (the export once there is one, the file that came in before) */
  media_id: string | null;
  /** its clip in "Clip của tôi" (an import has none until its first export) */
  board_id: number | null;
  lines: number;
  /** exported from the editor at least once */
  edited: boolean;
  started_at: number;
  hear: HearState;
}

const post = <T,>(path: string, body: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body) });

export const EDIT_PATH = "/tools/edit";
/** How many videos one editor session takes (the agent's cap too). */
export const MAX_EDIT_TOGETHER = 60;

export const listEditItems = () => api<{ items: EditItem[]; max_import: number }>("/api/edit/items");
export const importEditFiles = (media: { media_id: string; name: string }[]) =>
  post<{ job_ids: string[]; errors: { name: string; error: string }[] }>("/api/edit/import", { media });
export const importEditClips = (boardIds: number[]) =>
  post<{ job_ids: string[]; errors: { name: string; error: string }[] }>("/api/edit/clips", { board_ids: boardIds });
export const addEditJobs = (jobIds: string[]) => post<{ job_ids: string[] }>("/api/edit/add", { job_ids: jobIds });
export const removeEditJobs = (jobIds: string[]) =>
  post<{ removed: string[]; kept: { job_id: string; why: string }[] }>("/api/edit/remove", { job_ids: jobIds });

export const hearEditJob = (id: string) => post<HearState>(`/api/edit/jobs/${id}/hear`, {});
export const getEditHear = (id: string) => api<HearState>(`/api/edit/jobs/${id}/hear`);
export const stopEditHear = (id: string) => post<HearState>(`/api/edit/jobs/${id}/hear/stop`, {});

/** The editor with these videos side by side (the select "Video n/N", "⇪ Áp cho cả loạt"); opens on ``first``. */
export function editPath(jobIds: string[], first?: string): string {
  const list = Array.from(new Set(jobIds.filter(Boolean))).slice(0, MAX_EDIT_TOGETHER);
  if (!list.length) return EDIT_PATH;
  const open = first && list.includes(first) ? first : list[0];
  return `${EDIT_PATH}?jobs=${encodeURIComponent(list.join(","))}&job=${encodeURIComponent(open)}`;
}
