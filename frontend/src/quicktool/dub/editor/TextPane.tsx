import { useEffect, useRef } from "react";
import {
  ADJUST_RANGE, MAX_TEXTS, NO_ADJUST, normAdjust, normText, TEXT_DEFAULTS, TEXT_ROLE_LABEL,
  type DubAdjust, type DubText,
} from "../../../api/dub";
import { TickRange } from "../../../components/TickRange";

const pct = (v: number) => `${Math.round(v * 100)}%`;

/** Ready-made looks: text colour + box colour ("" = no box, the text gets an outline). */
const LOOKS: { label: string; color: string; bg: string }[] = [
  { label: "Trắng / đỏ", color: "#ffffff", bg: "#e5322d" },
  { label: "Đen / vàng", color: "#141414", bg: "#ffd814" },
  { label: "Đen / trắng", color: "#141414", bg: "#ffffff" },
  { label: "Trắng / đen", color: "#ffffff", bg: "#111111" },
  { label: "Trắng viền đen", color: "#ffffff", bg: "" },
  { label: "Vàng viền đen", color: "#ffd814", bg: "" },
];
const Y_PRESETS: { label: string; y: number }[] = [{ label: "Trên", y: 0.09 }, { label: "Giữa", y: 0.5 }, { label: "Dưới", y: 0.9 }];
const SHOW: { secs: number; label: string }[] = [
  { secs: 0, label: "Cả clip" }, { secs: 3, label: "3 giây đầu" }, { secs: 5, label: "5 giây đầu" }, { secs: 10, label: "10 giây đầu" },
];

export const textLabel = (texts: DubText[], i: number): string => {
  const t = texts[i];
  if (!t) return "";
  return t.role === "text" ? `Chữ ${texts.slice(0, i + 1).filter((x) => x.role === "text").length}` : TEXT_ROLE_LABEL[t.role];
};

/**
 * "🔤 Chữ": text on the picture for the whole clip. Two slots are always there — the title and the second title
 * (the words typed when the video was cut; empty when there were none) — switched on with one tick; free text is
 * added below. The selected layer's words, size, colours, box, width, place and how long it shows are set here;
 * dragging it on the preview moves it.
 */
export function TextPane({ texts, selected, onSelect, onTexts, readOnly, focus, cutWords }: {
  texts: DubText[];
  selected: number | null;
  onSelect: (i: number | null) => void;
  /** coalesce: successive changes with the same key are one undo step */
  onTexts: (next: DubText[], coalesce?: string) => void;
  readOnly: boolean;
  /** changes → the words box of the selected layer takes the focus (double-click on the preview) */
  focus: number;
  /** the words this clip was cut with: "↺" puts them back */
  cutWords: { title: string; subtitle: string };
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (focus) { box.current?.focus(); box.current?.select(); } }, [focus]);
  const cur = selected !== null ? texts[selected] ?? null : null;
  const set = (i: number, patch: Partial<DubText>, key?: string) =>
    onTexts(texts.map((t, k) => (k === i ? { ...t, ...patch } : t)), key ? `${key}-${i}` : undefined);
  const setCur = (patch: Partial<DubText>, key?: string) => { if (selected !== null) set(selected, patch, key); };
  function add() {
    if (texts.length >= MAX_TEXTS) return;
    // not on top of another free text
    const taken = texts.filter((t) => t.role === "text").length;
    onTexts([...texts, normText({ role: "text", on: true, text: "Chữ mới", bg: "", y: Math.min(0.9, TEXT_DEFAULTS.text.y + taken * 0.08) })]);
    onSelect(texts.length);
    window.setTimeout(() => { box.current?.focus(); box.current?.select(); }, 0);
  }
  function remove(i: number) {
    onTexts(texts.filter((_, k) => k !== i));
    onSelect(null);
  }
  function toggle(i: number, on: boolean) {
    set(i, { on });
    if (on) {
      onSelect(i);
      if (!texts[i].text.trim()) window.setTimeout(() => box.current?.focus(), 0);
    }
  }
  const back = cur && cur.role !== "text" ? cutWords[cur.role] : "";

  return (
    <section className="dx-insp__sec dx-text">
      <p className="dx-insp__tip">Chữ nằm trên video: <b>tiêu đề</b> và <b>tiêu đề phụ</b> (lời đã nhập lúc cắt video — chưa có thì để trống, gõ ở đây),
        hoặc chữ tự thêm. Tick để hiện, kéo chữ trên video để đặt chỗ.</p>
      <ol className="dx-text__list">
        {texts.map((t, i) => (
          <li key={i} className={`${i === selected ? "is-on" : ""}${t.on ? "" : " is-off"}`}>
            <label className="dx-text__tick" title={t.on ? "Đang hiện trên video — bỏ tick để ẩn" : "Tick để hiện trên video"}>
              <input type="checkbox" checked={t.on} disabled={readOnly} onChange={(e) => toggle(i, e.target.checked)} />
            </label>
            <button type="button" className="dx-text__pick" onClick={() => onSelect(i)}>
              <strong>{textLabel(texts, i)}</strong>
              <small>{t.text.trim() ? t.text.replace(/\s+/g, " ") : "(chưa có chữ)"}</small>
            </button>
            {t.role === "text" && (
              <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={readOnly} title="Xoá chữ này" onClick={() => remove(i)}>🗑</button>
            )}
          </li>
        ))}
      </ol>
      <div className="qt-post__actions">
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={readOnly || texts.length >= MAX_TEXTS} onClick={add}>＋ Thêm chữ</button>
      </div>

      {cur && selected !== null && (
        <>
          <h4 className="dx-insp__h">{textLabel(texts, selected)}{cur.on ? "" : <small>đang ẩn — tick để hiện</small>}</h4>
          <textarea ref={box} className="qt-input dx-text__words" rows={2} value={cur.text} disabled={readOnly} maxLength={300}
                    placeholder={cur.role === "title" ? "Gõ tiêu đề…" : cur.role === "subtitle" ? "Gõ tiêu đề phụ…" : "Gõ chữ…"}
                    onChange={(e) => setCur({ text: e.target.value }, "text-words")} />
          {back && back !== cur.text && (
            <button type="button" className="qt-link" disabled={readOnly} onClick={() => setCur({ text: back })}>↺ Lấy lại lời lúc cắt: “{back.slice(0, 40)}{back.length > 40 ? "…" : ""}”</button>
          )}
          <div className="dx-text__looks" role="group" aria-label="Kiểu màu có sẵn">
            {LOOKS.map((l) => (
              <button key={l.label} type="button" disabled={readOnly} title={l.label}
                      className={`dx-text__look${cur.color === l.color && cur.bg === l.bg ? " is-on" : ""}`}
                      style={l.bg ? { color: l.color, background: l.bg } : { color: l.color, background: "#3a3a42", textShadow: "0 0 2px #000, 0 0 2px #000" }}
                      onClick={() => setCur({ color: l.color, bg: l.bg })}>Aa</button>
            ))}
          </div>
          <div className="dx-text__colors">
            <label title="Màu chữ">Màu chữ <input type="color" value={cur.color} disabled={readOnly} onChange={(e) => setCur({ color: e.target.value }, "text-color")} /></label>
            <label title="Có nền: một ô màu sau chữ. Không nền: chữ có viền để dễ đọc">
              <input type="checkbox" checked={!!cur.bg} disabled={readOnly} onChange={(e) => setCur({ bg: e.target.checked ? "#111111" : "" })} /> Nền
              {cur.bg && <input type="color" value={cur.bg} disabled={readOnly} onChange={(e) => setCur({ bg: e.target.value }, "text-bg")} />}
            </label>
            <span className="dx-text__biu" role="group" aria-label="Kiểu chữ">
              <button type="button" className={cur.bold ? "is-on" : ""} aria-pressed={cur.bold} disabled={readOnly} title="Chữ đậm"
                      onClick={() => setCur({ bold: !cur.bold })}><b>B</b></button>
              <button type="button" className={cur.italic ? "is-on" : ""} aria-pressed={cur.italic} disabled={readOnly} title="Chữ nghiêng"
                      onClick={() => setCur({ italic: !cur.italic })}><i>I</i></button>
              <button type="button" className={cur.underline ? "is-on" : ""} aria-pressed={cur.underline} disabled={readOnly} title="Gạch chân"
                      onClick={() => setCur({ underline: !cur.underline })}><u>U</u></button>
            </span>
          </div>
          {cur.bold && (
            <label className="qt-field" title="Chữ đậm nhiều hay ít: 100% = đậm thường; kéo trái cho nhạt bớt, kéo phải cho đậm hơn">
              <span>Độ đậm <small>{pct(cur.weight)}</small></span>
              <TickRange min={0.3} max={2.5} step={0.05} value={cur.weight} disabled={readOnly} every={0.1} marks={[0.5, 1, 1.5, 2]}
                         onChange={(v) => setCur({ weight: v }, "text-weight")} />
            </label>
          )}
          <div className="dx-insp__row2">
            <label className="qt-field"><span>Cỡ chữ <small>{pct(cur.size)}</small></span>
              <TickRange min={0.5} max={4} step={0.05} value={cur.size} disabled={readOnly} every={0.5} marks={[1, 2, 3]}
                         onChange={(v) => setCur({ size: v }, "text-size")} /></label>
            <label className="qt-field"><span>Rộng tối đa <small>{pct(cur.w)}</small></span>
              <TickRange min={0.2} max={0.96} step={0.01} value={cur.w} disabled={readOnly} every={0.1} marks={[0.5, 0.86]}
                         onChange={(v) => setCur({ w: v }, "text-w")} /></label>
            <label className="qt-field"><span>Vị trí ngang <small>{pct(cur.x)}</small></span>
              <TickRange min={0.02} max={0.98} step={0.005} value={cur.x} disabled={readOnly} every={0.1} marks={[0.25, 0.5, 0.75]}
                         onChange={(v) => setCur({ x: v }, "text-x")} /></label>
            <label className="qt-field"><span>Vị trí dọc <small>{pct(cur.y)}</small></span>
              <TickRange min={0.03} max={0.97} step={0.005} value={cur.y} disabled={readOnly} every={0.1} marks={[0.09, 0.5, 0.9]}
                         onChange={(v) => setCur({ y: v }, "text-y")} /></label>
          </div>
          <div className="qt-post__actions">
            {Y_PRESETS.map((p) => (
              <button key={p.label} type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={readOnly}
                      onClick={() => setCur({ x: 0.5, y: p.y })}>{p.label}</button>
            ))}
            <label className="dx-text__show" title="Chữ hiện suốt clip, hay chỉ mấy giây đầu">
              Hiện
              <select value={SHOW.some((s) => s.secs === cur.secs) ? cur.secs : -1} disabled={readOnly}
                      onChange={(e) => setCur({ secs: Number(e.target.value) })}>
                {SHOW.map((s) => <option key={s.secs} value={s.secs}>{s.label}</option>)}
                {!SHOW.some((s) => s.secs === cur.secs) && <option value={-1}>{cur.secs} giây đầu</option>}
              </select>
            </label>
          </div>
        </>
      )}
    </section>
  );
}

const ADJUSTS: { key: keyof DubAdjust; label: string; lo: string; hi: string }[] = [
  { key: "brightness", label: "Sáng / tối", lo: "tối", hi: "sáng" },
  { key: "contrast", label: "Tương phản", lo: "nhạt", hi: "gắt" },
  { key: "saturation", label: "Màu", lo: "xám", hi: "rực" },
];

/** "🎚 Sáng / tối & màu" of the video itself (not the background, the text or the sticker) — exported as shown. */
export function AdjustPane({ adjust, onAdjust, readOnly }: {
  adjust: DubAdjust | null | undefined;
  onAdjust: (a: DubAdjust | null, coalesce?: string) => void;
  readOnly: boolean;
}) {
  const a = adjust ?? NO_ADJUST;
  return (
    <div className="dx-adjust" role="group" aria-label="Sáng tối và màu của video">
      <div className="dx-adjust__head">
        <span className="dx-format__label">Sáng / tối &amp; màu</span>
        {adjust && <button type="button" className="qt-link" disabled={readOnly} onClick={() => onAdjust(null)}>↺ Về như gốc</button>}
      </div>
      {ADJUSTS.map((x) => {
        const [lo, hi] = ADJUST_RANGE[x.key];
        return (
          <label key={x.key} className="dx-adjust__row" title={`${x.label}: kéo trái = ${x.lo}, phải = ${x.hi}; 100% = như video gốc`}>
            <span>{x.label} <small>{pct(a[x.key])}</small></span>
            <TickRange min={lo} max={hi} step={0.01} value={a[x.key]} disabled={readOnly} every={0.1} marks={[1]}
                       onChange={(v) => onAdjust(normAdjust({ ...a, [x.key]: v }), `adjust-${x.key}`)} />
          </label>
        );
      })}
    </div>
  );
}
