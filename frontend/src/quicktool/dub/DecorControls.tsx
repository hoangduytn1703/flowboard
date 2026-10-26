import { useEffect, useRef, useState } from "react";
import { mediaUrl } from "../../api/client";
import { listCharacters, type SavedCharacter } from "../../api/characters";
import {
  DEFAULT_FRAME, DEFAULT_MASCOT, decorChat, decorCutout, deleteDecorPreset, listDecorPresets, saveDecorPreset, uploadMascot,
  markDecorPresetUsed, type DecorChatTurn, type DecorPreset, type DubFrame, type DubLayout, type DubMascot,
} from "../../api/dub";
import { toast } from "../../store/toast";
import { generateStandaloneImage } from "../standaloneImage";

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const pct = (v: number) => `${Math.round(v * 100)}%`;
type Orientation = "portrait" | "landscape" | "square";

const MOTIONS: { key: DubMascot["motion"]; label: string }[] = [
  { key: "dance", label: "Nhún nhảy" },
  { key: "bounce", label: "Nhún" },
  { key: "sway", label: "Lắc lư" },
  { key: "none", label: "Đứng yên" },
];
const CORNERS: { label: string; x: number; y: number }[] = [
  { label: "Góc dưới phải", x: 0.83, y: 0.9 },
  { label: "Góc dưới trái", x: 0.17, y: 0.9 },
  { label: "Góc trên phải", x: 0.83, y: 0.3 },
  { label: "Góc trên trái", x: 0.17, y: 0.3 },
];
const ASKS = [
  "Khung hồng pastel, viền trắng mảnh",
  "Khung trang trí hoa đào, nền ấm áp",
  "Khung tối giản, viền vàng nổi bật",
  "Bé chibi mẹ bầu vẫy tay, góc dưới phải",
  "Chú mèo dễ thương nhún nhảy góc trái",
];
const ASPECT: Record<Orientation, string> = {
  portrait: "IMAGE_ASPECT_RATIO_PORTRAIT", landscape: "IMAGE_ASPECT_RATIO_LANDSCAPE", square: "IMAGE_ASPECT_RATIO_SQUARE",
};

/**
 * "💬 Nhờ AI", "★ Mẫu đã lưu", "🖼 Khung video" and "💃 Nhân vật nhún nhảy" for
 * a dubbed video: they go into the same ``layout`` as the subtitle position and
 * are burned in the same pass ("✓ Áp dụng"). The AI here only designs frames
 * and stickers (services/decor_ai); pictures it asks for are drawn by Flow
 * (a frame background, or a sticker on white that is then cut out).
 */
export function DecorControls({ layout, onChange, orientation = "portrait" }: {
  layout: DubLayout; onChange: (l: DubLayout) => void; orientation?: Orientation;
}) {
  const frame = layout.frame ?? null;
  const mascot = layout.mascot ?? null;
  const [models, setModels] = useState<SavedCharacter[] | null>(null);
  const [uploading, setUploading] = useState<"" | "mascot" | "bg">("");
  const fileInput = useRef<HTMLInputElement>(null);
  const bgInput = useRef<HTMLInputElement>(null);
  const [presets, setPresets] = useState<DecorPreset[] | null>(null);
  const [chat, setChat] = useState<DecorChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [thinking, setThinking] = useState("");
  // always apply AI results on the newest layout (drawing takes ~25 s)
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const chatEnd = useRef<HTMLDivElement>(null);

  useEffect(() => { void listDecorPresets().then(setPresets).catch(() => setPresets([])); }, []);
  useEffect(() => {
    if (!mascot || models !== null) return;
    void listCharacters().then(setModels).catch(() => setModels([]));
  }, [mascot, models]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [chat.length, thinking]);

  const apply = (patch: Partial<DubLayout>) => onChange({ ...layoutRef.current, ...patch });
  const setFrame = (patch: Partial<DubFrame> | null) =>
    apply({ frame: patch === null ? null : { ...DEFAULT_FRAME, ...(layoutRef.current.frame ?? {}), ...patch } });
  const setMascot = (patch: Partial<DubMascot> | null) => {
    if (patch === null) { apply({ mascot: null }); return; }
    const m = { ...DEFAULT_MASCOT, media_id: "", ...(layoutRef.current.mascot ?? {}), ...patch } as DubMascot;
    m.x = clamp(m.x, 0.05, 0.95);
    m.y = clamp(m.y, 0.15, 1);
    m.size = clamp(m.size, 0.08, 0.6);
    apply({ mascot: m });
  };

  async function upload(file: File | undefined | null, target: "mascot" | "bg") {
    if (!file) return;
    setUploading(target);
    try {
      const up = await uploadMascot(file);
      if (target === "bg") {
        setFrame({ bg: "image", bg_image: up.media_id });
        toast.success("Đã đặt ảnh nền cho khung.");
      } else {
        // an animated GIF keeps its own shape (a circle would freeze it)
        setMascot({ media_id: up.media_id, ...(up.animated ? { shape: "plain" as const } : {}) });
        toast.success(up.animated ? "Đã thêm GIF động — giữ nguyên hình, lặp suốt video." : "Đã thêm ảnh nhân vật.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading("");
      if (fileInput.current) fileInput.current.value = "";
      if (bgInput.current) bgInput.current.value = "";
    }
  }

  // ── 💬 AI ──────────────────────────────────────────────────────────────
  async function ask(text: string) {
    const msg = text.trim();
    if (!msg || thinking) return;
    const history = chat;
    setChat((c) => [...c, { role: "user", text: msg }]);
    setMessage("");
    setThinking("AI đang nghĩ…");
    try {
      const cur = layoutRef.current;
      const res = await decorChat({ message: msg, history, frame: cur.frame ?? null, mascot: cur.mascot ?? null, orientation });
      setChat((c) => [...c, { role: "assistant", text: res.reply }]);
      if (res.frame === "off") apply({ frame: null });
      else if (res.frame) apply({ frame: res.bg_prompt ? { ...res.frame, bg: cur.frame?.bg === "image" && cur.frame.bg_image ? "image" : "blur" } : res.frame });
      if (res.mascot === "off") apply({ mascot: null });
      else if (res.mascot) apply({ mascot: res.image_prompt ? { ...res.mascot, media_id: cur.mascot?.media_id ?? "" } : res.mascot });
      // pictures: drawn with Flow (~25 s each), side by side
      const jobs: Promise<void>[] = [];
      if (res.bg_prompt) {
        jobs.push((async () => {
          const id = await generateStandaloneImage(res.bg_prompt, ASPECT[orientation]);
          setFrame({ bg: "image", bg_image: id });
        })());
      }
      if (res.image_prompt) {
        jobs.push((async () => {
          const id = await generateStandaloneImage(res.image_prompt, "IMAGE_ASPECT_RATIO_PORTRAIT");
          const shape = (res.mascot && res.mascot !== "off" ? res.mascot.shape : layoutRef.current.mascot?.shape) ?? "plain";
          // on white → cut out, so it stands freely ("plain"); a circle badge keeps the picture
          const finalId = shape === "plain" ? (await decorCutout(id)).media_id : id;
          setMascot({ media_id: finalId });
        })());
      }
      if (jobs.length) {
        setThinking(`🎨 Đang vẽ ${res.bg_prompt && res.image_prompt ? "nền khung + nhân vật" : res.bg_prompt ? "nền khung" : "nhân vật"} bằng Flow (~30 giây)…`);
        const results = await Promise.allSettled(jobs);
        const failed = results.filter((r) => r.status === "rejected") as PromiseRejectedResult[];
        if (failed.length) {
          const why = failed.map((f) => (f.reason instanceof Error ? f.reason.message : String(f.reason))).join("; ");
          setChat((c) => [...c, { role: "assistant", text: `⚠ Vẽ ảnh chưa được: ${why}` }]);
        } else {
          setChat((c) => [...c, { role: "assistant", text: "Xong ảnh rồi — xem trên video bên trên, ưng thì bấm ★ Lưu hoặc ✓ Áp dụng." }]);
        }
      }
    } catch (e) {
      const err = e instanceof Error ? e.message : String(e);
      setChat((c) => [...c, { role: "assistant", text: `⚠ ${err}` }]);
    } finally {
      setThinking("");
    }
  }

  // ── ★ favourites ───────────────────────────────────────────────────────
  async function save(kind: "frame" | "mascot") {
    const data = kind === "frame" ? layoutRef.current.frame : layoutRef.current.mascot;
    if (!data) return;
    const n = (presets ?? []).filter((p) => p.kind === kind).length + 1;
    // "Khung 3 · hoa đào hồng nhạt" — the kind first, then a hint from the last wish
    const lastWish = [...chat].reverse().find((t) => t.role === "user")?.text ?? "";
    const hint = lastWish.replace(/^(khung|thêm|tạo|làm)\s+/i, "").split(/[;,.]/)[0].trim().slice(0, 32);
    const name = `${kind === "frame" ? "Khung" : "Nhân vật"} ${n}${hint ? ` · ${hint}` : ""}`;
    try {
      const row = await saveDecorPreset({ kind, name, data });
      setPresets((list) => [row, ...(list ?? [])]);
      toast.success(`Đã lưu ${kind === "frame" ? "khung" : "nhân vật"} "${row.name}" — dùng lại ở ★ Mẫu đã lưu.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }
  function usePreset(p: DecorPreset) {
    if (p.kind === "frame") apply({ frame: { ...DEFAULT_FRAME, ...(p.data as DubFrame) } });
    else apply({ mascot: { ...DEFAULT_MASCOT, ...(p.data as DubMascot) } });
    void markDecorPresetUsed(p.id).catch(() => undefined);
    toast.info(`Đã dùng "${p.name}".`);
  }
  async function removePreset(p: DecorPreset) {
    if (!window.confirm(`Xoá mẫu "${p.name}"?`)) return;
    try {
      await deleteDecorPreset(p.id);
      setPresets((list) => (list ?? []).filter((x) => x.id !== p.id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }
  const presetThumb = (p: DecorPreset) => {
    if (p.thumb) return <img src={mediaUrl(p.thumb)} alt="" loading="lazy" />;
    const f = p.data as DubFrame;
    return <span className="qt-decor__swatch" style={{ background: f.bg === "color" ? f.color : "linear-gradient(135deg,#3b4252,#1c2029)",
                                                       boxShadow: f.border ? `inset 0 0 0 3px ${f.border_color}` : undefined }} />;
  };

  return (
    <div className="qt-decor">
      <div className="qt-decor__block qt-decor__ai">
        <strong>💬 Nhờ AI tạo khung / nhân vật</strong>
        <small className="qt-card__hint">Tả bằng lời — AI chỉnh khung, nhân vật và vẽ ảnh bằng Flow khi cần (mỗi ảnh tốn credit như một ảnh cảnh).</small>
        {chat.length > 0 && (
          <div className="qt-decor__chat">
            {chat.map((t, i) => <div key={i} className={`qt-decor__msg qt-decor__msg--${t.role}`}>{t.text}</div>)}
            {thinking && <div className="qt-decor__msg qt-decor__msg--assistant qt-decor__msg--wait">{thinking}</div>}
            <div ref={chatEnd} />
          </div>
        )}
        {chat.length === 0 && thinking && <div className="qt-decor__msg qt-decor__msg--wait">{thinking}</div>}
        <div className="qt-posts__chips">
          {ASKS.map((q) => <button key={q} type="button" className="qt-chip" disabled={!!thinking} onClick={() => void ask(q)}>{q}</button>)}
        </div>
        <form className="qt-decor__send" onSubmit={(e) => { e.preventDefault(); void ask(message); }}>
          <input value={message} onChange={(e) => setMessage(e.target.value)} disabled={!!thinking}
                 placeholder="VD: khung Tết đỏ vàng, thêm bé gái chibi mặc áo dài nhún nhảy góc phải" />
          <button type="submit" className="qt-btn qt-btn--accent" disabled={!!thinking || !message.trim()}>Gửi</button>
        </form>
      </div>

      <div className="qt-decor__block">
        <strong>★ Mẫu đã lưu</strong>
        {presets === null ? <small className="qt-card__hint">Đang tải…</small>
          : presets.length === 0 ? <small className="qt-card__hint">Chưa có — chỉnh khung / nhân vật ưng ý rồi bấm ★ Lưu bên dưới.</small>
          : (
            <div className="qt-decor__presets">
              {presets.map((p) => (
                <div key={p.id} className="qt-decor__preset">
                  <button type="button" className="qt-decor__presetbtn" onClick={() => usePreset(p)} title={`Dùng "${p.name}"`}>
                    <span className="qt-decor__presetthumb">{presetThumb(p)}</span>
                    <span className="qt-decor__presetname">{p.kind === "frame" ? "🖼" : "💃"} {p.name}</span>
                  </button>
                  <button type="button" className="qt-decor__presetx" title="Xoá mẫu" onClick={() => void removePreset(p)}>×</button>
                </div>
              ))}
            </div>
          )}
      </div>

      <div className="qt-decor__block">
        <label className="qt-check">
          <input type="checkbox" checked={!!frame} onChange={(e) => setFrame(e.target.checked ? {} : null)} />
          <strong>🖼 Khung video</strong> <small className="qt-card__hint">thu nhỏ video vào giữa, nền mờ / màu / ảnh, có viền</small>
        </label>
        {frame && (
          <>
            <div className="qt-subpos__fields">
              <label className="qt-field"><span>Cỡ video trong khung <small>{pct(frame.scale)}</small></span>
                <input type="range" min={0.6} max={1} step={0.01} value={frame.scale} onChange={(e) => setFrame({ scale: Number(e.target.value) })} /></label>
              <label className="qt-field"><span>Nền khung</span>
                <select value={frame.bg} onChange={(e) => setFrame({ bg: e.target.value as DubFrame["bg"] })}>
                  <option value="blur">Chính video, làm mờ</option>
                  <option value="color">Một màu</option>
                  <option value="image">Ảnh nền (AI vẽ / của bạn)</option>
                </select></label>
              {frame.bg === "color" && (
                <label className="qt-field"><span>Màu nền</span>
                  <input type="color" value={frame.color} onChange={(e) => setFrame({ color: e.target.value })} /></label>
              )}
              <label className="qt-field"><span>Viền <small>{frame.border ? `${(frame.border * 100).toFixed(1)}%` : "không"}</small></span>
                <input type="range" min={0} max={0.03} step={0.001} value={frame.border} onChange={(e) => setFrame({ border: Number(e.target.value) })} /></label>
              {frame.border > 0 && (
                <label className="qt-field"><span>Màu viền</span>
                  <input type="color" value={frame.border_color} onChange={(e) => setFrame({ border_color: e.target.value })} /></label>
              )}
            </div>
            {frame.bg === "image" && (
              <div className="qt-decor__pick">
                {frame.bg_image
                  ? <span className="qt-decor__thumb is-on"><img src={mediaUrl(frame.bg_image)} alt="" /></span>
                  : <small className="qt-card__hint">Chưa có ảnh nền — nhờ AI vẽ (ô chat bên trên) hoặc tải ảnh lên.</small>}
                <button type="button" className="qt-decor__thumb qt-decor__thumb--add" disabled={uploading === "bg"} onClick={() => bgInput.current?.click()}>
                  {uploading === "bg" ? "…" : "⬆ Ảnh nền"}
                </button>
                <input ref={bgInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => void upload(e.target.files?.[0], "bg")} />
              </div>
            )}
            <div><button type="button" className="qt-btn qt-btn--small" onClick={() => void save("frame")}>★ Lưu khung này</button></div>
          </>
        )}
      </div>

      <div className="qt-decor__block">
        <label className="qt-check">
          <input type="checkbox" checked={!!mascot}
                 onChange={(e) => setMascot(e.target.checked ? { media_id: mascot?.media_id ?? "" } : null)} />
          <strong>💃 Nhân vật nhún nhảy</strong> <small className="qt-card__hint">người mẫu đã lưu, ảnh / GIF của bạn, hoặc nhờ AI vẽ — kéo trên video để đặt chỗ</small>
        </label>
        {mascot && (
          <>
            <div className="qt-decor__pick">
              {models === null && <small className="qt-card__hint">Đang tải người mẫu đã lưu…</small>}
              {mascot.media_id && !models?.some((m) => m.mediaId === mascot.media_id) && (
                <span className="qt-decor__thumb is-on" title="Nhân vật đang dùng"><img src={mediaUrl(mascot.media_id)} alt="" /></span>
              )}
              {models?.map((m) => (
                <button key={m.id} type="button" title={m.label || "Người mẫu"}
                        className={`qt-decor__thumb${mascot.media_id === m.mediaId ? " is-on" : ""}`}
                        onClick={() => setMascot({ media_id: m.mediaId })}>
                  <img src={mediaUrl(m.mediaId)} alt="" loading="lazy" />
                </button>
              ))}
              <button type="button" className="qt-decor__thumb qt-decor__thumb--add" disabled={uploading === "mascot"} onClick={() => fileInput.current?.click()}>
                {uploading === "mascot" ? "…" : "⬆ Ảnh / GIF"}
              </button>
              <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={(e) => void upload(e.target.files?.[0], "mascot")} />
            </div>
            {!mascot.media_id && <small className="qt-posts__need">Chọn người mẫu, tải ảnh / GIF lên, hoặc nhờ AI vẽ nhân vật.</small>}
            {mascot.media_id.length > 0 && (
              <>
                <div className="qt-subpos__fields">
                  <label className="qt-field"><span>Chuyển động</span>
                    <select value={mascot.motion} onChange={(e) => setMascot({ motion: e.target.value as DubMascot["motion"] })}>
                      {MOTIONS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                    </select></label>
                  <label className="qt-field"><span>Hình dạng</span>
                    <select value={mascot.shape} onChange={(e) => setMascot({ shape: e.target.value as DubMascot["shape"] })}>
                      <option value="circle">Tròn, viền trắng</option>
                      <option value="plain">Giữ nguyên ảnh (nền trong / GIF)</option>
                    </select></label>
                  <label className="qt-field"><span>Cỡ <small>{pct(mascot.size)}</small></span>
                    <input type="range" min={0.08} max={0.6} step={0.01} value={mascot.size} onChange={(e) => setMascot({ size: Number(e.target.value) })} /></label>
                </div>
                <div className="qt-posts__chips">
                  {CORNERS.map((c) => <button key={c.label} type="button" className="qt-chip" onClick={() => setMascot({ x: c.x, y: c.y })}>{c.label}</button>)}
                </div>
                <div><button type="button" className="qt-btn qt-btn--small" onClick={() => void save("mascot")}>★ Lưu nhân vật này</button></div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
