/** /tools/clean — "Xoá chữ / logo / watermark" for a video the seller
 *  already has. Manual mode: draw rectangles on a frame, ffmpeg removes
 *  them. AI mode: pyvideotrans finds the hard-subtitle bands and LaMa
 *  inpaints them (slow, GPU) — or the bands are just blurred (fast).
 *  Rendered inside the /clips layout like ProductsPage. */
import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useNavigate } from "react-router-dom";

import {
  aiStatus as fetchAiStatus,
  blurBands,
  detectBands,
  eraseBoxes,
  frameUrl,
  getCleanJob,
  MAX_CLEAN_VIDEO_BYTES,
  startAiErase,
  stopCleanJob,
  uploadCleanVideo,
} from "../../api/clean";
import type { AiStatus, CleanBand, CleanBox, CleanJob, CleanVideo, EraseMethod } from "../../api/clean";
import "../quicktool.css";
import "../clean.css";
import { useToastOn } from "../../store/toast";

const BOX_COLORS = ["#ff6a2b", "#38bdf8", "#a3e635", "#f472b6", "#facc15", "#c084fc"];
const BAND_COLOR = "#facc15";
const MIN_BOX = 0.01; // a drag smaller than 1 % of the frame is a click, not a box
const JOB_POLL_MS = 1500;
const ACCEPT = ".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm";

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function CleanToolPage() {
  const navigate = useNavigate();
  useEffect(() => {
    const prev = document.title;
    document.title = "Xoá chữ / logo · Flowboard";
    return () => { document.title = prev; };
  }, []);

  // ── source video ────────────────────────────────────────────────────
  const [video, setVideo] = useState<CleanVideo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  useToastOn(uploadError, "error", () => setUploadError(null));
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  // ── frame + drawing ─────────────────────────────────────────────────
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [t, setT] = useState(0);
  const [frame, setFrame] = useState<HTMLImageElement | null>(null);
  const [frameLoading, setFrameLoading] = useState(false);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [boxes, setBoxes] = useState<CleanBox[]>([]);
  const [draft, setDraft] = useState<CleanBox | null>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const [method, setMethod] = useState<EraseMethod>("delogo");
  const [boxBusy, setBoxBusy] = useState(false);
  const [boxError, setBoxError] = useState<string | null>(null);
  useToastOn(boxError, "error", () => setBoxError(null));

  // ── AI ──────────────────────────────────────────────────────────────
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [bands, setBands] = useState<CleanBand[] | null>(null);
  const [detectInfo, setDetectInfo] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  useToastOn(aiError, "error", () => setAiError(null));
  const [job, setJob] = useState<CleanJob | null>(null);
  const [bandBlurBusy, setBandBlurBusy] = useState(false);

  // ── result ──────────────────────────────────────────────────────────
  const [result, setResult] = useState<CleanVideo | null>(null);
  const [resultLabel, setResultLabel] = useState("");

  useEffect(() => {
    fetchAiStatus().then(setAi).catch((e) => setAi({ available: false, reason: errMessage(e) }));
  }, []);

  const resetForVideo = useCallback((v: CleanVideo) => {
    setVideo(v);
    setT(Math.min(1, v.duration_s));
    setBoxes([]);
    setDraft(null);
    setBands(null);
    setDetectInfo(null);
    setBoxError(null);
    setAiError(null);
    setFrameError(null);
    setJob(null);
  }, []);

  const pickFile = useCallback(async (file: File | undefined | null) => {
    if (!file) return;
    setUploadError(null);
    const ext = file.name.toLowerCase().split(".").pop() ?? "";
    if (!["mp4", "mov", "webm"].includes(ext) && !file.type.startsWith("video/")) {
      setUploadError("Chỉ nhận video mp4 / mov / webm.");
      return;
    }
    if (file.size > MAX_CLEAN_VIDEO_BYTES) {
      setUploadError(`Video ${Math.round(file.size / 1024 / 1024)} MB — tối đa 200 MB.`);
      return;
    }
    setUploading(true);
    try {
      const v = await uploadCleanVideo(file);
      resetForVideo(v);
      setResult(null);
    } catch (e) {
      setUploadError(`Tải lên lỗi: ${errMessage(e)}`);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }, [resetForVideo]);

  // Load the frame for `t`, debounced so dragging the slider does not fire
  // one ffmpeg per pixel.
  useEffect(() => {
    if (!video) { setFrame(null); return; }
    let cancelled = false;
    setFrameLoading(true);
    const timer = window.setTimeout(() => {
      const img = new Image();
      img.onload = () => { if (!cancelled) { setFrame(img); setFrameLoading(false); setFrameError(null); } };
      img.onerror = () => { if (!cancelled) { setFrameLoading(false); setFrameError("Không lấy được khung hình."); } };
      img.src = frameUrl(video.media_id, t);
    }, 150);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [video, t]);

  // Redraw: frame, then the AI bands, then the boxes (and the drag draft).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !video) return;
    const W = video.width, H = video.height;
    if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    if (frame) ctx.drawImage(frame, 0, 0, W, H);
    else { ctx.fillStyle = "#111"; ctx.fillRect(0, 0, W, H); }
    const lw = Math.max(2, Math.round(W / 360));
    ctx.font = `${Math.max(12, Math.round(W / 40))}px sans-serif`;
    for (const b of bands ?? []) {
      ctx.fillStyle = "rgba(250, 204, 21, 0.22)";
      ctx.fillRect(0, b.y0 * H, W, (b.y1 - b.y0) * H);
      ctx.strokeStyle = BAND_COLOR;
      ctx.lineWidth = lw;
      ctx.setLineDash([lw * 4, lw * 3]);
      ctx.strokeRect(0, b.y0 * H, W, (b.y1 - b.y0) * H);
      ctx.setLineDash([]);
    }
    const all = draft ? [...boxes, draft] : boxes;
    all.forEach((b, i) => {
      const color = BOX_COLORS[i % BOX_COLORS.length];
      const isDraft = draft != null && i === all.length - 1;
      ctx.fillStyle = isDraft ? "rgba(255,255,255,0.12)" : `${color}33`;
      ctx.fillRect(b.x * W, b.y * H, b.w * W, b.h * H);
      ctx.strokeStyle = color;
      ctx.lineWidth = lw;
      if (isDraft) ctx.setLineDash([lw * 3, lw * 3]);
      ctx.strokeRect(b.x * W, b.y * H, b.w * W, b.h * H);
      ctx.setLineDash([]);
      if (!isDraft) {
        ctx.fillStyle = color;
        ctx.fillText(String(i + 1), b.x * W + lw * 2, b.y * H + lw * 2 + parseInt(ctx.font, 10));
      }
    });
  }, [video, frame, boxes, draft, bands]);

  const pointFromEvent = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)),
    };
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!video || boxBusy) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragStart.current = pointFromEvent(e);
    setDraft(null);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const start = dragStart.current;
    if (!start) return;
    const p = pointFromEvent(e);
    setDraft({ x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) });
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const start = dragStart.current;
    dragStart.current = null;
    if (!start) return;
    const p = pointFromEvent(e);
    const box = { x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) };
    setDraft(null);
    if (box.w >= MIN_BOX && box.h >= MIN_BOX) {
      setBoxes((prev) => [...prev, { x: +box.x.toFixed(4), y: +box.y.toFixed(4), w: +box.w.toFixed(4), h: +box.h.toFixed(4) }]);
      setBoxError(null);
    }
  };

  const runBoxErase = async () => {
    if (!video || boxes.length === 0) return;
    setBoxBusy(true);
    setBoxError(null);
    try {
      const out = await eraseBoxes(video.media_id, boxes, method);
      setResult(out);
      setResultLabel(method === "delogo" ? `Đã xoá ${boxes.length} vùng (delogo)` : `Đã làm mờ ${boxes.length} vùng`);
    } catch (e) {
      setBoxError(errMessage(e));
    } finally {
      setBoxBusy(false);
    }
  };

  const runDetect = async () => {
    if (!video) return;
    setDetecting(true);
    setAiError(null);
    try {
      const out = await detectBands(video.media_id);
      setBands(out.bands);
      setDetectInfo(out.info || (out.bands.length ? `Thấy ${out.bands.length} dải phụ đề.` : "Không thấy dải phụ đề nào."));
      if (out.bands.length && Number.isFinite(out.preview_t)) setT(out.preview_t);
    } catch (e) {
      setAiError(errMessage(e));
    } finally {
      setDetecting(false);
    }
  };

  const runAiErase = async () => {
    if (!video || !bands?.length) return;
    setAiError(null);
    try {
      const { job_id } = await startAiErase(video.media_id, bands);
      setJob({ job_id, status: "queued", progress: 0 });
    } catch (e) {
      setAiError(errMessage(e));
    }
  };

  const runBandBlur = async () => {
    if (!video || !bands?.length) return;
    setBandBlurBusy(true);
    setAiError(null);
    try {
      const out = await blurBands(video.media_id, bands);
      setResult(out);
      setResultLabel(`Đã làm mờ ${bands.length} dải phụ đề`);
    } catch (e) {
      setAiError(errMessage(e));
    } finally {
      setBandBlurBusy(false);
    }
  };

  // Poll the LaMa job until it settles.
  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await getCleanJob(job.job_id);
        if (stopped) return;
        setJob(j);
        if (j.status === "done" && j.media_id && j.url) {
          setResult({ media_id: j.media_id, url: j.url, duration_s: j.duration_s ?? video?.duration_s ?? 0,
                      width: video?.width ?? 0, height: video?.height ?? 0 });
          setResultLabel("Đã xoá phụ đề bằng AI (LaMa)");
        } else if (j.status === "error") {
          setAiError(j.error ?? "Xoá bằng AI lỗi.");
        }
      } catch (e) {
        if (!stopped) { setAiError(errMessage(e)); setJob(null); }
      }
    };
    const timer = window.setInterval(tick, JOB_POLL_MS);
    void tick();
    return () => { stopped = true; window.clearInterval(timer); };
  }, [job?.job_id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const jobRunning = job?.status === "queued" || job?.status === "running";
  const busyAny = boxBusy || bandBlurBusy || jobRunning || detecting;

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">🧽 Xoá chữ / logo / watermark</span>
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate("/clips")}>
          ← Clip của tôi
        </button>
      </header>
      <div className="qt-home">
        {/* 1 · upload */}
        <section className="qt-card">
          <span className="qt-card__eyebrow">Bước 1 · Video nguồn</span>
          <h2 className="qt-card__title">Chọn video cần làm sạch</h2>
          <p className="qt-card__hint">
            Video có sẵn của bạn (mp4 / mov / webm, tối đa 200 MB). Video chỉ nằm trên máy này, không gửi lên Flow.
          </p>
          <label
            className={`clean-drop${dragOver ? " clean-drop--over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); void pickFile(e.dataTransfer.files?.[0]); }}
          >
            <input ref={fileInput} type="file" accept={ACCEPT} disabled={uploading}
                   onChange={(e) => void pickFile(e.target.files?.[0])} />
            {uploading ? (
              <><span className="qt-spinner" /> Đang tải lên…</>
            ) : video ? (
              <>
                <strong>Đã có video</strong>
                <span>Kéo thả hoặc bấm để thay video khác</span>
              </>
            ) : (
              <>
                <strong>Kéo thả video vào đây</strong>
                <span>hoặc bấm để chọn file</span>
              </>
            )}
          </label>
          {video && (
            <div className="clean-meta">
              <span>Kích thước <strong>{video.width}×{video.height}</strong></span>
              <span>Thời lượng <strong>{fmtTime(video.duration_s)}</strong></span>
              {video.has_audio === false && <span>Không có tiếng</span>}
              <span>Media <code>{video.media_id.slice(0, 8)}…</code></span>
            </div>
          )}
        </section>

        {video && (
          <div className="clean-grid">
            {/* 2 · frame + manual boxes */}
            <div className="clean-stack">
              <section className="qt-card">
                <span className="qt-card__eyebrow">Bước 2 · Khoanh vùng</span>
                <h2 className="qt-card__title">Kéo chuột trên khung hình để khoanh chữ / logo</h2>
                <p className="qt-card__hint">
                  Kéo thanh thời gian để tìm khung có logo rõ nhất. Mỗi lần kéo chuột tạo một ô; khoanh rộng hơn
                  logo một chút để không sót viền. Vùng vàng là dải phụ đề do AI tìm (mục 3).
                </p>
                <div className={`clean-stage${boxBusy ? " clean-stage--busy" : ""}`}>
                  <canvas
                    ref={canvasRef}
                    onPointerDown={onPointerDown}
                    onPointerMove={onPointerMove}
                    onPointerUp={onPointerUp}
                    onPointerCancel={() => { dragStart.current = null; setDraft(null); }}
                  />
                  {(frameLoading || frameError) && (
                    <span className="clean-stage__hint">{frameError ?? "Đang lấy khung hình…"}</span>
                  )}
                </div>
                <div className="clean-time">
                  <span>Thời điểm</span>
                  <input
                    type="range" min={0} max={Math.max(0.1, video.duration_s - 0.05)} step={0.1}
                    value={Math.min(t, video.duration_s)} onChange={(e) => setT(parseFloat(e.target.value))}
                  />
                  <code>{fmtTime(t)}</code>
                </div>
              </section>
            </div>

            <div className="clean-stack">
              <section className="qt-card">
                <span className="qt-card__eyebrow">Thủ công · không cần AI</span>
                <h2 className="qt-card__title">Vùng đã khoanh ({boxes.length})</h2>
                {boxes.length === 0 ? (
                  <div className="qt-empty">Chưa có vùng nào — kéo chuột trên khung hình bên trái.</div>
                ) : (
                  <ul className="clean-list">
                    {boxes.map((b, i) => (
                      <li key={`${b.x}-${b.y}-${i}`}>
                        <span className="clean-swatch" style={{ background: BOX_COLORS[i % BOX_COLORS.length] }} />
                        <span>Ô {i + 1}</span>
                        <code>{pct(b.x)},{pct(b.y)} · {pct(b.w)}×{pct(b.h)}</code>
                        <button type="button" onClick={() => setBoxes((prev) => prev.filter((_, k) => k !== i))} disabled={boxBusy}>
                          Bỏ
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="clean-radio">
                  <label>
                    <input type="radio" name="clean-method" checked={method === "delogo"} onChange={() => setMethod("delogo")} />
                    Xoá (delogo)
                  </label>
                  <label>
                    <input type="radio" name="clean-method" checked={method === "blur"} onChange={() => setMethod("blur")} />
                    Làm mờ
                  </label>
                </div>
                <p className="qt-card__hint">
                  <strong>Xoá</strong> nội suy nền từ xung quanh — hợp logo nhỏ, nền đơn giản.
                  <strong> Làm mờ</strong> an toàn hơn với logo to hoặc nền phức tạp.
                </p>
                <div className="qt-row">
                  <button type="button" className="qt-btn qt-btn--accent" disabled={boxes.length === 0 || busyAny} onClick={() => void runBoxErase()}>
                    {boxBusy ? <><span className="qt-spinner" /> Đang xử lý…</> : "Xoá vùng đã khoanh"}
                  </button>
                  <button type="button" className="qt-btn qt-btn--ghost" disabled={boxes.length === 0 || boxBusy} onClick={() => setBoxes([])}>
                    Bỏ hết
                  </button>
                </div>
              </section>

              {/* 3 · AI subtitle bands */}
              <section className={`qt-card${ai && !ai.available ? " clean-card--disabled" : ""}`}>
                <span className="qt-card__eyebrow">AI · phụ đề cứng</span>
                <h2 className="qt-card__title">AI xoá phụ đề cứng</h2>
                {ai === null ? (
                  <p className="qt-card__hint"><span className="qt-spinner" /> Đang kiểm tra pyvideotrans…</p>
                ) : !ai.available ? (
                  <p className="qt-card__hint">
                    <strong>Cần cài pyvideotrans (xem CLAUDE.md).</strong> {ai.reason}
                  </p>
                ) : (
                  <p className="qt-card__hint">
                    Tìm các dòng chữ lặp lại ở cùng độ cao (phụ đề in sẵn), rồi vẽ lại nền bằng LaMa trên GPU.
                    {ai.model_cached === false && " Lần đầu sẽ tải mô hình LaMa (~200 MB)."}
                  </p>
                )}
                <div className="qt-row">
                  <button type="button" className="qt-btn" disabled={!ai?.available || busyAny} onClick={() => void runDetect()}>
                    {detecting ? <><span className="qt-spinner" /> Đang quét…</> : "Tìm dải phụ đề"}
                  </button>
                </div>
                {detectInfo && <p className="clean-ok">{detectInfo}</p>}
                {bands && bands.length > 0 && (
                  <ul className="clean-list">
                    {bands.map((b, i) => (
                      <li key={`${b.y0}-${b.y1}`}>
                        <span className="clean-swatch" style={{ background: BAND_COLOR }} />
                        <span>Dải {i + 1}</span>
                        <code>{pct(b.y0)} → {pct(b.y1)}{b.hits ? ` · ${b.hits} khung` : ""}</code>
                        <button type="button" disabled={jobRunning} onClick={() => setBands((prev) => (prev ?? []).filter((_, k) => k !== i))}>
                          Bỏ
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {bands && bands.length > 0 && (
                  <div className="qt-row">
                    <button type="button" className="qt-btn qt-btn--accent" disabled={!ai?.available || busyAny} onClick={() => void runAiErase()}>
                      Xoá bằng AI (chậm, GPU)
                    </button>
                    <button type="button" className="qt-btn" disabled={busyAny} onClick={() => void runBandBlur()}>
                      {bandBlurBusy ? <><span className="qt-spinner" /> Đang làm mờ…</> : "Làm mờ dải (nhanh)"}
                    </button>
                  </div>
                )}
                {job && (
                  <>
                    <div className={`clean-progress${job.status === "queued" ? " clean-progress--indeterminate" : ""}`}>
                      <span style={{ width: `${job.status === "done" ? 100 : job.progress}%` }} />
                    </div>
                    <div className="qt-row" style={{ alignItems: "center" }}>
                      <span className="clean-ok">
                        {job.status === "queued" && "Đang khởi động (nạp mô hình)…"}
                        {job.status === "running" && `Đang xoá… ${job.progress}%`}
                        {job.status === "done" && "Xong."}
                        {job.status === "error" && "Lỗi."}
                      </span>
                      {jobRunning && (
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost"
                                onClick={() => stopCleanJob(job.job_id).then(setJob).catch((e) => setAiError(errMessage(e)))}>
                          Dừng
                        </button>
                      )}
                    </div>
                  </>
                )}
              </section>
            </div>
          </div>
        )}

        {/* 4 · result */}
        {result && (
          <section className="qt-card clean-result">
            <span className="qt-card__eyebrow">Kết quả</span>
            <h2 className="qt-card__title">{resultLabel || "Video đã làm sạch"}</h2>
            <video key={result.media_id} src={result.url} controls playsInline />
            <div className="qt-row">
              <a className="qt-btn qt-btn--accent" href={result.url} download={`clean-${result.media_id.slice(0, 8)}.mp4`}>
                ⬇ Tải về
              </a>
              <button type="button" className="qt-btn" onClick={() => resetForVideo(result)}>
                Làm sạch tiếp trên kết quả này
              </button>
            </div>
            <p className="qt-card__hint">
              Kết quả cũng là một media của Flowboard, dùng được ở chỗ khác (ví dụ chèn vào bước Ghép):{" "}
              <code>{result.url}</code>
            </p>
          </section>
        )}
      </div>
    </>
  );
}
