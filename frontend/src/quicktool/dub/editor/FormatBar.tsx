import {
  CANVAS_ASPECTS, CANVAS_FITS, canvasSize, type CanvasAspect, type CanvasFit, type DubCanvas, type DubLayout,
} from "../../../api/dub";
import { PLATFORMS, type PlatformKey } from "./platforms";

/** Where the source picture sits inside the output frame (fractions of the frame): the format's fit, then the
 * decorative frame's shrink — the same steps as the render (services/dub.canvas_filter, dub_decor.frame_filter). */
export function sourceRect(srcW: number, srcH: number, layout: DubLayout): { x: number; y: number; w: number; h: number } {
  let r = { x: 0, y: 0, w: 1, h: 1 };
  const c = layout.canvas;
  if (c && srcW > 0 && srcH > 0) {
    const { w: cw, h: ch } = canvasSize(srcW, srcH, c);
    const k = c.fit === "crop" ? Math.max(cw / srcW, ch / srcH) : Math.min(cw / srcW, ch / srcH);
    const w = (srcW * k) / cw, h = (srcH * k) / ch;
    r = c.fit === "crop" ? { x: -(w - 1) * c.pos, y: -(h - 1) * c.pos, w, h } : { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
  }
  const f = layout.frame;
  if (f) {
    const m = (1 - f.scale) / 2;
    r = { x: m + f.scale * r.x, y: m + f.scale * r.y, w: f.scale * r.w, h: f.scale * r.h };
  }
  return r;
}

/** A box given on the source picture (e.g. an OCR text band) → the same place on the output frame, clipped to it. */
export function sourceBoxToFrame(box: { x: number; y: number; w: number; h: number }, srcW: number, srcH: number, layout: DubLayout) {
  const r = sourceRect(srcW, srcH, layout);
  const x0 = Math.max(0, r.x + box.x * r.w), y0 = Math.max(0, r.y + box.y * r.h);
  const x1 = Math.min(1, r.x + (box.x + box.w) * r.w), y1 = Math.min(1, r.y + (box.y + box.h) * r.h);
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

/** "Khung xuất": the output format above the preview — the preview switches to it at once, the export comes out in it. */
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
  const set = (patch: Partial<DubCanvas> | null, key?: string) =>
    onLayout({ ...layout, canvas: patch === null ? null : { aspect: "9:16", fit: "blur", pos: 0.5, ...(c ?? {}), ...patch } }, key);

  return (
    <div className="dx-format" role="group" aria-label="Khung xuất">
      <span className="dx-format__label">Khung xuất</span>
      <div className="dx-format__chips">
        <button type="button" className={`dx-format__chip${!c ? " is-on" : ""}`} disabled={readOnly} onClick={() => set(null)}
                title="Giữ đúng kích thước video gốc">
          <Shape w={srcW || 9} h={srcH || 16} /> Gốc{srcW ? ` ${shapeOf(srcW, srcH)}` : ""}
        </button>
        {CANVAS_ASPECTS.filter((a) => !(srcW && srcH && Math.abs(a.w / a.h - srcW / srcH) < 0.01) || c?.aspect === a.key).map((a) => (
          <button key={a.key} type="button" className={`dx-format__chip${c?.aspect === a.key ? " is-on" : ""}`} disabled={readOnly}
                  title={a.hint} onClick={() => set({ aspect: a.key as CanvasAspect })}>
            <Shape w={a.w} h={a.h} /> {a.key}
          </button>
        ))}
      </div>
      {c && !same && (
        <div className="dx-format__fit">
          {CANVAS_FITS.map((f) => (
            <button key={f.key} type="button" className={`dx-format__chip dx-format__chip--sm${c.fit === f.key ? " is-on" : ""}`} disabled={readOnly}
                    onClick={() => set({ fit: f.key as CanvasFit })}>{f.label}</button>
          ))}
          {c.fit === "crop" && (
            <label className="dx-format__pos" title="Cắt lệch về bên nào (trái / phải hoặc trên / dưới)">
              Vị trí cắt
              <input type="range" min={0} max={1} step={0.01} value={c.pos} disabled={readOnly}
                     onChange={(e) => set({ pos: Number(e.target.value) }, "canvas-pos")} />
            </label>
          )}
        </div>
      )}
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
  );
}
