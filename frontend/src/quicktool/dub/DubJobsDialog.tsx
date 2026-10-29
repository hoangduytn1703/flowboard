import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { DubJob } from "../../api/dub";
import { PageEmpty } from "../PageState";

const PER_PAGE = 10;
type Filter = "all" | "done" | "review" | "error" | "working";
const WORKING = ["queued", "running", "rendering"];

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "done", label: "Xong" },
  { key: "review", label: "Chờ sửa" },
  { key: "error", label: "Lỗi" },
  { key: "working", label: "Đang chạy" },
];

function matches(j: DubJob, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "working") return WORKING.includes(j.status);
  return j.status === f;
}

export function jobTitle(j: DubJob): string {
  return j.name || j.title || j.url || "Video lồng tiếng";
}

function source(j: DubJob): string {
  if (!j.url) return "File tải lên";
  try {
    const host = new URL(j.url).hostname.replace(/^www\./, "");
    if (/douyin/.test(host)) return "Douyin";
    if (/tiktok/.test(host)) return "TikTok";
    if (/youtu/.test(host)) return "YouTube";
    if (/facebook|fb\./.test(host)) return "Facebook";
    if (/instagram/.test(host)) return "Instagram";
    return host;
  } catch {
    return "Link";
  }
}

function when(ts?: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const now = new Date();
  const day = `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}${d.getFullYear() !== now.getFullYear() ? `/${d.getFullYear()}` : ""}`;
  return `${day} · ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function length(s: number): string {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s - m * 60)).padStart(2, "0")}`;
}

function StatePill({ j }: { j: DubJob }) {
  if (j.status === "done") return <span className="qt-dubjobs__pill is-done">Xong</span>;
  if (j.status === "review") return <span className="qt-dubjobs__pill is-review">Chờ sửa bản dịch</span>;
  if (j.status === "error") return <span className="qt-dubjobs__pill is-error" title={j.error ?? ""}>Lỗi</span>;
  if (j.status === "queued") return <span className="qt-dubjobs__pill is-working">Chờ đến lượt</span>;
  return <span className="qt-dubjobs__pill is-working">Đang chạy {j.progress}%</span>;
}

/** Page numbers with gaps: 1 … 4 5 6 … 12. */
export function pageList(current: number, pages: number): (number | "gap")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const keep = new Set([1, pages, current - 1, current, current + 1]);
  const out: (number | "gap")[] = [];
  for (let n = 1; n <= pages; n++) {
    if (keep.has(n)) out.push(n);
    else if (out[out.length - 1] !== "gap") out.push("gap");
  }
  return out;
}

/**
 * "Xem tất cả": every dubbed video saved on this machine (and the ones restored
 * from their clips), newest first — search, filter by state, 10 a page.
 */
export function DubJobsDialog({ jobs, onOpen, onClose, onDelete }: {
  /** brief rows (no lines; ``lines`` = their count), newest first */
  jobs: DubJob[];
  onOpen: (jobId: string) => void;
  onClose: () => void;
  /** take these jobs off the list (the page refreshes it); resolves when done */
  onDelete: (ids: string[]) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // the confirm was opened by a row's 🗑 (not the selection): cancelling it also drops that one-row selection
  const [fromTrash, setFromTrash] = useState(false);
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    search.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (confirming) setConfirming(false);  // Esc first backs out of the confirm bar
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, confirming]);
  useEffect(() => setPage(1), [query, filter]);
  // rows that left the list (deleted, or the list refreshed) leave the selection too
  useEffect(() => {
    setPicked((p) => {
      const alive = new Set(jobs.map((j) => j.job_id));
      const next = new Set([...p].filter((id) => alive.has(id)));
      return next.size === p.size ? p : next;
    });
  }, [jobs]);

  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.key, jobs.filter((j) => matches(j, f.key)).length])) as Record<Filter, number>, [jobs]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return jobs.filter((j) => matches(j, filter) && (!q || `${j.name} ${j.title} ${j.url ?? ""}`.toLowerCase().includes(q)));
  }, [jobs, filter, query]);
  const pages = Math.max(1, Math.ceil(shown.length / PER_PAGE));
  const current = Math.min(page, pages);
  const rows = shown.slice((current - 1) * PER_PAGE, current * PER_PAGE);
  const deletable = (j: DubJob) => !WORKING.includes(j.status);
  const pageIds = rows.filter(deletable).map((j) => j.job_id);
  const shownIds = shown.filter(deletable).map((j) => j.job_id);
  const pageAll = pageIds.length > 0 && pageIds.every((id) => picked.has(id));
  const toggle = (id: string) => {
    setConfirming(false);
    setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };
  const togglePage = () => {
    setConfirming(false);
    setPicked((p) => { const n = new Set(p); for (const id of pageIds) { if (pageAll) n.delete(id); else n.add(id); } return n; });
  };
  const pickedJobs = jobs.filter((j) => picked.has(j.job_id));
  const withClip = pickedJobs.filter((j) => j.board_id).length;
  async function remove() {
    setDeleting(true);
    try {
      await onDelete([...picked]);
      setPicked(new Set());
      setConfirming(false);
    } finally {
      setDeleting(false);
    }
  }

  // a portal: the page around it makes its own stacking layer, which drew the cards over the dialog
  return createPortal(
    <div className="project-modal-backdrop" onClick={onClose}>
      <div className="project-modal qt-dubjobs" role="dialog" aria-modal="true" aria-label="Tất cả video đã lồng tiếng" onClick={(e) => e.stopPropagation()}>
        <div className="qt-dubjobs__head">
          <div>
            <h3 className="project-modal__title">Tất cả video đã lồng tiếng</h3>
            <small className="qt-card__hint">{jobs.length} video · mới nhất ở trên · bấm “Mở” để chỉnh tiếp</small>
          </div>
          <button type="button" className="qt-dubjobs__close" aria-label="Đóng" onClick={onClose}>×</button>
        </div>

        <div className="qt-dubjobs__tools">
          <input ref={search} className="qt-dubjobs__search" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="🔍 Tìm theo tên hoặc link…" aria-label="Tìm video" />
          <div className="qt-dubjobs__filters" role="tablist" aria-label="Lọc theo trạng thái">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" role="tab" aria-selected={filter === f.key}
                      className={`qt-chip${filter === f.key ? " qt-chip--on" : ""}`} disabled={f.key !== "all" && !counts[f.key]}
                      onClick={() => setFilter(f.key)}>
                {f.label} <span className="qt-dubjobs__count">{counts[f.key]}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="qt-dubjobs__body">
          {rows.length ? (
            <table className="qt-dubjobs__table">
              <thead>
                <tr>
                  <th className="qt-dubjobs__check">
                    <input type="checkbox" checked={pageAll} disabled={!pageIds.length} onChange={togglePage}
                           aria-label="Chọn cả trang này" title="Chọn cả trang này" />
                  </th>
                  <th>Video</th><th>Trạng thái</th><th>Thời lượng</th><th>Số câu</th><th>Ngày làm</th><th aria-label="Thao tác" />
                </tr>
              </thead>
              <tbody>
                {rows.map((j) => (
                  <tr key={j.job_id} className={picked.has(j.job_id) ? "is-picked" : undefined} onDoubleClick={() => onOpen(j.job_id)}>
                    <td className="qt-dubjobs__check">
                      <input type="checkbox" checked={picked.has(j.job_id)} disabled={!deletable(j)} onChange={() => toggle(j.job_id)}
                             aria-label={`Chọn ${jobTitle(j)}`} title={deletable(j) ? "Chọn để xoá khỏi danh sách" : "Đang chạy — dừng trước rồi xoá"} />
                    </td>
                    <td className="qt-dubjobs__name">
                      <strong title={jobTitle(j)}>{jobTitle(j)}</strong>
                      <small>{source(j)}{j.language ? ` · tiếng ${j.language}` : ""}{j.batch_id ? " · trong một loạt" : ""}</small>
                    </td>
                    <td><StatePill j={j} /></td>
                    <td className="qt-dubjobs__num">{length(j.duration_s)}</td>
                    <td className="qt-dubjobs__num">{j.lines ?? j.segments.length ?? 0}</td>
                    <td className="qt-dubjobs__num">{when(j.started_at)}</td>
                    <td className="qt-dubjobs__act">
                      <div className="qt-dubjobs__btns">
                        <button type="button" className="qt-btn qt-btn--small" onClick={() => onOpen(j.job_id)}>Mở</button>
                        <button type="button" className="qt-dubjobs__trash" disabled={!deletable(j)}
                                title={deletable(j) ? "Xoá khỏi danh sách (video và clip vẫn giữ)" : "Đang chạy — dừng trước rồi xoá"}
                                aria-label={`Xoá ${jobTitle(j)} khỏi danh sách`}
                                onClick={() => { setPicked(new Set([j.job_id])); setFromTrash(true); setConfirming(true); }}>🗑</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <PageEmpty compact icon="🔍" title={jobs.length ? "Không có video nào khớp" : "Chưa có video nào"}>
              {jobs.length ? "Đổi từ khoá hoặc bộ lọc trạng thái." : "Lồng tiếng một video là nó hiện ở đây."}
            </PageEmpty>
          )}
        </div>

        {picked.size > 0 && (
          <div className={`qt-dubjobs__bar${confirming ? " is-confirm" : ""}`} role="region" aria-label="Xoá khỏi danh sách">
            {confirming ? (
              <>
                <span>
                  Xoá <b>{picked.size}</b> mục khỏi danh sách? Chỉ xoá dòng này và file làm việc tạm (giọng đọc, nhạc nền tách ra).
                  {withClip ? ` Video đã xuất và ${withClip} clip trong “Clip của tôi” vẫn giữ nguyên — thả video vào trang là mở lại được.` : " Mục chưa xuất video thì mất luôn bản dịch."}
                </span>
                <div className="qt-dubjobs__barbtns">
                  <button type="button" className="qt-btn qt-btn--small" disabled={deleting}
                          onClick={() => { setConfirming(false); if (fromTrash) { setPicked(new Set()); setFromTrash(false); } }}>Huỷ</button>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={deleting} onClick={() => void remove()}>
                    {deleting ? "Đang xoá…" : `🗑 Xoá ${picked.size} mục`}
                  </button>
                </div>
              </>
            ) : (
              <>
                <span>
                  Đã chọn <b>{picked.size}</b>
                  {shownIds.length > picked.size && shownIds.length > pageIds.length && (
                    <button type="button" className="qt-link" onClick={() => setPicked(new Set(shownIds))}>Chọn cả {shownIds.length} mục đang lọc</button>
                  )}
                  <button type="button" className="qt-link" onClick={() => setPicked(new Set())}>Bỏ chọn</button>
                </span>
                <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => { setFromTrash(false); setConfirming(true); }}>🗑 Xoá khỏi danh sách</button>
              </>
            )}
          </div>
        )}

        {pages > 1 && (
          <nav className="qt-pager qt-dubjobs__pager" aria-label="Phân trang video">
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current <= 1} onClick={() => setPage(current - 1)}>← Trước</button>
            {pageList(current, pages).map((n, i) => (n === "gap"
              ? <span key={`g${i}`} className="qt-pager__info">…</span>
              : <button key={n} type="button" aria-current={n === current ? "page" : undefined}
                        className={`qt-pager__num${n === current ? " qt-pager__num--active" : ""}`} onClick={() => setPage(n)}>{n}</button>))}
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current >= pages} onClick={() => setPage(current + 1)}>Sau →</button>
            <span className="qt-pager__info">{(current - 1) * PER_PAGE + 1}–{Math.min(current * PER_PAGE, shown.length)} / {shown.length}</span>
          </nav>
        )}
      </div>
    </div>,
    document.body,
  );
}
