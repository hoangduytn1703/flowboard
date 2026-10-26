import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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

/** "Thứ hai, 26 tháng 10" */
function todayLabel(): string {
  const text = new Date().toLocaleDateString("vi-VN", { weekday: "long", day: "numeric", month: "long" });
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// ── icons (stroke icons, 24×24, inherit the text colour) ────────────────────
const ICONS = {
  wallet: <><path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1" /><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4" /></>,
  activity: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />,
  check: <><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></>,
  alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4" /><path d="M12 17h.01" /></>,
  zap: <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />,
  clock: <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
  download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></>,
  pen: <><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></>,
  plus: <><path d="M5 12h14" /><path d="M12 5v14" /></>,
  arrow: <><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></>,
  film: <><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M7 3v18" /><path d="M3 7.5h4" /><path d="M3 12h18" /><path d="M3 16.5h4" /><path d="M17 3v18" /><path d="M17 7.5h4" /><path d="M17 16.5h4" /></>,
} satisfies Record<string, ReactNode>;

function Icon({ name, size = 18 }: { name: keyof typeof ICONS; size?: number }) {
  return (
    <svg className="td-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

type Tone = "neutral" | "accent" | "good" | "bad" | "warn";

function Kpi({ icon, label, value, note, tone = "neutral", action }: {
  icon: keyof typeof ICONS; label: string; value: ReactNode; note?: string; tone?: Tone; action?: ReactNode;
}) {
  return (
    <div className={`td-kpi td-kpi--${tone}`}>
      <span className="td-kpi__icon"><Icon name={icon} /></span>
      <div className="td-kpi__body">
        <span className="td-kpi__label">{label}</span>
        <strong className="td-kpi__value">{value}</strong>
        {(note || action) && <span className="td-kpi__note">{note}{action}</span>}
      </div>
    </div>
  );
}

/** A block of the page: title row (icon, count, action) and either its rows
 * or one quiet "nothing here" line — an empty block takes one line, not a card. */
function Section({ icon, title, count = 0, tone = "neutral", action, empty, children }: {
  icon: keyof typeof ICONS; title: string; count?: number; tone?: Tone; action?: ReactNode; empty: string; children?: ReactNode;
}) {
  return (
    <section className={`td-sec td-sec--${tone}${count === 0 ? " td-sec--empty" : ""}`}>
      <header className="td-sec__head">
        <span className="td-sec__icon"><Icon name={icon} size={16} /></span>
        <h3 className="td-sec__title">{title}</h3>
        {count > 0 && <span className="td-sec__count">{count}</span>}
        <span className="td-sec__spacer" />
        {action}
      </header>
      {count === 0 ? <p className="td-sec__empty"><Icon name="check" size={14} /> {empty}</p> : <div className="td-sec__body">{children}</div>}
    </section>
  );
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

  const errorsToday = summary?.today.error ?? 0;
  const attention = due.length + failed.length;

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Hôm nay</span>
      </header>
      <div className="qt-home qt-today td-page">
        <div className="td-hero">
          <div>
            <h1 className="td-hero__title">Tổng quan hôm nay</h1>
            <p className="td-hero__sub">
              {todayLabel()} ·{" "}
              {attention > 0
                ? <span className="td-hero__alert">{attention} việc cần bạn xử lý</span>
                : "Không có việc nào đang chờ bạn"}
            </p>
          </div>
          <div className="td-hero__actions">
            <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate("/posts")}>Viết bài</button>
            <button type="button" className="qt-btn qt-btn--accent td-btn-icon" onClick={() => navigate("/clips/new")}>
              <Icon name="plus" size={16} /> Clip mới
            </button>
          </div>
        </div>

        <div className="td-kpis">
          <Kpi icon="wallet" label="Credit Flow còn lại" value={credits === null ? "—" : credits.toLocaleString("vi-VN")}
               action={credits === null
                 ? <button type="button" className="qt-link" disabled={creditsLoading} onClick={() => void refreshCredits()}>Đọc lại</button>
                 : undefined}
               note={credits === null ? "Chưa đọc được từ tab Flow" : "Số dư tài khoản đang dùng"} />
          <Kpi icon="activity" label="Đang chạy" value={running.length} tone={running.length ? "accent" : "neutral"}
               note={running.length ? "Tự cập nhật mỗi 10 giây" : "Không có việc nào"} />
          <Kpi icon="check" label="Xong hôm nay" value={summary?.today.done ?? 0} tone="good" note="Ảnh, video và clip đã ghép" />
          <Kpi icon="alert" label="Lỗi hôm nay" value={errorsToday} tone={errorsToday ? "bad" : "neutral"}
               note={errorsToday ? "Xem mục Cần xử lý" : "Không có lỗi"} />
          <Kpi icon="zap" label="Credit đã dùng" value={`~${summary?.today.credits_estimate ?? 0}`} note="Ước tính hôm nay" />
        </div>

        <div className="td-grid">
          <div className="td-col">
            <Section icon="clock" title="Đến giờ đăng" count={due.length} tone="warn"
                     empty="Chưa có bài hoặc clip nào đến giờ đăng."
                     action={<button type="button" className="qt-btn qt-btn--small qt-btn--ghost td-btn-icon" onClick={() => navigate("/schedule")}>Lịch đăng <Icon name="arrow" size={14} /></button>}>
              <DueList items={due} busy={slotBusy} onCopy={copySlot}
                       onPublish={(s) => { if (window.confirm(`Đăng ngay lên Facebook Page của kênh "${s.channel}"?`)) void slotAction(() => publishSlot(s.id), "Đã đăng lên Facebook."); }}
                       onPosted={(s) => void slotAction(() => updateSlot(s.id, { status: "posted" }), "Đã đánh dấu đã đăng.")}
                       onSkip={(s) => void slotAction(() => updateSlot(s.id, { status: "skipped" }), "")}
                       openLink={(s) => channels.find((c) => c.id === s.channel_id)?.link || "https://www.facebook.com/"} />
            </Section>

            <Section icon="alert" title="Cần xử lý" count={failed.length} tone="bad" empty="Không có clip nào bị lỗi.">
              <ul className="qt-today__list">
                {failed.map((b) => (
                  <li key={b.id}>
                    {b.summary.thumbnail && <img className="qt-today__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" loading="lazy" />}
                    <div className="td-row__main">
                      <span className="qt-today__what">{b.name}</span>
                      <span className="qt-today__meta qt-today__meta--bad">
                        {b.summary.clip_errors > 0 ? `${b.summary.clip_errors} video lỗi` : `${b.summary.errors} cảnh lỗi`}
                        {b.summary.clip_errors > 0 && " · thường do Flow chặn người mẫu — thử Tạo lại hoặc đổi mẫu"}
                      </span>
                    </div>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => navigate(`/clips/${b.id}/${stepFor(b)}`)}>Sửa</button>
                  </li>
                ))}
              </ul>
            </Section>

            <Section icon="pen" title="Clip đang làm dở" count={unfinished.length} empty="Không có clip dở."
                     action={<button type="button" className="qt-btn qt-btn--small qt-btn--ghost td-btn-icon" onClick={() => navigate("/clips")}>Tất cả clip <Icon name="arrow" size={14} /></button>}>
              <ul className="qt-today__list">
                {unfinished.slice(0, 8).map((b) => (
                  <li key={b.id}>
                    {b.summary.thumbnail && <img className="qt-today__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" loading="lazy" />}
                    <div className="td-row__main">
                      <span className="qt-today__what">{b.name}</span>
                      <span className="qt-today__meta">{b.summary.scenes_done}/{b.summary.scenes} ảnh · {b.summary.clips_done}/{b.summary.clips} video</span>
                    </div>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${b.id}/${stepFor(b)}`)}>Làm tiếp</button>
                  </li>
                ))}
              </ul>
            </Section>
          </div>

          <div className="td-col">
            <Section icon="activity" title="Đang chạy" count={running.length} tone="accent" empty="Không có việc nào đang chạy.">
              <ul className="qt-today__list">
                {running.map((r) => (
                  <li key={r.id}>
                    <div className="td-row__main">
                      <span className="qt-today__what">{r.type_label_vi}{r.node?.title ? ` · ${r.node.title}` : ""}</span>
                      <span className="qt-today__meta">{r.board?.name ?? "—"} · {since(r.created_at)}</span>
                    </div>
                    <span className={`td-pill td-pill--${r.status === "queued" ? "wait" : "run"}`}>{r.status === "queued" ? "Chờ" : "Đang chạy"}</span>
                    {r.board && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${r.board!.id}`)}>Mở</button>}
                  </li>
                ))}
              </ul>
            </Section>

            <Section icon="download" title="Đã ghép xong, chưa tải về" count={toDownload.length} tone="good" empty="Không còn clip nào chờ tải."
                     action={toDownload.length > 1
                       ? <button type="button" className="qt-btn qt-btn--small qt-btn--accent td-btn-icon" onClick={downloadAll}><Icon name="download" size={14} /> Tải cả {toDownload.length} (.zip)</button>
                       : undefined}>
              <ul className="qt-today__list">
                {toDownload.map((b) => (
                  <li key={b.id}>
                    {b.summary.thumbnail && <img className="qt-today__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" loading="lazy" />}
                    <div className="td-row__main"><span className="qt-today__what">{b.name}</span></div>
                    <a className="qt-btn qt-btn--small td-btn-icon" href={exportsZipUrl([b.id])} onClick={() => setTimeout(() => void load(), 3000)}><Icon name="download" size={14} /> Tải</a>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${b.id}/export`)}>Mở</button>
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        </div>
      </div>
    </>
  );
}
