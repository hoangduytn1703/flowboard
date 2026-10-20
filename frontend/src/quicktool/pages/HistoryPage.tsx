// /history — every worker job (image, video, export, AI calls) with the clip
// it belongs to, its media (downloadable), status, duration and a credit
// estimate. Read-only except "Thử lại", which resubmits a generation through
// POST /api/requests. Renders inside the quicktool layout like ProductsPage.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listBoards, mediaUrl, type Board } from "../../api/client";
import {
  HISTORY_STATUS_OPTIONS,
  HISTORY_TYPE_OPTIONS,
  formatCredits,
  formatDurationVi,
  getHistoryDetail,
  getHistorySummary,
  isVideoType,
  listHistory,
  relativeTimeVi,
  retryHistoryRow,
  statusLabelVi,
  statusTone,
  type HistoryDetail,
  type HistoryRow,
  type HistorySummary,
} from "../../api/history";
import { tierLabel, useFlowCredits } from "../../components/credits";
import "../history.css";

const PAGE_SIZE = 50;
/** Re-poll the list while something is still queued / running. */
const LIVE_POLL_MS = 5000;

function useTitle(title: string) {
  useEffect(() => {
    const prev = document.title;
    document.title = `${title} · Flowboard`;
    return () => { document.title = prev; };
  }, [title]);
}

/** Trigger a browser download for every media id (same-origin `/media/<id>`). */
function downloadMedia(ids: string[], video: boolean) {
  ids.forEach((id, i) => {
    setTimeout(() => {
      const a = document.createElement("a");
      a.href = mediaUrl(id);
      a.download = `${id.slice(0, 12)}.${video ? "mp4" : "png"}`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    }, i * 350);
  });
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// ── page ────────────────────────────────────────────────────────────────────

export function HistoryPage() {
  const navigate = useNavigate();
  useTitle("Lịch sử");

  const [summary, setSummary] = useState<HistorySummary | null>(null);
  const [boards, setBoards] = useState<Board[]>([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [boardFilter, setBoardFilter] = useState<number | null>(null);

  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [retrying, setRetrying] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const flow = useFlowCredits();
  // Ignore responses from a filter set the user has already moved on from.
  const reqSeq = useRef(0);

  const loadSummary = useCallback(() => {
    getHistorySummary().then(setSummary).catch(() => { /* strip is optional */ });
  }, []);

  const loadFirst = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError(null);
    try {
      const page = await listHistory({
        limit: PAGE_SIZE,
        type: typeFilter || undefined,
        status: statusFilter || undefined,
        board_id: boardFilter,
      });
      if (seq !== reqSeq.current) return;
      setRows(page.items);
      setNextBefore(page.next_before_id);
    } catch (err) {
      if (seq !== reqSeq.current) return;
      setError(`Không tải được lịch sử: ${errorText(err)}`);
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [typeFilter, statusFilter, boardFilter]);

  const loadMore = useCallback(async () => {
    if (!nextBefore || loadingMore) return;
    const seq = reqSeq.current;
    setLoadingMore(true);
    try {
      const page = await listHistory({
        limit: PAGE_SIZE,
        before_id: nextBefore,
        type: typeFilter || undefined,
        status: statusFilter || undefined,
        board_id: boardFilter,
      });
      if (seq !== reqSeq.current) return;
      setRows((prev) => {
        const seen = new Set(prev.map((r) => r.id));
        return [...prev, ...page.items.filter((r) => !seen.has(r.id))];
      });
      setNextBefore(page.next_before_id);
    } catch (err) {
      setError(`Không tải thêm được: ${errorText(err)}`);
    } finally {
      setLoadingMore(false);
    }
  }, [nextBefore, loadingMore, typeFilter, statusFilter, boardFilter]);

  useEffect(() => {
    listBoards().then(setBoards).catch(() => { /* filter stays empty */ });
  }, []);
  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { void loadFirst(); }, [loadFirst]);

  // Live refresh while a job is in flight; also keeps "x phút trước" moving.
  const hasLive = rows.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    const t = setInterval(() => {
      setNow(Date.now());
      if (hasLive) {
        void loadFirst();
        loadSummary();
      }
    }, hasLive ? LIVE_POLL_MS : 30_000);
    return () => clearInterval(t);
  }, [hasLive, loadFirst, loadSummary]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(t);
  }, [notice]);

  const retry = useCallback(async (row: HistoryRow) => {
    if (retrying !== null) return;
    setRetrying(row.id);
    try {
      const detail = await getHistoryDetail(row.id);
      if (!detail.can_retry) {
        setNotice("Không thể chạy lại: cảnh của việc này đã bị xoá.");
        return;
      }
      const cost = detail.credits_estimate;
      const costLine = cost === null
        ? "Chưa rõ số credit sẽ tốn."
        : cost === 0
          ? "Việc này không tốn credit Flow."
          : `Ước tính tốn ~${formatCredits(cost)} credit Flow.`;
      const balance = typeof flow.credits === "number"
        ? `Số dư hiện tại: ${formatCredits(flow.credits)} credit (gói ${tierLabel(flow.tier, flow.sku)}).`
        : "Chưa đọc được số dư credit.";
      const ok = window.confirm(
        `Chạy lại "${detail.type_label_vi}" cho ${detail.node?.title || detail.node?.short_id || "cảnh này"}?\n\n${costLine}\n${balance}`,
      );
      if (!ok) return;
      const created = await retryHistoryRow(detail);
      setNotice(`Đã đưa vào hàng đợi (việc #${created.id}).`);
      await loadFirst();
      loadSummary();
    } catch (err) {
      setNotice(`Chạy lại thất bại: ${errorText(err)}`);
    } finally {
      setRetrying(null);
    }
  }, [retrying, flow.credits, flow.tier, flow.sku, loadFirst, loadSummary]);

  const boardOptions = useMemo(
    () => [...boards].sort((a, b) => b.id - a.id),
    [boards],
  );

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Lịch sử tạo</span>
      </header>
      <div className="qt-home">
        <div className="hist">
          <SummaryStrip summary={summary} />

          {notice && <div className="qt-banner qt-banner--busy">{notice}</div>}
          {error && (
            <div className="qt-banner qt-banner--error">
              {error}
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => { void loadFirst(); }}>
                Thử tải lại
              </button>
            </div>
          )}

          <div className="hist__filters">
            <label className="qt-field">
              <span>Loại việc</span>
              <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">Tất cả</option>
                {HISTORY_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label className="qt-field">
              <span>Trạng thái</span>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">Tất cả</option>
                {HISTORY_STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label className="qt-field">
              <span>Clip</span>
              <select
                value={boardFilter ?? ""}
                onChange={(e) => setBoardFilter(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Mọi clip</option>
                {boardOptions.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </label>
            <span className="hist__filters__spacer" />
            <span className="hist__count">{loading ? "" : `${rows.length} việc${nextBefore ? "+" : ""}`}</span>
            <button
              type="button"
              className="qt-btn qt-btn--small qt-btn--ghost"
              onClick={() => { void loadFirst(); loadSummary(); }}
              disabled={loading}
            >
              Làm mới
            </button>
          </div>

          {loading ? (
            <div className="hist__list">
              {Array.from({ length: 6 }, (_, i) => <SkeletonRow key={i} />)}
            </div>
          ) : rows.length === 0 ? (
            <div className="qt-empty qt-empty--big">
              {typeFilter || statusFilter || boardFilter
                ? "Không có việc nào khớp bộ lọc."
                : "Chưa có việc nào. Tạo clip đầu tiên ở mục Công cụ nhanh."}
            </div>
          ) : (
            <div className="hist__list">
              {rows.map((row) => (
                <Row
                  key={row.id}
                  row={row}
                  now={now}
                  retrying={retrying === row.id}
                  onOpenClip={(id) => navigate(`/clips/${id}`)}
                  onDetail={() => setDetailId(row.id)}
                  onRetry={() => { void retry(row); }}
                />
              ))}
            </div>
          )}

          {!loading && nextBefore && (
            <div className="hist__more">
              <button type="button" className="qt-btn" onClick={() => { void loadMore(); }} disabled={loadingMore}>
                {loadingMore ? <><span className="qt-spinner" /> Đang tải…</> : "Tải thêm"}
              </button>
            </div>
          )}
        </div>
      </div>

      {detailId !== null && (
        <DetailModal
          id={detailId}
          onClose={() => setDetailId(null)}
          onOpenClip={(id) => { setDetailId(null); navigate(`/clips/${id}`); }}
          onRetry={(row) => { setDetailId(null); void retry(row); }}
        />
      )}
    </>
  );
}

export default HistoryPage;

// ── pieces ──────────────────────────────────────────────────────────────────

function SummaryStrip({ summary }: { summary: HistorySummary | null }) {
  const bucket = (b: HistorySummary["today"] | undefined, title: string, eyebrow: string) => (
    <div className="qt-card">
      <div className="qt-card__head">
        <span className="qt-card__eyebrow">{eyebrow}</span>
        <span className="qt-card__title">{title}</span>
      </div>
      <div className="qt-stats">
        <div className="qt-stat"><strong>{b ? b.jobs : "–"}</strong><span>việc</span></div>
        <div className="qt-stat"><strong>{b ? b.done : "–"}</strong><span>xong</span></div>
        <div className={`qt-stat${b && b.error > 0 ? " hist__stat--err" : ""}`}>
          <strong>{b ? b.error : "–"}</strong><span>lỗi</span>
        </div>
        <div className="qt-stat hist__stat--credit">
          <strong>{b ? `~${formatCredits(b.credits_estimate)}` : "–"}</strong><span>credit</span>
        </div>
      </div>
    </div>
  );
  return (
    <div className="hist__strip">
      {bucket(summary?.today, "Hôm nay", "Thống kê")}
      {bucket(summary?.week, "7 ngày qua", "Thống kê")}
      <div className="qt-card">
        <div className="qt-card__head">
          <span className="qt-card__eyebrow">Kho</span>
          <span className="qt-card__title">Media đã tạo</span>
        </div>
        <div className="qt-stats">
          <div className="qt-stat"><strong>{summary ? summary.total_media : "–"}</strong><span>ảnh / video</span></div>
        </div>
        <p className="qt-card__hint">Credit là ước tính theo giá Flow, không phải số Flow trừ thật.</p>
      </div>
    </div>
  );
}

function SkeletonRow() {
  return (
    <div className="hist-row hist-row--skeleton" aria-hidden="true">
      <div className="hist-row__thumb"><span className="qt-skeleton qt-skeleton--thumb" /></div>
      <div className="hist-row__main">
        <span className="qt-skeleton qt-skeleton--line qt-skeleton--short" />
        <span className="qt-skeleton qt-skeleton--line" />
        <span className="qt-skeleton qt-skeleton--line qt-skeleton--short" />
      </div>
      <div />
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone = statusTone(status);
  return (
    <span className={`hist-pill hist-pill--${tone}`}>
      {tone === "running" && <span className="qt-spinner" />}
      {statusLabelVi(status)}
    </span>
  );
}

function CreditCell({ value }: { value: number | null }) {
  if (value === null) return <span className="hist-credit hist-credit--free" title="Chưa rõ">— credit</span>;
  if (value === 0) return <span className="hist-credit hist-credit--free">0 credit</span>;
  return <span className="hist-credit" title="Ước tính theo giá Flow">~{formatCredits(value)} credit</span>;
}

function Thumb({ row, size }: { row: HistoryRow; size: "row" | "modal" }) {
  const video = isVideoType(row.type);
  if (!row.thumbnail) {
    return <div className="hist-row__thumb" aria-hidden="true">{video ? "🎬" : row.type.startsWith("gen_") || row.type === "edit_image" ? "🖼" : "✦"}</div>;
  }
  const url = mediaUrl(row.thumbnail);
  return (
    <div className="hist-row__thumb">
      {video ? <video src={url} muted playsInline preload="metadata" /> : <img src={url} alt="" loading="lazy" />}
      {size === "row" && row.media_ids.length > 1 && (
        <span className="hist-row__thumb-count">{row.media_ids.length}</span>
      )}
    </div>
  );
}

interface RowProps {
  row: HistoryRow;
  now: number;
  retrying: boolean;
  onOpenClip(boardId: number): void;
  onDetail(): void;
  onRetry(): void;
}

function Row({ row, now, retrying, onOpenClip, onDetail, onRetry }: RowProps) {
  const tone = statusTone(row.status);
  const cls = `hist-row${tone === "fail" ? " hist-row--fail" : tone === "running" ? " hist-row--running" : ""}`;
  const when = new Date(row.created_at).toLocaleString("vi-VN");
  return (
    <div className={cls}>
      <Thumb row={row} size="row" />
      <div className="hist-row__main">
        <div className="hist-row__top">
          <span className="hist-row__type">{row.type_label_vi}</span>
          <StatusPill status={row.status} />
          {row.board && (
            <a
              className="hist-row__clip"
              href={`/clips/${row.board.id}`}
              title={row.board.name}
              onClick={(e) => { e.preventDefault(); onOpenClip(row.board!.id); }}
            >
              {row.board.name}
            </a>
          )}
          {row.node && (
            <span className="hist-row__node">· {row.node.title || row.node.short_id}</span>
          )}
        </div>
        <div className={`hist-row__summary${row.summary ? "" : " hist-row__summary--empty"}`} title={row.summary ?? ""}>
          {row.summary ?? "(không có mô tả)"}
        </div>
        {row.error && tone === "fail" && (
          <div className="hist-row__error" title={row.error}>{row.error}</div>
        )}
        <div className="hist-row__meta">
          <span title={when}>{relativeTimeVi(row.created_at, now)}</span>
          <span>· {formatDurationVi(row.duration_ms)}</span>
          <span>· <CreditCell value={row.credits_estimate} /></span>
          {row.media_ids.length > 0 && <span>· {row.media_ids.length} media</span>}
        </div>
      </div>
      <div className="hist-row__actions">
        {row.media_ids.length > 0 && (
          <button
            type="button"
            className="qt-btn qt-btn--small"
            onClick={() => downloadMedia(row.media_ids, isVideoType(row.type))}
            title={row.media_ids.length > 1 ? `Tải ${row.media_ids.length} file` : "Tải file về máy"}
          >
            Tải về{row.media_ids.length > 1 ? ` (${row.media_ids.length})` : ""}
          </button>
        )}
        {row.board && (
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => onOpenClip(row.board!.id)}>
            Mở clip
          </button>
        )}
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={onDetail}>
          Chi tiết
        </button>
        {row.can_retry && (
          <button
            type="button"
            className="qt-btn qt-btn--small qt-btn--accent"
            onClick={onRetry}
            disabled={retrying || tone === "running"}
            title="Gửi lại việc này với cùng prompt và cài đặt"
          >
            {retrying ? <><span className="qt-spinner" /> Đang gửi…</> : "Thử lại"}
          </button>
        )}
      </div>
    </div>
  );
}

interface DetailModalProps {
  id: number;
  onClose(): void;
  onOpenClip(boardId: number): void;
  onRetry(row: HistoryRow): void;
}

function DetailModal({ id, onClose, onOpenClip, onRetry }: DetailModalProps) {
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setErr(null);
    getHistoryDetail(id)
      .then((d) => { if (alive) setDetail(d); })
      .catch((e) => { if (alive) setErr(errorText(e)); });
    return () => { alive = false; };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const video = detail ? isVideoType(detail.type) : false;

  return (
    <div
      className="hist-modal__backdrop"
      role="presentation"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="hist-modal" role="dialog" aria-modal="true" aria-label="Chi tiết việc">
        <div className="hist-modal__head">
          <span className="hist-modal__title">
            {detail ? `Việc #${detail.id} — ${detail.type_label_vi}` : "Đang tải…"}
          </span>
          {detail && <StatusPill status={detail.status} />}
          <button type="button" className="hist-modal__close" onClick={onClose} aria-label="Đóng">×</button>
        </div>

        {err && <div className="qt-banner qt-banner--error">Không tải được chi tiết: {err}</div>}

        {detail && (
          <>
            <dl className="hist-modal__grid">
              <dt>Clip</dt>
              <dd>
                {detail.board ? (
                  <a href={`/clips/${detail.board.id}`} onClick={(e) => { e.preventDefault(); onOpenClip(detail.board!.id); }}>
                    {detail.board.name}
                  </a>
                ) : "—"}
              </dd>
              <dt>Cảnh</dt>
              <dd>{detail.node ? `${detail.node.title || "(không tên)"} · ${detail.node.short_id} · ${detail.node.type}` : "—"}</dd>
              <dt>Bắt đầu</dt>
              <dd>{new Date(detail.created_at).toLocaleString("vi-VN")}</dd>
              <dt>Kết thúc</dt>
              <dd>{detail.finished_at ? new Date(detail.finished_at).toLocaleString("vi-VN") : "—"}</dd>
              <dt>Thời gian chạy</dt>
              <dd>{formatDurationVi(detail.duration_ms)}</dd>
              <dt>Credit ước tính</dt>
              <dd><CreditCell value={detail.credits_estimate} /></dd>
              <dt>Mô tả</dt>
              <dd>{detail.summary ?? "—"}</dd>
            </dl>

            {detail.error && (
              <div className="hist-modal__error">{detail.error}</div>
            )}

            {detail.media_ids.length > 0 && (
              <div className="hist-modal__media">
                {detail.media_ids.map((mid) => (
                  <a key={mid} href={mediaUrl(mid)} target="_blank" rel="noopener noreferrer" title={mid}>
                    {video
                      ? <video src={mediaUrl(mid)} muted playsInline preload="metadata" />
                      : <img src={mediaUrl(mid)} alt="" loading="lazy" />}
                  </a>
                ))}
              </div>
            )}

            <details>
              <summary>Tham số gửi đi (params)</summary>
              <pre>{JSON.stringify(detail.params, null, 2)}</pre>
            </details>
            <details>
              <summary>Kết quả (result)</summary>
              <pre>{JSON.stringify(detail.result, null, 2)}</pre>
            </details>

            <div className="hist-modal__foot">
              {detail.media_ids.length > 0 && (
                <button type="button" className="qt-btn qt-btn--small" onClick={() => downloadMedia(detail.media_ids, video)}>
                  Tải về ({detail.media_ids.length})
                </button>
              )}
              {detail.board && (
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => onOpenClip(detail.board!.id)}>
                  Mở clip
                </button>
              )}
              {detail.can_retry && (
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => onRetry(detail)}>
                  Thử lại
                </button>
              )}
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={onClose}>Đóng</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
