import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { exportsZipUrl, listBoardSummaries, mediaUrl, type BoardSummary } from "../../api/client";
import { getHistorySummary, listHistory, type HistoryRow, type HistorySummary } from "../../api/history";
import { useFlowCredits } from "../../components/credits";
import { PageLoading } from "../PageState";
import { listDue, publishSlot, updateSlot, type Slot } from "../../api/schedule";
import { listPosts, splitTags, type SavedPost } from "../../api/posts";
import { toast } from "../../store/toast";
import { useChannels } from "../channels/ChannelPicker";
import { copyPost, copyText } from "../posts/PostEditor";
import { DueList } from "./SchedulePage";
import "../today.css";
import "../schedule.css";

/** Where to send someone who opens a clip from "Hôm nay". */
function stepFor(b: BoardSummary): string {
  const s = b.summary;
  if (s.clip_errors > 0) return "videos";
  if (s.errors > 0) return "images";
  if (s.exported) return "export";
  if (s.clips > 0 && s.clips_done === s.clips) return "export";
  if (s.scenes > 0 && s.scenes_done === s.scenes) return "videos";
  if (s.scenes_done > 0) return "images";
  return "setup";
}

function since(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} giây`;
  if (s < 3600) return `${Math.round(s / 60)} phút`;
  return `${Math.round(s / 3600)} giờ`;
}

/**
 * "Hôm nay" — the landing page: what is running, what failed and needs a
 * click, which finished clips are not downloaded yet, and today's numbers.
 */
export function TodayPage() {
  const navigate = useNavigate();
  const { credits, refresh: refreshCredits, loading: creditsLoading } = useFlowCredits();
  const [boards, setBoards] = useState<BoardSummary[] | null>(null);
  const [running, setRunning] = useState<HistoryRow[]>([]);
  const [summary, setSummary] = useState<HistorySummary | null>(null);
  const [due, setDue] = useState<Slot[]>([]);
  const [posts, setPosts] = useState<SavedPost[]>([]);
  const [slotBusy, setSlotBusy] = useState(false);
  const [channels] = useChannels();

  const load = useCallback(async () => {
    const [b, r, s, d, p] = await Promise.allSettled([
      listBoardSummaries(), listHistory({ status: "queued,running", limit: 20 }), getHistorySummary(), listDue(), listPosts(),
    ]);
    if (b.status === "fulfilled") setBoards(b.value);
    if (r.status === "fulfilled") setRunning(r.value.items);
    if (s.status === "fulfilled") setSummary(s.value);
    if (d.status === "fulfilled") setDue(d.value);
    if (p.status === "fulfilled") setPosts(p.value);
  }, []);

  async function slotAction(fn: () => Promise<Slot>, done: string) {
    setSlotBusy(true);
    try {
      const out = await fn();
      setDue((list) => list.filter((x) => x.id !== out.id || out.due));
      if (out.status === "failed") toast.error(out.result?.error ?? "Đăng không được.");
      else if (done) toast.success(done);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSlotBusy(false);
    }
  }
  async function copySlot(s: Slot) {
    const p = posts.find((x) => x.id === s.post_id) ?? posts.find((x) => s.kind === "clip" && x.board_id === s.board_id);
    if (!p) { toast.info("Chưa có bài / caption cho mục này."); return; }
    if (s.kind === "post") await copyPost({ title: p.title ?? "", body: p.body, hashtags: splitTags(p.hashtags), image_prompts: p.image_prompts, first_comment: p.first_comment ?? "" });
    else await copyText(`${p.body}\n\n${p.hashtags}`.trim(), "Đã copy caption của clip.");
  }

  useEffect(() => {
    document.title = "Hôm nay · Flowboard";
    void load();
  }, [load]);
  // Refresh while something runs (10 s), otherwise every minute.
  useEffect(() => {
    const t = setInterval(() => void load(), running.length ? 10_000 : 60_000);
    return () => clearInterval(t);
  }, [load, running.length]);

  const list = boards ?? [];
  const failed = useMemo(() => list.filter((b) => b.summary.errors > 0), [list]);
  const toDownload = useMemo(() => list.filter((b) => b.summary.exported && !b.summary.downloaded_at), [list]);
  const unfinished = useMemo(
    () => list.filter((b) => !b.summary.exported && b.summary.errors === 0 && !running.some((r) => r.board?.id === b.id)),
    [list, running],
  );

  if (boards === null) return <PageLoading text="Đang tải bảng hôm nay…" />;

  function downloadAll() {
    if (!toDownload.length) return;
    window.location.href = exportsZipUrl(toDownload.map((b) => b.id));
    // The agent marks them downloaded while it builds the zip.
    setTimeout(() => void load(), 4000);
  }

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Hôm nay</span>
      </header>
      <div className="qt-home qt-today">
        <div className="qt-stats qt-today__stats">
          <div className="qt-stat">
            <strong>{credits === null ? "—" : credits.toLocaleString("vi-VN")}</strong>
            <span>credit Flow còn lại {credits === null && (
              <button type="button" className="qt-link" disabled={creditsLoading} onClick={() => void refreshCredits()}>đọc lại</button>
            )}</span>
          </div>
          <div className="qt-stat"><strong>{running.length}</strong><span>việc đang chạy</span></div>
          <div className="qt-stat"><strong>{summary?.today.done ?? 0}</strong><span>việc xong hôm nay</span></div>
          <div className="qt-stat"><strong>{summary?.today.error ?? 0}</strong><span>lỗi hôm nay</span></div>
          <div className="qt-stat"><strong>~{summary?.today.credits_estimate ?? 0}</strong><span>credit đã dùng hôm nay</span></div>
        </div>

        <section className={`qt-card${due.length ? " qt-sched__due" : ""}`}>
          <div className="qt-card__head">
            <h3 className="qt-card__title">⏰ Đến giờ đăng{due.length ? ` (${due.length})` : ""}</h3>
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate("/schedule")}>Lịch đăng →</button>
          </div>
          {due.length === 0 ? <p className="qt-card__hint">Không có bài / clip nào đến giờ. Lên lịch ở trang <button type="button" className="qt-link" onClick={() => navigate("/schedule")}>Lịch đăng</button>.</p> : (
            <DueList items={due} busy={slotBusy} onCopy={copySlot}
                     onPublish={(s) => { if (window.confirm(`Đăng ngay lên Facebook Page của kênh "${s.channel}"?`)) void slotAction(() => publishSlot(s.id), "Đã đăng lên Facebook."); }}
                     onPosted={(s) => void slotAction(() => updateSlot(s.id, { status: "posted" }), "Đã đánh dấu đã đăng.")}
                     onSkip={(s) => void slotAction(() => updateSlot(s.id, { status: "skipped" }), "")}
                     openLink={(s) => channels.find((c) => c.id === s.channel_id)?.link || "https://www.facebook.com/"} />
          )}
        </section>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">⏳ Đang chạy</h3>
          </div>
          {running.length === 0 ? <p className="qt-card__hint">Không có việc nào đang chạy.</p> : (
            <ul className="qt-today__list">
              {running.map((r) => (
                <li key={r.id}>
                  <span className="qt-today__what">{r.type_label_vi}{r.node?.title ? ` · ${r.node.title}` : ""}</span>
                  <span className="qt-today__meta">{r.board?.name ?? "—"} · {r.status === "queued" ? "chờ" : "đang chạy"} {since(r.created_at)}</span>
                  {r.board && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${r.board!.id}`)}>Mở clip</button>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">⚠ Cần xử lý</h3>
          </div>
          {failed.length === 0 ? <p className="qt-card__hint">Không có clip nào bị lỗi.</p> : (
            <ul className="qt-today__list">
              {failed.map((b) => (
                <li key={b.id}>
                  {b.summary.thumbnail && <img className="qt-today__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" loading="lazy" />}
                  <span className="qt-today__what">{b.name}</span>
                  <span className="qt-today__meta qt-today__meta--bad">
                    {b.summary.clip_errors > 0 ? `${b.summary.clip_errors} video lỗi` : `${b.summary.errors} cảnh lỗi`}
                    {b.summary.clip_errors > 0 && " — thường do Flow chặn người mẫu: thử Tạo lại hoặc đổi mẫu"}
                  </span>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => navigate(`/clips/${b.id}/${stepFor(b)}`)}>Sửa</button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">✅ Đã ghép xong, chưa tải về</h3>
            {toDownload.length > 1 && (
              <button type="button" className="qt-btn qt-btn--accent" onClick={downloadAll}>⬇ Tải cả {toDownload.length} clip (.zip)</button>
            )}
          </div>
          {toDownload.length === 0 ? <p className="qt-card__hint">Không còn clip nào chờ tải.</p> : (
            <ul className="qt-today__list">
              {toDownload.map((b) => (
                <li key={b.id}>
                  {b.summary.thumbnail && <img className="qt-today__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" loading="lazy" />}
                  <span className="qt-today__what">{b.name}</span>
                  <a className="qt-btn qt-btn--small" href={exportsZipUrl([b.id])} onClick={() => setTimeout(() => void load(), 3000)}>⬇ Tải</a>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${b.id}/export`)}>Mở</button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">🛠 Clip đang làm dở</h3>
            <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate("/clips")}>Tất cả clip →</button>
          </div>
          {unfinished.length === 0 ? <p className="qt-card__hint">Không có clip dở.</p> : (
            <ul className="qt-today__list">
              {unfinished.slice(0, 8).map((b) => (
                <li key={b.id}>
                  {b.summary.thumbnail && <img className="qt-today__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" loading="lazy" />}
                  <span className="qt-today__what">{b.name}</span>
                  <span className="qt-today__meta">{b.summary.scenes_done}/{b.summary.scenes} ảnh · {b.summary.clips_done}/{b.summary.clips} video</span>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${b.id}/${stepFor(b)}`)}>Làm tiếp</button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
