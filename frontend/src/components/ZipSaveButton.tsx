// "⬇ Tải N clip" — the agent writes the .zip straight into this machine's Downloads folder and the button follows it.
//
// The old button was a plain link to GET /api/exports/zip: the agent built the whole archive (ten clips ≈ 800 MB)
// before the first byte, the desktop app showed nothing meanwhile, and the button looked dead — people pressed it
// four times and got four copies (15/11). Now one press starts a save (a second press on the same clips joins it),
// the button shows how far it is, and at the end it offers to show the file. The save goes on when the page is left
// (the "việc đang chạy" badge lists it); the state lives here, outside any component, so coming back shows it.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { getZipSave, revealZipSave, startZipSave, stopZipSave, type ZipSaveJob } from "../api/client";
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

function keyOf(ids: number[]): string {
  return [...new Set(ids)].sort((a, b) => a - b).join(",");
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
    const skipped = j.skipped.length ? ` (${j.skipped.length} clip chưa ghép bị bỏ qua)` : "";
    toast.success(`Đã lưu ${j.name} (${gb(j.total_bytes)}) vào thư mục ${j.folder}${skipped}`);
  } else if (j.status === "error") {
    toast.error(j.error || "Lưu file .zip bị lỗi");
  } else {
    toast.info("Đã dừng lưu file .zip");
  }
}

async function begin(key: string, ids: number[]) {
  if (starting.has(key)) return;
  starting.add(key);
  emit();
  try {
    const job = await startZipSave(ids, window.location.pathname + window.location.search);
    const already = jobs.get(key);
    jobs.set(key, job);
    announceRunning();
    if (!(already && already.id === job.id && already.status === "running")) void follow(key, job);
  } finally {
    starting.delete(key);
    emit();
  }
}

export function ZipSaveButton({ ids, label, className = "qt-btn", title, onDone }: {
  /** clip (board) ids; clips that are not joined yet are skipped by the agent */
  ids: number[];
  label: string;
  className?: string;
  title?: string;
  /** after a save of exactly these clips ends well (e.g. reload the "chưa tải" list) */
  onDone?: () => void;
}) {
  useSyncExternalStore(subscribe, () => version);
  const key = keyOf(ids);
  const job = jobs.get(key);
  const status = job?.status;
  const prev = useRef(status);
  useEffect(() => {
    if (prev.current === "running" && status === "done") onDone?.();
    prev.current = status;
  }, [status, onDone]);

  if (!ids.length) return null;
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
                title={job.total_bytes ? `${gb(job.done_bytes)} / ${gb(job.total_bytes)} — lưu vào thư mục Tải về` : "Đang chuẩn bị"}>
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
              title={title ?? "Lưu một file .zip các clip đã ghép vào thư mục Tải về (Downloads) của máy này"}
              onClick={() => void begin(key, ids).catch((e: unknown) => toast.error(e instanceof Error ? e.message : String(e)))}>
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
