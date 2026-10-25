import type { ReactNode } from "react";
import type { FlowNode, FlowboardNodeData, OverlaySpec } from "../../store/board";

interface Clip {
  index: number;
  image: FlowNode;
  video: FlowNode | null;
}

/** The clips in the order step 5 will join them (picks on the export node). */
export function orderedClips<T extends Clip>(clips: T[], exp: FlowNode | null): T[] {
  const order = Array.isArray(exp?.data.clipOrder) ? exp!.data.clipOrder : [];
  const rank = (c: T) => { const i = order.indexOf(c.video?.id ?? ""); return i < 0 ? 1000 + c.index : i; };
  return [...clips].sort((a, b) => rank(a) - rank(b));
}

/** "Thứ tự & cắt cảnh": move clips up/down, leave one out, cut its start/end. */
export function ClipArranger<T extends Clip>({ clips, exp, busy, setOption, renderLine }: {
  clips: T[];
  exp: FlowNode | null;
  busy: boolean;
  setOption(patch: Partial<FlowboardNodeData>): void;
  renderLine(clip: T): ReactNode;
}) {
  const ordered = orderedClips(clips, exp);
  const skip = new Set(Array.isArray(exp?.data.clipSkip) ? exp!.data.clipSkip : []);
  const trims = exp?.data.clipTrims ?? {};

  function move(i: number, d: -1 | 1) {
    const ids = ordered.map((c) => c.video!.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setOption({ clipOrder: ids });
  }
  function toggleSkip(id: string) {
    const next = new Set(skip);
    if (next.has(id)) next.delete(id); else next.add(id);
    setOption({ clipSkip: [...next] });
  }
  function setTrim(id: string, which: 0 | 1, raw: string) {
    const cur: [number, number | null] = trims[id] ?? [0, null];
    const v = raw.trim() === "" ? null : Math.max(0, Number(raw));
    if (v !== null && Number.isNaN(v)) return;
    const next: [number, number | null] = which === 0 ? [v ?? 0, cur[1]] : [cur[0], v];
    const all = { ...trims };
    if (next[0] === 0 && next[1] === null) delete all[id]; else all[id] = next;
    setOption({ clipTrims: all });
  }

  return (
    <ol className="qt-cliplist qt-arrange">
      {ordered.map((s, i) => {
        const id = s.video!.id;
        const off = skip.has(id);
        const t = trims[id];
        return (
          <li key={id} className={off ? "qt-arrange--off" : undefined}>
            <span className="qt-cliplist__num">{i + 1}</span>
            <span className="qt-cliplist__title">
              {s.image.data.title}
              {off && <small> · bỏ khỏi clip</small>}
              {!off && t && <small> · cắt {t[0]}s → {t[1] ?? "hết"}{t[1] !== null ? "s" : ""}</small>}
            </span>
            <span className="qt-cliplist__line">{renderLine(s)}</span>
            <span className="qt-arrange__tools">
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy || i === 0}
                      title="Lên trước" onClick={() => move(i, -1)}>↑</button>
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy || i === ordered.length - 1}
                      title="Xuống sau" onClick={() => move(i, 1)}>↓</button>
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy}
                      onClick={() => toggleSkip(id)}>{off ? "Dùng lại" : "Bỏ cảnh"}</button>
              {!off && (
                <label className="qt-arrange__trim" title="Cắt bớt đầu/cuối cảnh này (giây). Để trống = giữ nguyên.">
                  Cắt từ
                  <input type="number" min={0} step={0.5} disabled={busy} value={t ? t[0] : ""} placeholder="0"
                         onChange={(e) => setTrim(id, 0, e.target.value)} />
                  đến
                  <input type="number" min={0} step={0.5} disabled={busy} value={t && t[1] !== null ? t[1] : ""} placeholder="hết"
                         onChange={(e) => setTrim(id, 1, e.target.value)} />
                  s
                </label>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const PRESET_LABEL: Record<OverlaySpec["preset"], string> = {
  title: "Tiêu đề (chữ trắng to)",
  price: "Giá (chữ vàng nền đỏ)",
  badge: "Nhãn (nền cam)",
  cta: "Kêu gọi (nền tối)",
};
const POSITION_LABEL: Record<OverlaySpec["position"], string> = { top: "Trên", middle: "Giữa", bottom: "Dưới" };

/** "Chữ trên video": quick presets + free text, burned on the joined clip. */
export function OverlayEditor({ exp, busy, setOption, productName, price }: {
  exp: FlowNode | null;
  busy: boolean;
  setOption(patch: Partial<FlowboardNodeData>): void;
  productName: string;
  price: string;
}) {
  const list: OverlaySpec[] = Array.isArray(exp?.data.overlays) ? exp!.data.overlays : [];
  const quick: { label: string; make(): OverlaySpec }[] = [
    { label: "+ Tên sản phẩm", make: () => ({ text: productName || "Tên sản phẩm", preset: "title", position: "top", start: 0, end: 3 }) },
    { label: "+ Giá", make: () => ({ text: price ? `Chỉ ${price}` : "Giá sốc hôm nay", preset: "price", position: "bottom", start: -4, end: null }) },
    { label: "+ Freeship", make: () => ({ text: "Freeship", preset: "badge", position: "top", start: 0, end: null }) },
    { label: "+ 👇 Bấm giỏ hàng", make: () => ({ text: "👇 Bấm giỏ hàng bên dưới", preset: "cta", position: "bottom", start: -4, end: null }) },
    { label: "+ Chữ tự gõ", make: () => ({ text: "", preset: "title", position: "middle", start: 0, end: null }) },
  ];

  function save(next: OverlaySpec[]) {
    setOption({ overlays: next });
  }
  function update(i: number, patch: Partial<OverlaySpec>) {
    save(list.map((o, k) => (k === i ? { ...o, ...patch } : o)));
  }
  function num(raw: string): number | null {
    if (raw.trim() === "") return null;
    const v = Number(raw);
    return Number.isNaN(v) ? null : Math.max(0, v);
  }

  return (
    <div className="qt-overlays">
      <div className="qt-overlays__head">
        <strong>Chữ trên video</strong>
        <small>In lên clip khi ghép · tối đa 8 dòng · cùng vị trí thì xếp chồng · "từ" số âm = tính từ cuối (−4 = 4 giây cuối)</small>
      </div>
      <div className="qt-regen__chips">
        {quick.map((q) => (
          <button key={q.label} type="button" className="qt-regen__chip" disabled={busy || list.length >= 8}
                  onClick={() => save([...list, q.make()])}>{q.label}</button>
        ))}
      </div>
      {list.map((o, i) => (
        <div key={i} className="qt-overlay-row">
          <input className="qt-textarea" value={o.text} maxLength={80} disabled={busy} placeholder="Chữ hiện trên video"
                 onChange={(e) => update(i, { text: e.target.value })} />
          <select value={o.preset} disabled={busy} onChange={(e) => update(i, { preset: e.target.value as OverlaySpec["preset"] })}>
            {Object.entries(PRESET_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={o.position} disabled={busy} onChange={(e) => update(i, { position: e.target.value as OverlaySpec["position"] })}>
            {Object.entries(POSITION_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label className="qt-arrange__trim">
            từ <input type="number" step={0.5} disabled={busy} value={o.start}
                      onChange={(e) => update(i, { start: e.target.value.trim() === "" ? 0 : Number(e.target.value) || 0 })} />
            đến <input type="number" min={0} step={0.5} disabled={busy} value={o.end ?? ""} placeholder="hết"
                       onChange={(e) => update(i, { end: num(e.target.value) })} /> s
          </label>
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy}
                  onClick={() => save(list.filter((_, k) => k !== i))}>Xoá</button>
        </div>
      ))}
    </div>
  );
}
