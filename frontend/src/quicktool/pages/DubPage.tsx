import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { detectBands } from "../../api/clean";
import {
  DEFAULT_BLUR, DEFAULT_LAYOUT, fmtClock, getDubJob, getDubStatus, listDubJobs, renderDub, startDub, stopDub, uploadDubVideo,
  type DubJob, type DubLayout, type DubStatus,
} from "../../api/dub";
import { SubPositioner } from "../dub/SubPositioner";
import type { DubEngine } from "../../api/dub";
import { toast } from "../../store/toast";
import { ChannelPicker } from "../channels/ChannelPicker";
import { PageEmpty, PageLoading } from "../PageState";
import { ClipPost } from "../steps/ClipPost";
import { VoiceField } from "../VoiceField";
import "../dub.css";

const POLL_MS = 2000;
const DEFAULT_VOICE = "vi-VN-HoaiMyNeural";

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
  const [status, setStatus] = useState<DubStatus | null>(null);
  const [url, setUrl] = useState("");  // one link per line → one job each (up to 5 queued)
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
  const [lines, setLines] = useState<string[]>([]);
  const [layout, setLayout] = useState<DubLayout>({ ...DEFAULT_LAYOUT });
  const [detecting, setDetecting] = useState(false);
  const [recent, setRecent] = useState<DubJob[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = "Lồng tiếng video · Flowboard";
    void getDubStatus().then((s) => { setStatus(s); if (!s.separate) setKeepBgm(false); })
      .catch((e) => { toast.error(errMessage(e)); setStatus({ available: false, reason: errMessage(e), root: "", ytdlp: false, whisper: false, separate: false, styles: [], max_minutes: 10, remotion: false }); });
    void listDubJobs().then(setRecent).catch(() => undefined);
  }, []);

  // Keep "Gần đây" fresh while any job there still works (the queue advances on its own).
  const anyWorking = recent.some((j) => ["queued", "running", "rendering"].includes(j.status));
  useEffect(() => {
    if (!anyWorking) return;
    const t = window.setInterval(() => void listDubJobs().then(setRecent).catch(() => undefined), 4000);
    return () => window.clearInterval(t);
  }, [anyWorking]);

  // Poll while the job works; the lines become editable when it pauses or finishes.
  useEffect(() => {
    if (!job || !["queued", "running", "rendering"].includes(job.status)) return;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await getDubJob(job.job_id);
        if (stopped) return;
        setJob(j);
        if (j.status === "review" || j.status === "done") setLines(j.segments.map((s) => s.text));
        if (j.status === "done") setLayout({ ...DEFAULT_LAYOUT, ...j.layout });
        if (j.status === "done") { toast.success("Video lồng tiếng xong — đã lưu thành clip."); void listDubJobs().then(setRecent).catch(() => undefined); }
        if (j.status === "error") toast.error(j.error ?? "Lồng tiếng lỗi.");
      } catch (e) {
        if (!stopped) { toast.error(errMessage(e)); setJob(null); }
      }
    };
    const timer = window.setInterval(tick, POLL_MS);
    void tick();
    return () => { stopped = true; window.clearInterval(timer); };
  }, [job?.job_id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    const links = url.split(/\n+/).map((l) => l.trim()).filter(Boolean);
    if (!links.length && !file) { toast.warning("Dán link video hoặc chọn file."); return; }
    if (links.length > 5) { toast.warning("Tối đa 5 link một lần."); return; }
    setStarting(true);
    try {
      let sourceMediaId: string | null = null;
      if (file) {
        toast.info("Đang tải file lên…");
        sourceMediaId = (await uploadDubVideo(file)).media_id;
      }
      const sources = file ? [{ url: null as string | null, source_media_id: sourceMediaId }] : links.map((l) => ({ url: l, source_media_id: null }));
      let first: DubJob | null = null;
      for (const [i, src] of sources.entries()) {
        const j = await startDub({
          ...src, voice, keep_bgm: keepBgm, style, engine, channel_id: channelId,
          name: sources.length > 1 ? "" : name.trim(), auto_render: !review,
        });
        if (i === 0) first = j;
      }
      if (first) { setJob(first); setLines([]); }
      if (sources.length > 1) toast.success(`Đã xếp ${sources.length} video vào hàng — chạy lần lượt, xem tiến độ ở "Gần đây".`);
      void listDubJobs().then(setRecent).catch(() => undefined);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setStarting(false);
    }
  }

  async function render() {
    if (!job) return;
    try {
      const j = await renderDub(job.job_id, { lines, voice, style, engine, keep_bgm: keepBgm, name: name.trim() || undefined, channel_id: channelId, layout });
      setJob(j);
    } catch (e) {
      toast.error(errMessage(e));
    }
  }

  /** OCR the source video for its hard-sub band and put the blur rectangle there. */
  async function detectOriginalSubs() {
    if (!job?.source_media_id) return;
    setDetecting(true);
    try {
      const res = await detectBands(job.source_media_id);
      const band = res.bands[0];
      if (!band) { toast.warning("OCR không thấy dải chữ nào trên video gốc — kéo vùng mờ bằng tay nhé."); return; }
      setLayout((l) => ({ ...l, blur: { ...(l.blur ?? DEFAULT_BLUR), x: 0.05, w: 0.9, y: Math.max(0, band.y0 - 0.01), h: Math.min(0.4, band.y1 - band.y0 + 0.02) } }));
      toast.success(`Thấy chữ gốc ở ${Math.round(band.y0 * 100)}–${Math.round(band.y1 * 100)}% chiều cao — đã đặt vùng mờ.`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setDetecting(false);
    }
  }

  function openJob(j: DubJob) {
    setJob(j);
    setLines(j.segments.map((s) => s.text));
    setVoice(j.voice);
    setStyle(j.style);
    setEngine(j.engine ?? "ass");
    setLayout({ ...DEFAULT_LAYOUT, ...j.layout });
    setKeepBgm(j.keep_bgm);
    setChannelId(j.channel_id);
    setName(j.name);
    if (j.url) setUrl(j.url);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (status === null) return <PageLoading text="Đang kiểm tra công cụ lồng tiếng…" />;
  const working = !!job && ["queued", "running", "rendering"].includes(job.status);
  const styleOptions = engine === "remotion" ? status.remotion_styles ?? [] : status.styles;
  function pickEngine(next: DubEngine) {
    setEngine(next);
    const opts = next === "remotion" ? status?.remotion_styles ?? [] : status?.styles ?? [];
    if (!opts.some((o) => o.key === style)) setStyle(opts[0]?.key ?? (next === "remotion" ? "rm_box" : "box_yellow"));
  }
  const playerData = job && engine === "remotion" && job.nosub_url
    ? { src: job.nosub_url, cues: job.segments.map((s) => ({ start: s.start, end: s.end, text: s.text })),
        width: job.width || 1080, height: job.height || 1920, durationS: job.duration_s }
    : null;
  const editable = !!job && (job.status === "review" || job.status === "done" || job.status === "error") && job.segments.length > 0;

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">🎙 Lồng tiếng video</span>
      </header>
      <div className="qt-home qt-dub">
        {!status.available ? (
          <PageEmpty icon="🎙" title="Chưa dùng được trên máy này">
            {status.reason ?? "Thiếu pyvideotrans / mô hình Whisper."} Lồng tiếng cần máy có repo <code>pyvideotrans</code> (VieDub) với mô hình
            Whisper large-v3-turbo — như máy nhà.
          </PageEmpty>
        ) : (
          <div className="qt-dub__grid">
            <div className="qt-dub__left">
              <section className="qt-card">
                <div className="qt-card__eyebrow">1 · Video gốc</div>
                <h3 className="qt-card__title">Link hoặc file</h3>
                <p className="qt-card__hint">
                  Dán link TikTok / Douyin / YouTube / Instagram / Facebook / X (tối đa {status.max_minutes} phút). AI nghe tiếng gốc
                  (Whisper), dịch sang tiếng Việt nói, đọc lại bằng giọng Việt, bỏ tiếng gốc{status.separate ? " (giữ được nhạc nền)" : ""} và in phụ đề.
                </p>
                <label className="qt-field">
                  <span>Link video <small>(mỗi dòng một link, tối đa 5 — dán cả đoạn share Douyin cũng được)</small></span>
                  <textarea className="qt-textarea" value={url} onChange={(e) => { setUrl(e.target.value); if (e.target.value) setFile(null); }} disabled={starting}
                            placeholder={"https://v.douyin.com/…\nhttps://www.tiktok.com/@…/video/…"} />
                </label>
                <div className="qt-dub__or">
                  <span>hoặc</span>
                  <input ref={fileInput} type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska" hidden
                         onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); if (f) setUrl(""); }} />
                  <button type="button" className="qt-btn qt-btn--small" disabled={working || starting} onClick={() => fileInput.current?.click()}>⬆ Chọn file video</button>
                  {file && <small>{file.name} · {(file.size / 1048576).toFixed(1)} MB <button type="button" className="qt-link" onClick={() => setFile(null)}>bỏ</button></small>}
                </div>
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
                  {starting ? "Đang gửi…" : working ? "🎙 Thêm vào hàng đợi" : "🎙 Lồng tiếng"}
                </button>
              </section>

              {recent.length > 0 && (
                <section className="qt-card">
                  <div className="qt-card__head"><h3 className="qt-card__title">Gần đây</h3><small className="qt-card__hint">đã lưu — chạy lần lượt, 1 video một lúc</small></div>
                  <ul className="qt-dub__recent">
                    {recent.map((j) => (
                      <li key={j.job_id}>
                        <span className={`qt-dub__dot qt-dub__dot--${j.status}`} />
                        <span className="qt-today__what">{j.name || j.title || j.url || "Video"}</span>
                        <span className="qt-today__meta">{j.status === "done" ? "xong" : j.status === "error" ? "lỗi" : j.status === "review" ? "chờ sửa" : j.status === "queued" ? j.phase || "chờ đến lượt" : `${j.phase} ${j.progress}%`}</span>
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => openJob(j)}>Mở</button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>

            <div className="qt-dub__right">
              {!job ? (
                <div className="qt-empty qt-dub__placeholder">Kết quả hiện ở đây: tiến độ từng bước, bản dịch sửa được, video xem trước, rồi lưu kênh và viết bài đăng.</div>
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
                    {job.status === "review" && <p className="qt-card__hint">Đã dịch xong. Sửa câu nào cần rồi bấm <strong>Render video</strong>.</p>}
                    {job.media_url && job.status === "done" && (
                      <div className="qt-dub__result">
                        <video className="qt-dub__video" src={job.media_url} controls playsInline />
                        <div className="qt-post__actions">
                          <a className="qt-btn qt-btn--accent" href={job.media_url} download={`${(job.name || job.title || "video-long-tieng").replace(/[\\/:*?"<>|]+/g, " ").trim()}.mp4`}>⬇ Tải video</a>
                          {job.board_id && <button type="button" className="qt-btn" onClick={() => navigate(`/clips/${job.board_id}/export`)}>Mở clip →</button>}
                        </div>
                      </div>
                    )}
                  </section>

                  {job.media_url && job.status === "done" && (
                    <details className="qt-card qt-dub__layout" open>
                      <summary>🎯 Vị trí phụ đề & làm mờ chữ gốc <small className="qt-card__hint">(kéo trên video như CapCut)</small></summary>
                      <SubPositioner
                        src={job.media_url} layout={layout} style={style} styles={styleOptions} player={playerData}
                        sample={job.segments.find((s) => s.text.trim())?.text ?? "Phụ đề mẫu"}
                        width={0} height={0} busy={working} detecting={detecting}
                        onChange={setLayout} onStyle={setStyle} onApply={() => void render()}
                        onDetect={job.source_media_id ? () => void detectOriginalSubs() : null}
                      />
                    </details>
                  )}

                  {editable && (
                    <section className="qt-card">
                      <div className="qt-card__head">
                        <h3 className="qt-card__title">Bản dịch</h3>
                        <button type="button" className={`qt-btn${job.status === "review" ? " qt-btn--accent" : ""}`} disabled={working} onClick={() => void render()}>
                          {job.status === "review" ? "🎬 Render video" : "↻ Render lại với bản sửa"}
                        </button>
                      </div>
                      <p className="qt-card__hint">Mỗi dòng là một câu đọc + một hộp phụ đề, giữ trong khoảng thời gian của câu gốc; câu dài sẽ bị đọc nhanh hơn — rút gọn nếu quá dài. Để trống = bỏ câu đó.</p>
                      <ol className="qt-dub__lines">
                        {job.segments.map((s, i) => (
                          <li key={i}>
                            <div className="qt-dub__time">{fmtClock(s.start)}–{fmtClock(s.end)}<small>{(s.end - s.start).toFixed(1)}s</small></div>
                            <div className="qt-dub__texts">
                              <small className="qt-dub__src">{s.src}</small>
                              <textarea className="qt-textarea" value={lines[i] ?? ""} rows={1} disabled={working}
                                        onChange={(e) => setLines((l) => { const n = [...l]; n[i] = e.target.value; return n; })} />
                            </div>
                          </li>
                        ))}
                      </ol>
                    </section>
                  )}

                  {job.status === "done" && job.board_id && (
                    <ClipPost boardId={job.board_id} productId={null} channelId={job.channel_id} />
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
