import { useEffect, useRef, useState } from "react";
import {
  CANVAS_ASPECTS, CANVAS_DEFAULT, CANVAS_FITS, canvasSize, normCanvas, uploadDubBackground,
  type CanvasAspect, type CanvasFit, type DubCanvas, type DubLayout,
} from "../../../api/dub";
import { toast } from "../../../store/toast";
import { TickRange } from "../../../components/TickRange";
import { canvasRect, innerCrop } from "../../../remotion/canvasGeom";
import { PLATFORMS, platformOf, type PlatformKey } from "./platforms";

type Rect = { x: number; y: number; w: number; h: number };
const FULL: Rect = { x: 0, y: 0, w: 1, h: 1 };

/** Where the picture goes on the output frame (fractions of the frame): ``src`` = where the whole source picture
 * would lie (larger than ``shown`` when it is cut), ``shown`` = the part that is visible — the format's fit, then the
 * decorative frame's shrink, the same steps as the render (services/dub.canvas_filter, dub_decor.frame_filter). */
function placed(srcW: number, srcH: number, layout: DubLayout): { src: Rect; shown: Rect } {
  let src = FULL, shown = FULL;
  const c = layout.canvas;
  if (c && srcW > 0 && srcH > 0) {
    const { w: cw, h: ch } = canvasSize(srcW, srcH, c);
    shown = canvasRect(srcW, srcH, cw, ch, c);
    src = shown;
    const ic = innerCrop(srcW, srcH, c);
    if (ic) src = { x: shown.x - (ic.x / ic.w) * shown.w, y: shown.y - (ic.y / ic.h) * shown.h, w: shown.w / ic.w, h: shown.h / ic.h };
    if (c.fit === "crop") shown = FULL; // the picture covers the frame
  }
  const f = layout.frame;
  const shrink = (r: Rect): Rect => {
    if (!f) return r;
    const m = (1 - f.scale) / 2;
    return { x: m + f.scale * r.x, y: m + f.scale * r.y, w: f.scale * r.w, h: f.scale * r.h };
  };
  return { src: shrink(src), shown: shrink(shown) };
}

/** Where the whole source picture lies on the output frame (fractions of the frame). */
export function sourceRect(srcW: number, srcH: number, layout: DubLayout): Rect {
  return placed(srcW, srcH, layout).src;
}

/** A box given on the source picture (e.g. an OCR text band) → the same place on the output frame, clipped to the
 * part of the picture that shows. */
export function sourceBoxToFrame(box: Rect, srcW: number, srcH: number, layout: DubLayout) {
  const { src: r, shown } = placed(srcW, srcH, layout);
  const lx = Math.max(0, shown.x), ly = Math.max(0, shown.y);
  const hx = Math.min(1, shown.x + shown.w), hy = Math.min(1, shown.y + shown.h);
  const x0 = Math.max(lx, r.x + box.x * r.w), y0 = Math.max(ly, r.y + box.y * r.h);
  const x1 = Math.min(hx, r.x + (box.x + box.w) * r.w), y1 = Math.min(hy, r.y + (box.y + box.h) * r.h);
  const r3 = (v: number) => Math.round(v * 1000) / 1000;
  return { x: r3(Math.min(x0, 0.95)), y: r3(Math.min(y0, 0.97)), w: r3(Math.max(0.05, x1 - x0)), h: r3(Math.max(0.02, y1 - y0)) };
}

function shapeOf(w: number, h: number): string {
  if (!w || !h) return "";
  const hit = CANVAS_ASPECTS.find((a) => Math.abs(a.w / a.h - w / h) < 0.01);
  return hit ? hit.key : `${w}×${h}`;
}

/** A small rectangle in the format's shape. */
function Shape({ w, h }: { w: number; h: number }) {
  const k = 14 / Math.max(w, h);
  return <span className="dx-format__shape" style={{ width: Math.round(w * k), height: Math.round(h * k) }} aria-hidden="true" />;
}

const BACKGROUNDS = CANVAS_FITS.filter((f) => f.key !== "crop");

/** "Khung xuất" above the preview, three rows — the preview follows at once, the export comes out the same:
 * 1. the frame (the video's final size); 2. the picture in it: covering the frame (cut), whole, or cut to another
 * shape first ("Cắt 4:3"); 3. the background around it: blur / black / colour / grid / uploaded picture or video —
 * the background that replaces the app's black bars. Picking a background while the picture covers a frame that is
 * not the phone's (4:3 cut to fill) keeps that look and puts it on the phone frame (9:16, or 16:9 for YouTube). */
export function FormatBar({ layout, srcW, srcH, readOnly, onLayout, platform, onPlatform }: {
  layout: DubLayout;
  srcW: number;
  srcH: number;
  readOnly: boolean;
  onLayout: (l: DubLayout, coalesce?: string) => void;
  /** "📱 Xem trên": preview inside an app's screen (view only) */
  platform: PlatformKey | null;
  onPlatform: (p: PlatformKey | null) => void;
}) {
  const c = layout.canvas ?? null;
  const out = canvasSize(srcW, srcH, c);
  const same = !!c && out.w === srcW && out.h === srcH;
  const srcShape = shapeOf(srcW, srcH);
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const fill = !!c && c.fit === "crop";
  const bg = c && c.fit !== "crop" ? c.fit : null;
  // the background last used, for "Nguyên hình" / "Cắt …" after "Phủ kín khung"
  const lastBg = useRef<CanvasFit>(bg ?? "blur");
  useEffect(() => { if (bg) lastBg.current = bg; }, [bg]);
  const set = (patch: Partial<DubCanvas> | null, key?: string) =>
    onLayout({ ...layout, canvas: patch === null ? null : normCanvas({ aspect: "9:16", fit: "blur", pos: 0.5, ...CANVAS_DEFAULT, ...(c ?? {}), ...patch }) }, key);

  async function upload(file: File) {
    setUploading(true);
    try {
      const r = await uploadDubBackground(file);
      set({ fit: r.kind, media_id: r.media_id });
      toast.success(r.kind === "video" ? "Đã đặt video nền (tự lặp, không lấy tiếng)." : "Đã đặt ảnh nền.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  /** A background: around the picture as it is — onto the phone's frame when the picture covers another one. */
  function pickBg(kind: CanvasFit) {
    const app = platformOf(platform);
    const target: CanvasAspect = platform === "youtube" ? "16:9" : "9:16";
    if (!c || fill) {
      const look = c?.aspect ?? (srcShape as CanvasAspect);
      const inner = c && c.aspect !== target ? c.aspect : "";
      // the source already has the target shape and nothing is cut: shrink it a little so the background shows
      const shrink = !inner && srcShape === target ? 0.85 : 1;
      set({ aspect: target, fit: kind, inner, cut: c?.cut ?? 0.5, pos: 0.5, scale: shrink });
      toast.info(inner
        ? `Video vẫn cắt ${look} như cũ, giờ đặt giữa khung ${target} — nền thay phần đen của ${app?.label ?? "TikTok"}.`
        : `Cả video đặt giữa khung ${target} trên nền.`);
    } else {
      set({ fit: kind });
    }
    if ((kind === "image" || kind === "video") && !c?.media_id) fileInput.current?.click();
  }

  const inner = c?.inner ?? "";
  const cutting = fill || !!inner;
  const needsFile = !!bg && (bg === "image" || bg === "video");
  // "Cắt …" chips: shapes other than the source's own (that is "Nguyên hình") and the frame's (that is "Phủ kín khung")
  const cutShapes = CANVAS_ASPECTS.filter((a) => a.key !== srcShape && a.key !== c?.aspect);

  return (
    <div className="dx-format" role="group" aria-label="Khung xuất">
      <div className="dx-format__row">
        <span className="dx-format__label">Khung xuất</span>
        <div className="dx-format__chips">
          <button type="button" className={`dx-format__chip${!c ? " is-on" : ""}`} disabled={readOnly} onClick={() => set(null)}
                  title="Giữ đúng kích thước video gốc">
            <Shape w={srcW || 9} h={srcH || 16} /> Gốc{srcW ? ` ${srcShape}` : ""}
          </button>
          {CANVAS_ASPECTS.map((a) => (
            <button key={a.key} type="button" className={`dx-format__chip${c?.aspect === a.key ? " is-on" : ""}`} disabled={readOnly}
                    title={a.hint} onClick={() => set({ aspect: a.key, ...(c?.inner === a.key ? { inner: "" } : {}) })}>
              <Shape w={a.w} h={a.h} /> {a.key}
            </button>
          ))}
        </div>
        <label className={`dx-format__view${platform ? " is-on" : ""}`} title="Xem video sau khi xuất hiện thế nào trong app — nút, chữ của app che chỗ nào, app cắt video ra sao (chỉ để xem, không đổi video xuất)">
          📱 Xem trên
          <select value={platform ?? ""} onChange={(e) => onPlatform((e.target.value || null) as PlatformKey | null)}>
            <option value="">— Khung chỉnh sửa —</option>
            {PLATFORMS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
        <span className="dx-format__size" title="Kích thước video sẽ xuất ra">
          {out.w && out.h ? `→ ${out.w}×${out.h}${same ? " (giống gốc)" : ""}` : ""}
        </span>
      </div>

      {c && (
        <div className="dx-format__row" role="group" aria-label="Video trong khung">
          <span className="dx-format__label">Video</span>
          {!same && (
            <button type="button" className={`dx-format__chip dx-format__chip--sm${fill ? " is-on" : ""}`} disabled={readOnly}
                    title={`Phóng video cho kín khung ${c.aspect}, cắt bớt phần thừa — không có nền`}
                    onClick={() => set({ fit: "crop", inner: "" })}>Phủ kín khung</button>
          )}
          <button type="button" className={`dx-format__chip dx-format__chip--sm${!fill && !inner ? " is-on" : ""}`} disabled={readOnly}
                  title="Giữ nguyên cả hình video, phần còn lại của khung là nền"
                  onClick={() => set({ fit: bg ?? lastBg.current, inner: "" })}>Nguyên hình{srcShape ? ` ${srcShape}` : ""}</button>
          {cutShapes.map((a) => (
            <button key={a.key} type="button" className={`dx-format__chip dx-format__chip--sm${inner === a.key ? " is-on" : ""}`} disabled={readOnly}
                    title={`Cắt video về khung ${a.key} rồi đặt lên nền của khung ${c.aspect}`}
                    onClick={() => set({ fit: bg ?? lastBg.current, inner: a.key })}>Cắt {a.key}</button>
          ))}
          {cutting && (
            <label className="dx-format__pos" title="Cắt lệch về bên nào (trái / phải hoặc trên / dưới)">
              Vị trí cắt
              <TickRange min={0} max={1} step={0.01} value={c.cut} disabled={readOnly}
                         onChange={(v) => set({ cut: v }, "canvas-cut")} />
            </label>
          )}
          {!fill && (
            <>
              <label className="dx-format__pos" title="Video nằm trên / dưới (hoặc trái / phải) trong khung">
                Vị trí video
                <TickRange min={0} max={1} step={0.01} value={c.pos} disabled={readOnly}
                           onChange={(v) => set({ pos: v }, "canvas-pos")} />
              </label>
              <label className="dx-format__pos" title="Cỡ video trong khung — nhỏ hơn thì nền hiện xung quanh">
                Cỡ video {Math.round(c.scale * 100)}%
                <TickRange min={0.5} max={1} step={0.01} value={c.scale} disabled={readOnly} every={0.05}
                           marks={[0.5, 0.75, 1]} onChange={(v) => set({ scale: v }, "canvas-scale")} />
              </label>
            </>
          )}
        </div>
      )}

      <div className="dx-format__row dx-format__fit" role="group" aria-label="Nền quanh video">
        <span className="dx-format__label" title="Phần khung không có video — thay cho phần đen app tự thêm">Nền</span>
        {BACKGROUNDS.map((f) => (
          <button key={f.key} type="button" className={`dx-format__chip dx-format__chip--sm${bg === f.key ? " is-on" : ""}`} disabled={readOnly}
                  title={f.hint} onClick={() => pickBg(f.key)}>{f.label}</button>
        ))}
        {bg && (bg === "color" || bg === "grid") && c && (
          <label className="dx-format__color" title={bg === "grid" ? "Màu nền của lưới" : "Màu nền"}>
            {bg === "grid" ? "Nền" : "Màu"}
            <input type="color" value={c.color} disabled={readOnly} onChange={(e) => set({ color: e.target.value }, "canvas-color")} />
          </label>
        )}
        {bg === "grid" && c && (
          <>
            <label className="dx-format__color" title="Màu đường kẻ">
              Kẻ
              <input type="color" value={c.line} disabled={readOnly} onChange={(e) => set({ line: e.target.value }, "canvas-line")} />
            </label>
            <label className="dx-format__pos" title="Cỡ ô lưới">
              Ô
              <TickRange min={0.04} max={0.3} step={0.01} value={c.cell} disabled={readOnly} every={0.02}
                         marks={[0.04, 0.11, 0.3]} onChange={(v) => set({ cell: v }, "canvas-cell")} />
            </label>
          </>
        )}
        {needsFile && c && (
          <span className="dx-format__file">
            <button type="button" className="qt-btn qt-btn--small" disabled={readOnly || uploading} onClick={() => fileInput.current?.click()}>
              {uploading ? "Đang tải lên…" : c.media_id ? `⬆ Đổi ${bg === "video" ? "video" : "ảnh"}` : `⬆ Chọn ${bg === "video" ? "video" : "ảnh"} nền`}
            </button>
            {!c.media_id && <small className="dx-format__warn">chưa có file — tạm dùng màu nền</small>}
          </span>
        )}
        <input ref={fileInput} type="file" hidden
               accept={bg === "video" ? "video/mp4,video/quicktime,video/webm,image/gif" : bg === "image" ? "image/jpeg,image/png,image/webp" : "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,image/gif"}
               onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f); }} />
        {(!c || fill) && (
          <small className="dx-format__hint">
            {fill
              ? `Video đang phủ kín khung ${c?.aspect} — chọn một nền: video giữ hình ${c?.aspect}, đặt giữa khung ${platform === "youtube" ? "16:9" : "9:16"} trên nền đó.`
              : `Chọn một nền: cả video đặt giữa khung ${platform === "youtube" ? "16:9" : "9:16"} trên nền đó.`}
          </small>
        )}
        {same && bg && !inner && c && c.scale >= 0.999 && <small className="dx-format__warn">video đã đúng khung — kéo “Cỡ video” nhỏ lại để thấy nền</small>}
      </div>
    </div>
  );
}
