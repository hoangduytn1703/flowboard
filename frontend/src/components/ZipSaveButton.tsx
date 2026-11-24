// "⬇ Tải" — the agent writes the video(s) straight into this machine's save folder (Settings → 🖥 Máy này, else
// Downloads): one video as its own .mp4, several as one .zip. The button follows the save.
//
// The old button was a plain link to GET /api/exports/zip: the agent built the whole archive (ten clips ≈ 800 MB)
// before the first byte, the desktop app showed nothing meanwhile, and the button looked dead — people pressed it
// four times and got four copies (15/11). Now one press starts a save (a second press on the same videos joins it),
// the button shows how far it is, and at the end it offers to show the file. The save goes on when the page is left
// (the "việc đang chạy" badge lists it); the state lives here, outside any component, so coming back shows it.
// With "Hỏi chỗ lưu mỗi lần" on, the computer's folder picker opens first.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { getSaveFolder, getZipSave, pickFolder, revealZipSave, startSave, stopZipSave, type SaveMedia, type ZipSaveJob } from "../api/client";
import { toast } from "../store/toast";
import { announceRunning } from "./BackgroundTasks";
import { StopButton } from "./StopButton";

const POLL_MS = 700;
/** "📂 Mở thư mục" stays next to the button this long after a save. */
const DONE_SHOW_MS = 3 * 60 * 1000;

const jobs = new Map<string, ZipSaveJob>();
/** keys whose start request is on its way (a fast double press must not start twice) */
const starting = new Set<string>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version++;
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

function keyOf(ids: number[], media: SaveMedia[]): string {
  return [...[...new Set(ids)].sort((a, b) => a - b).map(String), ...media.map((m) => `m:${m.media_id}`).sort()].join(",");
}

function gb(n: number): string {
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1).replace(".", ",")} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`;
}

async function follow(key: string, job: ZipSaveJob) {
  let j = job;
  while (j.status === "running") {
    await new Promise((r) => setTimeout(r, POLL_MS));
    try {
      j = await getZipSave(j.id);
    } catch {
      jobs.delete(key); // the agent restarted: the save is gone
      emit();
      return;
    }
    jobs.set(key, j);
    emit();
  }
  if (j.status === "done") {
    const skipped = j.skipped.length ? ` (${j.skipped.length} clip chưa có video bị bỏ qua)` : "";
    toast.success(`Đã lưu ${j.name} (${gb(j.total_bytes)}) vào ${j.folder}${skipped}`);
  } else if (j.status === "error") {
    toast.error(j.error || "Lưu video bị lỗi");
  } else {
    toast.info("Đã dừng lưu video");
  }
}

async function begin(key: string, ids: number[], media: SaveMedia[]) {
  if (starting.has(key)) return;
  starting.add(key);
  emit();
  try {
    let folder = "";
    const where = await getSaveFolder().catch(() => null);
    if (where?.ask) {
      const picked = await pickFolder(where.folder, "Lưu video vào thư mục nào?");
      if (!picked) return; // closed the picker: nothing saved
      folder = picked;
    }
    const job = await startSave({ ids, media, page: window.location.pathname + window.location.search, folder });
    const already = jobs.get(key);
    jobs.set(key, job);
    announceRunning();
    if (!(already && already.id === job.id && already.status === "running")) void follow(key, job);
  } finally {
    starting.delete(key);
    emit();
  }
}

export function SaveButton({ ids = [], media = [], label, className = "qt-btn", title, onDone }: {
  /** clip (board) ids; clips that are not joined yet are skipped by the agent */
  ids?: number[];
  /** videos named by the page itself (not through a clip) */
  media?: SaveMedia[];
  label: string;
  className?: string;
  title?: string;
  /** after a save of exactly these videos ends well (e.g. reload the "chưa tải" list) */
  onDone?: () => void;
}) {
  useSyncExternalStore(subscribe, () => version);
  const key = keyOf(ids, media);
  const job = jobs.get(key);
  const status = job?.status;
  const prev = useRef(status);
  useEffect(() => {
    if (prev.current === "running" && status === "done") onDone?.();
    prev.current = status;
  }, [status, onDone]);

  if (!ids.length && !media.length) return null;
  if (starting.has(key) && job?.status !== "running") {
    return (
      <button type="button" className={className} disabled aria-busy="true">
        <span className="qt-spinner" style={{ display: "inline-block", verticalAlign: "-1px", marginRight: 6 }} />
        Đang bắt đầu…
      </button>
    );
  }
  if (job?.status === "running") {
    const pct = job.total_bytes ? ` · ${job.progress}%` : "";
    return (
      <>
        <button type="button" className={className} disabled aria-busy="true"
                title={job.total_bytes ? `${gb(job.done_bytes)} / ${gb(job.total_bytes)} — lưu vào ${job.folder || "thư mục lưu video"}` : "Đang chuẩn bị"}>
          <span className="qt-spinner" style={{ display: "inline-block", verticalAlign: "-1px", marginRight: 6 }} />
          {job.phase}{pct}
        </button>
        <StopButton stopping={job.stopping} className="qt-btn qt-btn--small qt-btn--ghost"
                    onStop={async () => { jobs.set(key, await stopZipSave(job.id)); emit(); }} />
      </>
    );
  }
  const recent = job?.status === "done" && job.finished_at && Date.now() - job.finished_at * 1000 < DONE_SHOW_MS;
  return (
    <>
      <button type="button" className={className}
              title={title ?? "Lưu video vào thư mục lưu video của máy này (đổi thư mục ở Cài đặt → 🖥 Máy này)"}
              onClick={() => void begin(key, ids, media).catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))}>
        {label}
      </button>
      {recent && (
        <button type="button" className="qt-btn qt-btn--small" title={`${job!.name} — trong ${job!.folder}`}
                onClick={() => void revealZipSave(job!.id).catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))}>
          📂 Mở thư mục
        </button>
      )}
    </>
  );
}

/** The many-clips form ("⬇ Tải N clip"): kept for the pages that pass clip ids. */
export const ZipSaveButton = SaveButton;
