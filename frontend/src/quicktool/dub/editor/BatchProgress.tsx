import { useEffect } from "react";
import type { DubJob } from "../../../api/dub";
import { StopButton } from "../../../components/StopButton";

const WORKING = ["queued", "running", "rendering"];
type RowState = "todo" | "queued" | "working" | "done" | "error" | "skipped";

export interface BatchRun {
  /** the clips this run touches, in batch order */
  ids: string[];
  /** each clip's ``started_at`` before the run: a clip whose value changed has been sent to the agent */
  before: Record<string, number | undefined>;
}

function stateOf(j: DubJob, run: BatchRun, sending: boolean): RowState {
  const sent = j.started_at !== run.before[j.job_id];
  if (j.status === "queued") return "queued";
  if (WORKING.includes(j.status)) return "working";
  if (!sent) return sending ? "todo" : "skipped";
  return j.status === "error" ? "error" : "done";
}
const pctOf = (j: DubJob, st: RowState) => (st === "done" || st === "error" || st === "skipped" ? 100 : st === "working" ? Math.max(1, Math.min(99, j.progress || 0)) : 0);

/** How a run stands: overall percent, what is finished, whether anything still works. */
export function batchSummary(jobs: DubJob[], run: BatchRun, sending: boolean) {
  const rows = jobs.filter((j) => run.ids.includes(j.job_id)).map((j) => { const st = stateOf(j, run, sending); return { job: j, st, pct: pctOf(j, st) }; });
  const total = rows.length || 1;
  return {
    rows,
    percent: Math.round(rows.reduce((n, r) => n + r.pct, 0) / total),
    done: rows.filter((r) => r.st === "done").length,
    failed: rows.filter((r) => r.st === "error").length,
    skipped: rows.filter((r) => r.st === "skipped").length,
    active: sending || rows.some((r) => r.st === "todo" || r.st === "queued" || r.st === "working"),
  };
}

const LABEL: Record<RowState, string> = {
  todo: "chờ gửi", queued: "chờ đến lượt", working: "đang xuất", done: "✓ xong", error: "⚠ lỗi", skipped: "bỏ qua (đang bận)",
};

/**
 * "⇪ Áp cho cả loạt" at work: covers the editor (nothing can be changed half-way) and says, clip by clip, what is
 * waiting, what is being exported (with its percent) and what is done — one bar for the whole run on top.
 */
export function BatchProgress({ jobs, run, sending, currentId, noun, onStopAll, onClose }: {
  jobs: DubJob[];
  run: BatchRun;
  sending: boolean;
  currentId: string;
  /** "video" (cut parts) or "clip" (dubbed batch) */
  noun: string;
  onStopAll: () => void;
  onClose: () => void;
}) {
  const s = batchSummary(jobs, run, sending);
  // finished clean: the cover lifts by itself; with a failure it stays until read
  useEffect(() => {
    if (s.active || s.failed) return;
    const t = window.setTimeout(onClose, 2200);
    return () => window.clearTimeout(t);
  }, [s.active, s.failed]); // eslint-disable-line react-hooks/exhaustive-deps

  const finished = s.rows.length - s.rows.filter((r) => r.st === "todo" || r.st === "queued" || r.st === "working").length;
  return (
    <div className="dx-batch" role="dialog" aria-modal="true" aria-label="Đang áp cho cả loạt" aria-live="polite">
      <div className="dx-batch__box">
        <div className="dx-batch__head">
          <strong>{s.active ? `⇪ Đang áp kiểu chỉnh cho ${s.rows.length} ${noun}` : s.failed ? `Đã áp xong — ${s.failed} ${noun} lỗi` : `✓ Đã áp xong cho ${s.rows.length} ${noun}`}</strong>
          <span className="dx-batch__pct">{s.percent}%</span>
        </div>
        <div className="dx-batch__bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={s.percent}>
          <span style={{ width: `${s.percent}%` }} className={s.active ? "is-live" : ""} />
        </div>
        <p className="dx-batch__sum">
          {finished}/{s.rows.length} {noun} xong{s.failed ? ` · ${s.failed} lỗi` : ""}{s.skipped ? ` · ${s.skipped} bỏ qua` : ""}
          {s.active ? " — xuất lần lượt từng cái. Trình chỉnh sửa tạm khoá tới khi xong; rời trang cũng không sao, việc vẫn chạy." : ""}
        </p>
        <ol className="dx-batch__list">
          {s.rows.map((r, i) => (
            <li key={r.job.job_id} className={`is-${r.st}`}>
              <span className="dx-batch__n">{jobs.findIndex((j) => j.job_id === r.job.job_id) + 1 || i + 1}</span>
              <span className="dx-batch__name" title={r.job.name || r.job.title}>
                {(r.job.name || r.job.title || "Video")}{r.job.job_id === currentId ? <em> · đang mở</em> : null}
              </span>
              <span className="dx-batch__mini"><i style={{ width: `${r.pct}%` }} /></span>
              <span className="dx-batch__st" title={r.st === "error" ? r.job.error : undefined}>
                {r.st === "working" ? `${LABEL.working} ${r.pct}%` : LABEL[r.st]}
              </span>
            </li>
          ))}
        </ol>
        <div className="dx-batch__foot">
          {s.active
            ? <StopButton label="Dừng tất cả" onStop={onStopAll} />
            : <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={onClose}>Đóng</button>}
        </div>
      </div>
    </div>
  );
}
