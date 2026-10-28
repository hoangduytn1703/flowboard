import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import {
  deleteDubJobs, getDubJob, getDubStatus, identifyVideo, linksIn, listDubBatch, listDubJobsBrief, renderDub, startDub, stopDub,
  uploadDubVideo, type DubJob, type DubStatus, type IdentifyResult,
} from "../../api/dub";
import { DubEditor, type BatchLook } from "../dub/editor/DubEditor";
import { DubJobsDialog, jobTitle } from "../dub/DubJobsDialog";
import type { DubEngine } from "../../api/dub";
import { toast } from "../../store/toast";
import { ChannelPicker } from "../channels/ChannelPicker";
import { PageEmpty, PageLoading } from "../PageState";
import { ClipPost } from "../steps/ClipPost";
import { VoiceField } from "../VoiceField";
import "../dub.css";

const POLL_MS = 2000;
const DEFAULT_VOICE = "vi-VN-HoaiMyNeural";
const MAX_LINKS = 5;
const RECENT_SHOWN = 5;
const WORKING = ["queued", "running", "rendering"];
const isWorking = (j: DubJob) => WORKING.includes(j.status);
/** a job the editor can open: it has lines, and is not mid-transcription */
const canEdit = (j: DubJob) => j.segments.length > 0 && (["review", "done", "error"].includes(j.status) || !!j.media_id);

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * "Lồng tiếng video" — the VieDub flow in one screen: paste a link (or a
 * file), pick a voice, get the video back with the original speech
 * replaced by Vietnamese voice-over and yellow-box subtitles. The result is
 * a clip, so it can belong to a channel and get a Facebook post.
 */
export function DubPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState<DubStatus | null>(null);
  // One input per link (paste several at once → one row each); every link becomes one job of the same batch.
  const [links, setLinks] = useState<string[]>([""]);
  const linkInputs = useRef<(HTMLInputElement | null)[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [voice, setVoice] = useState(DEFAULT_VOICE);
  const [style, setStyle] = useState("box_yellow");
  const [engine, setEngine] = useState<DubEngine>("ass");
  const [keepBgm, setKeepBgm] = useState(true);
  const [review, setReview] = useState(false);
  const [channelId, setChannelId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<DubJob | null>(null);
  // several links started together: their jobs side by side; the editor opens once all of them are done
  const [batch, setBatch] = useState<{ id: string; jobs: DubJob[] } | null>(null);
  // every saved job, brief (no lines), newest first: the card shows RECENT_SHOWN, "Xem tất cả" the rest in a dialog
  const [recent, setRecent] = useState<DubJob[]>([]);
  const [allOpen, setAllOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  // 📂 reopen a video this tool made: drop it on the page or pick it in the box
  const reopenInput = useRef<HTMLInputElement>(null);
  const [reopening, setReopening] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // a file picked for a NEW dub that turns out to be one of ours: offer to open its project instead
  const [fileMatch, setFileMatch] = useState<IdentifyResult | null>(null);
  const refreshRecent = () => void listDubJobsBrief().then(setRecent).catch(() => undefined);

  useEffect(() => {
    document.title = "Lồng tiếng video · Flowboard";
    void getDubStatus().then((s) => { setStatus(s); if (!s.separate) setKeepBgm(false); })
      .catch((e) => { toast.error(errMessage(e)); setStatus({ available: false, reason: errMessage(e), root: "", ytdlp: false, whisper: false, separate: false, styles: [], max_minutes: 30, remotion: false }); });
  }, []);
  useEffect(() => { refreshRecent(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep "Gần đây" fresh while any job there still works (the queue advances on its own).
  const anyWorking = recent.some((j) => ["queued", "running", "rendering"].includes(j.status));
  useEffect(() => {
    if (!anyWorking) return;
    const t = window.setInterval(refreshRecent, 4000);
    return () => window.clearInterval(t);
  }, [anyWorking]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll while the job works; the lines become editable when it pauses or finishes.
  useEffect(() => {
    if (batch || !job || !isWorking(job)) return;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await getDubJob(job.job_id);
        if (stopped) return;
        setJob(j);
        if (j.status === "done") { toast.success("Video lồng tiếng xong — đã lưu thành clip."); refreshRecent(); }
        if (j.status === "error") toast.error(j.error ?? "Lồng tiếng lỗi.");
      } catch (e) {
        if (!stopped) { toast.error(errMessage(e)); setJob(null); }
      }
    };
    const timer = window.setInterval(tick, POLL_MS);
    void tick();
    return () => { stopped = true; window.clearInterval(timer); };
  }, [job?.job_id, job?.status, !!batch]); // eslint-disable-line react-hooks/exhaustive-deps

  // Batch: poll the whole batch while any clip works; when every clip is finished, open the editor
  // on the first one that has lines (the select on top switches between them).
  const batchWorking = !!batch && batch.jobs.some(isWorking);
  useEffect(() => {
    if (!batch) return;
    let stopped = false;
    const tick = async () => {
      try {
        const jobs = await listDubBatch(batch.id);
        if (stopped) return;
        setBatch((b) => (b && b.id === batch.id ? { ...b, jobs } : b));
        setJob((j) => (j ? jobs.find((x) => x.job_id === j.job_id) ?? j : j));
        if (!jobs.some(isWorking)) {
          const ok = jobs.filter((x) => x.status === "done").length;
          const bad = jobs.filter((x) => x.status === "error").length;
          if (bad) toast.warning(`Loạt ${jobs.length} video xong: ${ok} được, ${bad} lỗi — xem từng clip trong trình chỉnh sửa.`);
          else toast.success(`Cả loạt ${jobs.length} video đã lồng tiếng xong.`);
          setJob((j) => (j && canEdit(j) ? j : jobs.find(canEdit) ?? j));
          refreshRecent();
        }
      } catch (e) {
        if (!stopped) toast.error(errMessage(e));
      }
    };
    if (!batchWorking) return;
    const timer = window.setInterval(tick, 3000);
    void tick();
    return () => { stopped = true; window.clearInterval(timer); };
  }, [batch?.id, batchWorking]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── link rows ──────────────────────────────────────────────────────────
  function setLink(i: number, v: string) {
    setLinks((ls) => ls.map((x, k) => (k === i ? v : x)));
    if (v) setFile(null);
  }
  function addRow(after?: number) {
    setLinks((ls) => {
      if (ls.length >= MAX_LINKS) { toast.warning(`Tối đa ${MAX_LINKS} link một lần.`); return ls; }
      const at = after === undefined ? ls.length : after + 1;
      const next = [...ls.slice(0, at), "", ...ls.slice(at)];
      window.setTimeout(() => linkInputs.current[at]?.focus(), 0);
      return next;
    });
  }
  function removeRow(i: number) {
    setLinks((ls) => (ls.length > 1 ? ls.filter((_, k) => k !== i) : [""]));
  }
  /** Several links pasted at once (one per line, or several Douyin shares) → one row each. */
  function onPasteLinks(i: number, e: ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text");
    const found = linksIn(text);
    if (found.length < 2) return;  // one link (maybe with share text around it): keep the paste as is
    e.preventDefault();
    setLinks((ls) => {
      // the pasted links take this row's place; other filled rows stay in order; no link twice
      const merged: string[] = [];
      for (const x of [...ls.slice(0, i), ...found, ...ls.slice(i + 1)]) {
        const v = x.trim();
        if (v && !merged.includes(v)) merged.push(v);
      }
      if (merged.length > MAX_LINKS) toast.warning(`Dán ${found.length} link — chỉ giữ ${MAX_LINKS} link đầu (tối đa một lần).`);
      return merged.slice(0, MAX_LINKS);
    });
    setFile(null);
  }
  function onLinkKey(i: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); addRow(i); }
    if (e.key === "Backspace" && !links[i] && links.length > 1) { e.preventDefault(); removeRow(i); window.setTimeout(() => linkInputs.current[Math.max(0, i - 1)]?.focus(), 0); }
  }
  const linkList = links.map((l) => l.trim()).filter(Boolean);

  async function start() {
    if (!linkList.length && !file) { toast.warning("Dán link video hoặc chọn file."); return; }
    if (linkList.length > MAX_LINKS) { toast.warning(`Tối đa ${MAX_LINKS} link một lần.`); return; }
    setStarting(true);
    try {
      let sourceMediaId: string | null = null;
      if (file) {
        toast.info("Đang tải file lên…");
        sourceMediaId = (await uploadDubVideo(file)).media_id;
      }
      const sources = file ? [{ url: null as string | null, source_media_id: sourceMediaId }] : linkList.map((l) => ({ url: l, source_media_id: null }));
      const batchId = sources.length > 1 ? `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}` : "";
      const started: DubJob[] = [];
      for (const src of sources) {
        started.push(await startDub({
          ...src, voice, keep_bgm: keepBgm, style, engine, channel_id: channelId,
          name: sources.length > 1 ? "" : name.trim(), auto_render: !review, batch_id: batchId,
        }));
      }
      if (batchId) {
        setBatch({ id: batchId, jobs: started });
        setJob(null);
        toast.success(`Đã xếp ${sources.length} video vào loạt — chạy lần lượt; xong cả loạt sẽ mở trình chỉnh sửa.`);
      } else {
        setBatch(null);
        setJob(started[0]);
      }
      setLinks([""]);
      announceRunning();
      refreshRecent();
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setStarting(false);
    }
  }

  /** What a recognised video opens: its dub project here, or the wizard clip it came from. */
  function openMatch(m: IdentifyResult) {
    if (m.kind === "dub") {
      openJob(m.job);
      toast.success(`Đã mở lại “${m.job.name || m.job.title || "video lồng tiếng"}” — chỉnh tiếp rồi bấm “Xuất lại video”.`);
    } else {
      toast.success(`Video này là clip “${m.name}” — mở lại ở Bước 5 của clip.`);
      navigate(`/clips/${m.board_id}/export`);
    }
  }
  async function reopenFromFile(f: File) {
    if (!f.type.startsWith("video/") && !/\.(mp4|mov|m4v|webm|mkv)$/i.test(f.name)) { toast.warning("Chỉ nhận file video."); return; }
    setReopening(true);
    try {
      openMatch(await identifyVideo(f));
    } catch (e) {
      toast.warning(errMessage(e));
    } finally {
      setReopening(false);
    }
  }
  /** A new file for dubbing: check in the background whether the tool already made it. */
  function pickNewFile(f: File | null) {
    setFile(f);
    setFileMatch(null);
    if (!f) return;
    setLinks([""]);
    void identifyVideo(f).then((m) => setFile((cur) => { if (cur === f) setFileMatch(m); return cur; })).catch(() => undefined);
  }
  function onDropPage(e: DragEvent<HTMLDivElement>) {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void reopenFromFile(f);
  }

  /** "🗑 Xoá khỏi danh sách": the jobs leave the list; their exported videos and clips stay. */
  async function removeFromList(ids: string[]) {
    try {
      const r = await deleteDubJobs(ids);
      if (r.deleted.length) {
        toast.success(`Đã xoá ${r.deleted.length} mục khỏi danh sách — video đã xuất và clip vẫn còn.`);
        if (job && r.deleted.includes(job.job_id)) { setJob(null); setBatch(null); setSearchParams({}, { replace: true }); }
      }
      if (r.skipped.length) toast.warning(`${r.skipped.length} mục chưa xoá: ${r.skipped.map((x) => x.reason).filter((v, i, a) => a.indexOf(v) === i).join("; ")}`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      refreshRecent();
    }
  }

  /** The lists are brief (no lines): fetch the whole job before opening it. */
  function openJobById(id: string) {
    setAllOpen(false);
    void getDubJob(id).then(openJob).catch((e) => toast.error(errMessage(e)));
  }

  function openJob(j: DubJob) {
    setJob(j);
    if (j.batch_id && j.batch_id !== batch?.id) {
      void listDubBatch(j.batch_id).then((jobs) => setBatch({ id: j.batch_id!, jobs })).catch(() => undefined);
    } else if (!j.batch_id) {
      setBatch(null);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function closeJob() {
    setJob(null);
    setBatch(null);
    setSearchParams({}, { replace: true });
    refreshRecent();
  }
  /** The editor's select: another clip of the batch. */
  function switchJob(id: string) {
    const j = batch?.jobs.find((x) => x.job_id === id);
    if (j) setJob(j);
  }
  /** "⇪ Áp cho cả loạt": the current clip's look → every other clip (each one re-rendered, voice kept). */
  async function applyLookToBatch(look: BatchLook): Promise<number> {
    if (!batch || !job) return 0;
    const jobs = await listDubBatch(batch.id);
    const targets = jobs.filter((j) => j.job_id !== job.job_id && j.segments.length > 0 && !isWorking(j));
    const skipped = jobs.length - 1 - targets.length;
    let sent = 0;
    for (const t of targets) {
      try {
        await renderDub(t.job_id, { layout: look.layout, style: look.style, engine: look.engine, highlights: look.highlights });
        sent++;
      } catch (e) {
        toast.error(`${t.name || t.title || t.job_id}: ${errMessage(e)}`);
      }
    }
    if (skipped) toast.warning(`${skipped} clip đang chạy hoặc chưa có bản dịch — bỏ qua, áp lại sau.`);
    announceRunning();
    void listDubBatch(batch.id).then((js) => setBatch((b) => (b ? { ...b, jobs: js } : b))).catch(() => undefined);
    return sent;
  }

  // /tools/dub?job=<id>[&batch=<id>] (the "đang chạy" badge links here) opens that job / batch.
  const wantedJob = searchParams.get("job");
  const wantedBatch = searchParams.get("batch");
  useEffect(() => {
    if (wantedJob && job?.job_id !== wantedJob) {
      void getDubJob(wantedJob).then(openJob).catch(() => toast.warning("Không thấy video lồng tiếng này nữa (agent đã khởi động lại?)."));
    } else if (!wantedJob && wantedBatch && batch?.id !== wantedBatch) {
      void listDubBatch(wantedBatch).then((jobs) => { if (jobs.length) { setBatch({ id: wantedBatch, jobs }); setJob(jobs.some(isWorking) ? null : jobs.find(canEdit) ?? null); } })
        .catch(() => undefined);
    }
  }, [wantedJob, wantedBatch]); // eslint-disable-line react-hooks/exhaustive-deps
  // …and the URL follows what is on screen, so a reload or the badge lands back on it.
  useEffect(() => {
    const want: Record<string, string> = {};
    if (batch) want.batch = batch.id;
    if (job) want.job = job.job_id;
    if (!Object.keys(want).length) return;
    if (searchParams.get("job") !== (want.job ?? null) || searchParams.get("batch") !== (want.batch ?? null)) setSearchParams(want, { replace: true });
  }, [job?.job_id, batch?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === null) return <PageLoading text="Đang kiểm tra công cụ lồng tiếng…" />;
  const working = (!!job && isWorking(job)) || batchWorking;
  const styleOptions = engine === "remotion" ? status.remotion_styles ?? [] : status.styles;
  function pickEngine(next: DubEngine) {
    setEngine(next);
    const opts = next === "remotion" ? status?.remotion_styles ?? [] : status?.styles ?? [];
    if (!opts.some((o) => o.key === style)) setStyle(opts[0]?.key ?? (next === "remotion" ? "rm_box" : "box_yellow"));
  }
  // An opened video with its lines → the CapCut-style editor (full width); a fresh job still
  // transcribing / translating → the progress card next to the form.
  // A batch waits until every clip is done before the editor opens (the links were pasted together: one sitting).
  const editing = !!job && canEdit(job) && !batchWorking;
  const batchJobs = batch?.jobs ?? [];
  const batchDone = batchJobs.filter((j) => j.status === "done").length;

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">🎙 Lồng tiếng video{editing && job ? ` › ${job.name || job.title || "chỉnh sửa"}` : ""}</span>
      </header>
      <div className={`qt-home qt-dub${dragOver && !editing ? " is-dropping" : ""}`}
           onDragOver={(e) => { if (!editing && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragOver(true); } }}
           onDragLeave={(e) => { if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false); }}
           onDrop={(e) => { if (!editing) onDropPage(e); }}>
        {dragOver && !editing && (
          <div className="qt-dub__dropmask"><div>📂 Thả video vào để mở lại và chỉnh tiếp</div></div>
        )}
        {editing && job ? (
          <>
            <DubEditor key={job.job_id} job={job} status={status} onClose={closeJob}
                       onJob={(j) => { setJob(j); setBatch((b) => (b ? { ...b, jobs: b.jobs.map((x) => (x.job_id === j.job_id ? j : x)) } : b)); }}
                       siblings={batch ? batchJobs : undefined} onSwitch={batch ? switchJob : undefined} onApplyAll={batch ? applyLookToBatch : undefined} />
            {job.status === "done" && job.board_id && (
              <ClipPost boardId={job.board_id} productId={null} channelId={job.channel_id} />
            )}
          </>
        ) : !status.available ? (
          <PageEmpty icon="🎙" title="Chưa dùng được trên máy này">
            {status.reason ?? "Thiếu pyvideotrans / mô hình Whisper."} Lồng tiếng cần máy có repo <code>pyvideotrans</code> (VieDub) với mô hình
            Whisper large-v3-turbo — như máy nhà.
          </PageEmpty>
        ) : (
          <div className="qt-dub__grid">
            <div className="qt-dub__left">
              <section className="qt-card qt-dub__reopen">
                <span className="qt-dub__reopenicon" aria-hidden="true">📂</span>
                <div className="qt-dub__reopentext">
                  <strong>Chỉnh lại video đã làm</strong>
                  <small>Kéo thả vào trang này video đã tải từ tool (hoặc chọn file) — mở lại đúng chỗ đã chỉnh, kể cả hôm sau.</small>
                </div>
                <input ref={reopenInput} type="file" accept="video/*" hidden
                       onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void reopenFromFile(f); }} />
                <button type="button" className="qt-btn qt-btn--small" disabled={reopening} onClick={() => reopenInput.current?.click()}>
                  {reopening ? "Đang nhận ra…" : "Chọn video…"}
                </button>
              </section>

              <section className="qt-card">
                <div className="qt-card__eyebrow">1 · Video gốc</div>
                <h3 className="qt-card__title">Link hoặc file</h3>
                <p className="qt-card__hint">
                  Dán link TikTok / Douyin / YouTube / Instagram / Facebook / X (tối đa {status.max_minutes} phút). AI nghe tiếng gốc
                  (Whisper), dịch sang tiếng Việt nói, đọc lại bằng giọng Việt, bỏ tiếng gốc{status.separate ? " (giữ được nhạc nền)" : ""} và in phụ đề.
                </p>
                <div className="qt-field">
                  <span>Link video <small>(mỗi ô một link, tối đa {MAX_LINKS} — dán một lúc nhiều link cũng tự tách; dán cả đoạn share Douyin cũng được)</small></span>
                  <div className="qt-dub__links">
                    {links.map((l, i) => (
                      <div key={i} className="qt-dub__linkrow">
                        <span className="qt-dub__linkno">{i + 1}</span>
                        <input ref={(el) => { linkInputs.current[i] = el; }} value={l} disabled={starting}
                               placeholder={i === 0 ? "https://v.douyin.com/… hoặc https://www.tiktok.com/@…/video/…" : "Link tiếp theo…"}
                               onChange={(e) => setLink(i, e.target.value)} onPaste={(e) => onPasteLinks(i, e)} onKeyDown={(e) => onLinkKey(i, e)} />
                        {links.length > 1 && <button type="button" className="qt-dub__linkx" title="Bỏ link này" onClick={() => removeRow(i)}>×</button>}
                      </div>
                    ))}
                    {links.length < MAX_LINKS && (
                      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost qt-dub__addlink" disabled={starting} onClick={() => addRow()}>＋ Thêm link</button>
                    )}
                  </div>
                  {linkList.length > 1 && <small className="qt-card__hint">{linkList.length} video sẽ chạy lần lượt thành một loạt; xong cả loạt mới mở trình chỉnh sửa (chọn clip ở trên, áp kiểu cho cả loạt).</small>}
                </div>
                <div className="qt-dub__or">
                  <span>hoặc</span>
                  <input ref={fileInput} type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska" hidden
                         onChange={(e) => { const f = e.target.files?.[0] ?? null; e.target.value = ""; pickNewFile(f); }} />
                  <button type="button" className="qt-btn qt-btn--small" disabled={starting} onClick={() => fileInput.current?.click()}>⬆ Chọn file video</button>
                  {file && <small>{file.name} · {(file.size / 1048576).toFixed(1)} MB <button type="button" className="qt-link" onClick={() => pickNewFile(null)}>bỏ</button></small>}
                </div>
                {file && fileMatch && (
                  <div className="qt-dub__match">
                    <span>🎬 Video này bạn đã làm bằng tool{fileMatch.kind === "dub" ? `: “${fileMatch.job.name || fileMatch.job.title || "video lồng tiếng"}”` : ` (clip “${fileMatch.name}”)`}.</span>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => { const m = fileMatch; pickNewFile(null); openMatch(m); }}>✏️ Mở lại để chỉnh</button>
                    <small>hoặc bấm Lồng tiếng để làm lại từ đầu.</small>
                  </div>
                )}
                <label className="qt-field">
                  <span>Tên clip <small>(không bắt buộc — AI tự đặt)</small></span>
                  <input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Mẹo giảm căng bụng cho mẹ bầu" />
                </label>
              </section>

              <section className="qt-card">
                <div className="qt-card__eyebrow">2 · Giọng & phụ đề</div>
                <VoiceField value={voice} onChange={setVoice} sampleText="Các mẹ bầu bị căng cứng bụng cuối thai kỳ thì nhớ đeo đai nâng bụng ngay nha." disabled={working} />
                <label className="qt-field">
                  <span>Công nghệ phụ đề <small className="qt-card__hint">(ffmpeg = cách cũ · Remotion = font Việt, emoji màu, xem trước đúng y kết quả)</small></span>
                  <select value={engine} onChange={(e) => pickEngine(e.target.value as DubEngine)} disabled={working}>
                    <option value="ass">ffmpeg · như hiện tại (nhanh)</option>
                    <option value="remotion" disabled={!status.remotion}>
                      Remotion · mới{status.remotion ? "" : ` — chưa dùng được: ${status.remotion_reason ?? ""}`}
                    </option>
                  </select>
                </label>
                <label className="qt-field">
                  <span>Kiểu phụ đề</span>
                  <select value={style} onChange={(e) => setStyle(e.target.value)} disabled={working}>
                    {styleOptions.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </label>
                {engine === "remotion" && <p className="qt-card__hint">Remotion vẽ phụ đề bằng Chrome nên render chậm hơn ffmpeg (ước 1–3 phút cho clip 1 phút); lần đầu còn tải Chrome (~150 MB) và đóng gói giao diện.</p>}
                <label className="qt-check" title={status.separate ? "Tách giọng nói khỏi nhạc (spleeter), giữ nhạc nền dưới giọng Việt" : "Máy này chưa có mô hình tách giọng"}>
                  <input type="checkbox" checked={keepBgm} disabled={!status.separate || working} onChange={(e) => setKeepBgm(e.target.checked)} /> Giữ nhạc nền gốc (tách giọng nói ra)
                </label>
                <label className="qt-check" title="Dừng sau khi dịch để bạn sửa từng câu, rồi mới render">
                  <input type="checkbox" checked={review} disabled={working} onChange={(e) => setReview(e.target.checked)} /> Xem lại bản dịch trước khi render
                </label>
                <ChannelPicker value={channelId} onChange={setChannelId} label="Lưu vào kênh" disabled={working} />
                <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={starting} onClick={() => void start()}>
                  {starting ? "Đang gửi…" : linkList.length > 1 ? `🎙 Lồng tiếng ${linkList.length} video` : working ? "🎙 Thêm vào hàng đợi" : "🎙 Lồng tiếng"}
                </button>
              </section>

              {recent.length > 0 && (
                <section className="qt-card">
                  <div className="qt-card__head">
                    <h3 className="qt-card__title">Gần đây</h3>
                    <button type="button" className="qt-link" onClick={() => setAllOpen(true)}>Xem tất cả ({recent.length})</button>
                  </div>
                  <ul className="qt-dub__recent">
                    {recent.slice(0, RECENT_SHOWN).map((j) => (
                      <li key={j.job_id}>
                        <span className={`qt-dub__dot qt-dub__dot--${j.status}`} />
                        <span className="qt-today__what" title={jobTitle(j)}>{jobTitle(j)}</span>
                        <span className="qt-today__meta">{j.status === "done" ? "xong" : j.status === "error" ? "lỗi" : j.status === "review" ? "chờ sửa" : j.status === "queued" ? j.phase || "chờ đến lượt" : `${j.phase} ${j.progress}%`}</span>
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => openJobById(j.job_id)}>Mở</button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>

            <div className="qt-dub__right">
              {batch && (batchWorking || !job) ? (
                <section className="qt-card">
                  <div className="qt-card__head">
                    <div>
                      <h3 className="qt-card__title">Loạt {batchJobs.length} video</h3>
                      <small className="qt-card__hint">{batchWorking ? `đang lồng tiếng lần lượt — ${batchDone}/${batchJobs.length} xong` : `${batchDone}/${batchJobs.length} xong`}</small>
                    </div>
                    {!batchWorking && batchJobs.some(canEdit) && (
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => setJob(batchJobs.find(canEdit) ?? null)}>✏️ Mở trình chỉnh sửa</button>
                    )}
                  </div>
                  <ol className="qt-dub__batch">
                    {batchJobs.map((j, i) => (
                      <li key={j.job_id} className={`is-${j.status}`}>
                        <span className="qt-dub__batchno">{i + 1}</span>
                        <div className="qt-dub__batchbody">
                          <div className="qt-dub__batchname">{j.name || j.title || j.url || "Video"}</div>
                          <div className="qt-dub__batchstate">
                            {j.status === "done" ? "✓ xong" : j.status === "error" ? `⚠ ${j.error ?? "lỗi"}` : j.status === "review" ? "chờ sửa bản dịch"
                              : j.status === "queued" ? (j.phase || "chờ đến lượt") : `${j.phase}… ${j.progress}%`}
                          </div>
                          {isWorking(j) && j.status !== "queued" && <div className="qt-dub__bar"><span style={{ width: `${j.progress}%` }} /></div>}
                        </div>
                        {isWorking(j) && <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => void stopDub(j.job_id).catch((e) => toast.error(errMessage(e)))}>Dừng</button>}
                      </li>
                    ))}
                  </ol>
                  <p className="qt-card__hint">Xong cả loạt sẽ mở trình chỉnh sửa: chọn clip ở ô trên cùng, chỉnh một clip rồi bấm "⇪ Áp cho cả loạt" để mọi clip cùng kiểu chữ, khung, nhân vật.</p>
                </section>
              ) : !job ? (
                <div className="qt-empty qt-dub__placeholder">Tiến độ hiện ở đây. Xong là mở trình chỉnh sửa kiểu CapCut: xem video với giọng Việt, sửa chữ ngay trên hình, kéo câu trên timeline.</div>
              ) : (
                <>
                  <section className="qt-card">
                    <div className="qt-card__head">
                      <div>
                        <h3 className="qt-card__title">{job.name || job.title || "Video lồng tiếng"}</h3>
                        <small className="qt-card__hint">
                          {job.language ? `tiếng gốc: ${job.language}` : ""}{job.duration_s ? ` · ${job.duration_s}s` : ""}{job.segments.length ? ` · ${job.segments.length} câu` : ""}
                        </small>
                      </div>
                      {working && <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => void stopDub(job.job_id).then(setJob).catch((e) => toast.error(errMessage(e)))}>Dừng</button>}
                    </div>
                    {(working || job.status === "error") && (
                      <div className="qt-dub__progress">
                        <div className={`qt-dub__bar${job.status === "error" ? " is-error" : ""}`}><span style={{ width: `${job.progress}%` }} /></div>
                        <span>{job.status === "error" ? `⚠ ${job.error}` : `${job.phase}… ${job.progress}%`}</span>
                      </div>
                    )}
                  </section>
                </>
              )}
            </div>
          </div>
        )}
      </div>
      {allOpen && <DubJobsDialog jobs={recent} onOpen={openJobById} onClose={() => setAllOpen(false)} onDelete={removeFromList} />}
    </>
  );
}
