import { useEffect, useRef, type ReactNode } from "react";
import {
  DEFAULT_BLUR, DEFAULT_LAYOUT, emphasisY, HL_Y_MAX, HL_Y_MIN, layoutBlurs, linesAreVietnamese, MAX_BLURS, SUB_LANGS,
  subLangName, withBlurs,
  type DubBlur, type DubEngine, type DubHighlights, type DubLayout, type DubMode, type DubStatus, type SubLang,
} from "../../../api/dub";
import { ChannelPicker } from "../../channels/ChannelPicker";
import { VoiceField } from "../../VoiceField";
import { DecorControls } from "../DecorControls";
import { clock, effectiveLayout, readingLoad, W_MAX, W_MIN, type EditCue, type GeomPatch } from "./cues";
import type { Sel } from "./EditorStage";

export type InspectorTab = "sub" | "list" | "hl" | "blur" | "decor" | "cut" | "out";

const TABS: { key: InspectorTab; label: string }[] = [
  { key: "sub", label: "💬 Phụ đề" },
  { key: "list", label: "📜 Các câu" },
  { key: "hl", label: "✨ Nhấn" },
  { key: "blur", label: "🌫 Làm mờ" },
  { key: "decor", label: "🎨 Trang trí" },
  { key: "cut", label: "✂️ Cắt" },
  { key: "out", label: "⚙ Xuất" },
];

/** What the "✨ Nhấn" tab needs from the editor. */
export interface HighlightsCtl {
  value: DubHighlights;
  set: (patch: Partial<DubHighlights>, coalesce?: string) => void;
  /** "✨ AI chọn chữ quan trọng" — runs on the agent (a few seconds) */
  pick: () => void;
  picking: boolean;
  /** "+ Thêm ở giờ đang xem" */
  addAtNow: () => void;
  setPoint: (i: number, patch: { at?: number; words?: string }) => void;
  removePoint: (i: number) => void;
  /** the preview's clock, for "+ Thêm" and the list's highlight */
  now: number;
  onPickPoint: (i: number) => void;
}

const POS_PRESETS: { label: string; y: number }[] = [
  { label: "Trên", y: 0.2 }, { label: "Giữa", y: 0.55 }, { label: "Dưới", y: 0.8 }, { label: "Sát đáy", y: 0.93 },
];
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const pct = (v: number) => `${Math.round(v * 100)}%`;

export interface OutSettings {
  /** voice-over or subtitles only */
  mode: DubMode;
  name: string;
  voice: string;
  engine: DubEngine;
  keepBgm: boolean;
  channelId: number | null;
}

export function Inspector({
  tab, onTab, selected, onSelect, cues, origin, onCueText, onCueTiming, onPlayCue,
  layout, onLayout, style, onStyle, styles, status, out, onOut, orientation,
  readOnly, focusText, onDetect, detecting, activeCue, onPickCue,
  scope, onScope, onGeom, onApplyAll, onClearLook, onClearAll, customCount, hl, cutPane, lang,
}: {
  tab: InspectorTab;
  onTab: (t: InspectorTab) => void;
  selected: Sel;
  onSelect: (s: Sel) => void;
  cues: EditCue[];
  origin: { start: number; end: number; text: string }[];
  onCueText: (i: number, text: string) => void;
  onCueTiming: (i: number, start: number, end: number) => void;
  onPlayCue: (i: number) => void;
  layout: DubLayout;
  onLayout: (l: DubLayout, coalesce?: string) => void;
  style: string;
  onStyle: (s: string) => void;
  styles: { key: string; label: string }[];
  status: DubStatus;
  out: OutSettings;
  onOut: (patch: Partial<OutSettings>) => void;
  orientation: "portrait" | "landscape" | "square";
  readOnly: boolean;
  /** bumps when the text box should take focus (double-click on the timeline) */
  focusText: number;
  onDetect: (() => void) | null;
  detecting: boolean;
  activeCue: number | null;
  /** select a line and jump the preview to it */
  onPickCue: (i: number) => void;
  /** what the placement controls change: the selected line only, or every line */
  scope: "all" | "cue";
  onScope: (s: "all" | "cue") => void;
  onGeom: (patch: GeomPatch, coalesce?: string) => void;
  onApplyAll: (i: number) => void;
  onClearLook: (i: number) => void;
  onClearAll: () => void;
  customCount: number;
  hl: HighlightsCtl;
  /** "✂️ Cắt": cut the exported video into several clips */
  cutPane: ReactNode;
  /** "Ngôn ngữ phụ đề": the lines' language now, the video's own (Whisper), switching (rewrites every line) */
  lang: { value: SubLang; source: string; busy: boolean; set: (l: SubLang) => void };
}) {
  const textRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (focusText && textRef.current) { textRef.current.focus(); textRef.current.select(); }
  }, [focusText]);

  const i = selected?.kind === "cue" ? selected.i : null;
  const cue = i !== null ? cues[i] : null;
  // the placement the controls show and change: the selected line's own (Riêng câu này) or the clip-wide one
  const own = scope === "cue" && cue !== null;
  const geo = effectiveLayout(layout, own ? cue?.look : null);
  const setPos = (patch: GeomPatch, key: string) => {
    const out: GeomPatch = {};
    if (patch.x !== undefined) out.x = clamp(patch.x, 0.05, 0.95);
    if (patch.y !== undefined) out.y = clamp(patch.y, 0.08, 0.98);
    if (patch.scale !== undefined) out.scale = clamp(patch.scale, 0.5, 2.2);
    if (patch.w !== undefined) out.w = patch.w === null ? null : clamp(patch.w, W_MIN, W_MAX);
    onGeom(out, key);
  };
  // several blur boxes: the panel edits the one selected on the picture (the first one otherwise)
  const blurs = layoutBlurs(layout);
  const bi = selected?.kind === "blur" ? Math.min(selected.i, blurs.length - 1) : 0;
  const blur = blurs[bi] ?? null;
  const setBlur = (patch: Partial<DubBlur>, key: string) => {
    if (!blur) return;
    const b = { ...blur, ...patch };
    b.x = clamp(b.x, 0, 0.95);
    b.y = clamp(b.y, 0, 0.97);
    b.w = clamp(b.w, 0.05, 1 - b.x);
    b.h = clamp(b.h, 0.02, 1 - b.y);
    b.amount = clamp(Math.round(b.amount), 1, 10);
    onLayout(withBlurs(layout, blurs.map((x, k) => (k === bi ? b : x))), key ? `${key}-${bi}` : undefined);
  };
  const addBlur = () => {
    if (blurs.length >= MAX_BLURS) return;
    // a new box under the last one (or at the top when there is no room), same width and blur
    const last = blurs[blurs.length - 1];
    const nb = last ? { ...last, y: last.y + last.h + 0.03 + last.h <= 0.97 ? last.y + last.h + 0.03 : 0.08 } : { ...DEFAULT_BLUR };
    onLayout(withBlurs(layout, [...blurs, nb]));
    onSelect({ kind: "blur", i: blurs.length });
  };
  const removeBlur = (i: number) => {
    onLayout(withBlurs(layout, blurs.filter((_, k) => k !== i)));
    onSelect(blurs.length > 1 ? { kind: "blur", i: Math.max(0, i - 1) } : null);
  };
  const engineStyles = out.engine === "remotion" ? status.remotion_styles ?? [] : status.styles;

  return (
    <aside className="dx-insp">
      <div className="dx-insp__tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
                  className={`dx-insp__tab${tab === t.key ? " is-on" : ""}`} onClick={() => onTab(t.key)}>{t.label}</button>
        ))}
      </div>
      <div className="dx-insp__body">
        {tab === "sub" && (
          <>
            {cue && i !== null ? (
              <section className="dx-insp__sec">
                <div className="dx-insp__cuehead">
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={i === 0} title="Câu trước (↑)"
                          onClick={() => onSelect({ kind: "cue", i: i - 1 })}>‹</button>
                  <strong>Câu {i + 1}<small> / {cues.length}</small></strong>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={i === cues.length - 1} title="Câu sau (↓)"
                          onClick={() => onSelect({ kind: "cue", i: i + 1 })}>›</button>
                  <button type="button" className="qt-btn qt-btn--small" onClick={() => onPlayCue(i)}>▶ Nghe câu này</button>
                </div>
                {cue.src && <p className="dx-insp__src" title="Câu gốc">{cue.src}</p>}
                <textarea ref={textRef} className="qt-textarea dx-insp__text" rows={3} value={cue.text} disabled={readOnly}
                          placeholder="(để trống = bỏ câu này: không đọc, không phụ đề)"
                          onChange={(e) => onCueText(i, e.target.value)} />
                <Load cue={cue} />
                <div className="dx-insp__times">
                  <TimeField label="Bắt đầu" value={cue.start} disabled={readOnly}
                             onChange={(v) => onCueTiming(i, v, Math.max(cue.end, v + 0.3))} />
                  <TimeField label="Kết thúc" value={cue.end} disabled={readOnly}
                             onChange={(v) => onCueTiming(i, cue.start, v)} />
                  <span className="dx-insp__len">{(cue.end - cue.start).toFixed(1)} s</span>
                </div>
                <div className="qt-post__actions">
                  {cue.text.trim()
                    ? <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={readOnly} onClick={() => onCueText(i, "")}>🗑 Bỏ câu này</button>
                    : null}
                  {origin[i] && origin[i].text !== cue.text && (
                    <button type="button" className="qt-btn qt-btn--small" disabled={readOnly} onClick={() => onCueText(i, origin[i].text)}>↺ Về bản dịch cũ</button>
                  )}
                  {origin[i] && (Math.abs(origin[i].start - cue.start) > 0.005 || Math.abs(origin[i].end - cue.end) > 0.005) && (
                    <button type="button" className="qt-btn qt-btn--small" disabled={readOnly}
                            onClick={() => onCueTiming(i, origin[i].start, origin[i].end)}>↺ Về thời gian cũ</button>
                  )}
                </div>
              </section>
            ) : (
              <p className="dx-insp__empty">Bấm một khối phụ đề trên timeline, hoặc bấm vào phụ đề trên video, để sửa câu đó. Bấm đúp phụ đề trên video để gõ thẳng lên hình.</p>
            )}

            <section className="dx-insp__sec">
              <h4>Vị trí, cỡ & độ rộng</h4>
              <div className="dx-scope" role="radiogroup" aria-label="Chỉnh cho">
                <span>Chỉnh cho</span>
                <button type="button" role="radio" aria-checked={scope === "cue"} className={scope === "cue" ? "is-on" : ""}
                        title="Kéo / chỉnh chỉ đổi câu đang chọn" onClick={() => onScope("cue")}>Riêng câu này</button>
                <button type="button" role="radio" aria-checked={scope === "all"} className={scope === "all" ? "is-on" : ""}
                        title="Kéo / chỉnh đổi mọi câu (trừ câu đã chỉnh riêng)" onClick={() => onScope("all")}>Tất cả câu</button>
              </div>
              <p className="dx-insp__tip">
                {own ? <>Đang chỉnh riêng <b>câu {(i ?? 0) + 1}</b>{cue?.look ? " (đã khác kiểu chung)" : ""}. Các câu khác giữ nguyên.</>
                  : scope === "cue" ? "Chọn một câu để chỉnh riêng — chưa chọn thì đang chỉnh kiểu chung cho mọi câu."
                  : `Đang chỉnh kiểu chung cho mọi câu${customCount ? ` (trừ ${customCount} câu đã chỉnh riêng)` : ""}.`}
              </p>
              {own && cue?.look && i !== null && (
                <div className="dx-insp__applyall">
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={readOnly} onClick={() => onApplyAll(i)}
                          title="Lấy vị trí, cỡ chữ và độ rộng của câu này làm kiểu chung, bỏ mọi chỉnh riêng">⇪ Áp cho tất cả câu</button>
                  <button type="button" className="qt-btn qt-btn--small" disabled={readOnly} onClick={() => onClearLook(i)}>↺ Câu này theo kiểu chung</button>
                </div>
              )}
              <label className="qt-field"><span>Cỡ chữ <small>{Math.round(geo.scale * 100)}%</small></span>
                <input type="range" min={0.5} max={2.2} step={0.05} value={geo.scale} disabled={readOnly}
                       onChange={(e) => setPos({ scale: Number(e.target.value) }, "sub-scale")} /></label>
              <label className="qt-field">
                <span>Độ rộng phụ đề <small>{geo.w ? pct(geo.w) : "tự động"}</small></span>
                <div className="dx-insp__wrow">
                  <input type="range" min={W_MIN} max={W_MAX} step={0.01} value={geo.w ?? 0.88} disabled={readOnly}
                         onChange={(e) => setPos({ w: Number(e.target.value) }, "sub-width")} />
                  <label className="qt-check"><input type="checkbox" checked={!geo.w} disabled={readOnly}
                         onChange={(e) => setPos({ w: e.target.checked ? null : 0.88 }, "")} /> Tự động</label>
                </div>
              </label>
              <div className="dx-insp__row2">
                <label className="qt-field"><span>Ngang <small>{pct(geo.x)}</small></span>
                  <input type="range" min={0.05} max={0.95} step={0.005} value={geo.x} disabled={readOnly}
                         onChange={(e) => setPos({ x: Number(e.target.value) }, "sub-x")} /></label>
                <label className="qt-field"><span>Dọc <small>{pct(geo.y)}</small></span>
                  <input type="range" min={0.08} max={0.98} step={0.005} value={geo.y} disabled={readOnly}
                         onChange={(e) => setPos({ y: Number(e.target.value) }, "sub-y")} /></label>
              </div>
              <div className="qt-posts__chips">
                {POS_PRESETS.map((p) => (
                  <button key={p.label} type="button" className="qt-chip" disabled={readOnly} onClick={() => setPos({ x: 0.5, y: p.y }, "")}>{p.label}</button>
                ))}
                <button type="button" className="qt-chip" disabled={readOnly}
                        onClick={() => (own && i !== null ? onClearLook(i)
                          : setPos({ x: DEFAULT_LAYOUT.x, y: DEFAULT_LAYOUT.y, scale: DEFAULT_LAYOUT.scale, w: null }, ""))}>
                  {own ? "Theo kiểu chung" : "Về mặc định"}
                </button>
              </div>
              {customCount > 0 && (
                <div className="dx-insp__custom">
                  <span>✎ {customCount} câu đang có vị trí / cỡ riêng</span>
                  <button type="button" className="qt-btn qt-btn--small" disabled={readOnly} onClick={onClearAll}
                          title="Mọi câu theo kiểu chung — đồng bộ lại cả clip">Đồng bộ tất cả theo kiểu chung</button>
                </div>
              )}
              <p className="dx-insp__tip">Trên video: kéo phụ đề để dời, kéo hai mép cam để đổi độ rộng, mũi tên nhích 1 % (Shift = 5 %), +/− đổi cỡ chữ.</p>
            </section>

            <section className="dx-insp__sec">
              <h4>Kiểu phụ đề <small>áp cho mọi câu</small></h4>
              <select className="dx-insp__select" value={style} disabled={readOnly} onChange={(e) => onStyle(e.target.value)} aria-label="Kiểu phụ đề">
                {styles.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
            </section>
          </>
        )}

        {tab === "list" && (
          <CueList cues={cues} origin={origin} selected={i} active={activeCue} readOnly={readOnly}
                   onPick={onPickCue} onText={onCueText} />
        )}

        {tab === "hl" && <HighlightsPane hl={hl} layout={layout} status={status} readOnly={readOnly} selected={selected} onSelect={onSelect} />}

        {tab === "blur" && (
          <section className="dx-insp__sec">
            <p className="dx-insp__tip">Mỗi vùng mờ là một ô viền xanh trên video: kéo để dời, kéo góc dưới phải để đổi cỡ. Video gốc có chữ ở nhiều chỗ
              thì thêm nhiều vùng (tối đa {MAX_BLURS}). Vùng mờ áp cho cả clip.</p>
            {blurs.length > 0 ? (
              <ol className="dx-insp__blurs">
                {blurs.map((b, k) => (
                  <li key={k} className={k === bi && blur ? "is-on" : ""}>
                    <button type="button" className="dx-insp__blurpick" onClick={() => onSelect({ kind: "blur", i: k })}>
                      <strong>Vùng {k + 1}</strong>
                      <small>dọc {pct(b.y)}–{pct(Math.min(1, b.y + b.h))} · rộng {pct(b.w)} · mờ {b.amount}/10</small>
                    </button>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={readOnly} title={`Bỏ vùng ${k + 1}`}
                            onClick={() => removeBlur(k)}>🗑</button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="dx-insp__empty">Chưa có vùng mờ nào.</p>
            )}
            <div className="qt-post__actions">
              <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={readOnly || blurs.length >= MAX_BLURS} onClick={addBlur}>
                ＋ Thêm vùng mờ
              </button>
              {onDetect && (
                <button type="button" className="qt-btn qt-btn--small" disabled={detecting || readOnly || blurs.length >= MAX_BLURS} onClick={onDetect}
                        title="Đọc chữ trên video gốc (OCR) và đặt một vùng mờ cho mỗi dải chữ tìm thấy">
                  {detecting ? "Đang tìm chữ gốc…" : "🔍 Tự tìm chữ gốc (OCR)"}
                </button>
              )}
              {blurs.length > 1 && (
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={readOnly}
                        onClick={() => { onLayout(withBlurs(layout, [])); onSelect(null); }}>Bỏ hết</button>
              )}
            </div>
            {blur && (
              <>
                <h4 className="dx-insp__h">Vùng {bi + 1}</h4>
                <div className="dx-insp__row2">
                  <label className="qt-field"><span>Cao <small>{pct(blur.h)}</small></span>
                    <input type="range" min={0.02} max={0.4} step={0.005} value={blur.h} disabled={readOnly} onChange={(e) => setBlur({ h: Number(e.target.value) }, "blur-h")} /></label>
                  <label className="qt-field"><span>Rộng <small>{pct(blur.w)}</small></span>
                    <input type="range" min={0.05} max={1} step={0.01} value={blur.w} disabled={readOnly} onChange={(e) => setBlur({ w: Number(e.target.value) }, "blur-w")} /></label>
                  <label className="qt-field"><span>Vị trí dọc <small>{pct(blur.y)}</small></span>
                    <input type="range" min={0} max={0.97} step={0.005} value={blur.y} disabled={readOnly} onChange={(e) => setBlur({ y: Number(e.target.value) }, "blur-y")} /></label>
                  <label className="qt-field"><span>Vị trí ngang <small>{pct(blur.x)}</small></span>
                    <input type="range" min={0} max={0.95} step={0.005} value={blur.x} disabled={readOnly} onChange={(e) => setBlur({ x: Number(e.target.value) }, "blur-x")} /></label>
                  <label className="qt-field"><span>Độ mờ <small>{blur.amount}/10</small></span>
                    <input type="range" min={1} max={10} step={1} value={blur.amount} disabled={readOnly} onChange={(e) => setBlur({ amount: Number(e.target.value) }, "blur-a")} /></label>
                </div>
                <div className="qt-post__actions">
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={readOnly} onClick={() => setBlur({ x: 0.05, w: 0.9 }, "")}>Rộng gần hết khung</button>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={readOnly}
                          onClick={() => setBlur({ y: Math.max(0, layout.y - blur.h - 0.09) }, "")}>Đặt ngay trên phụ đề</button>
                  {blurs.length > 1 && (
                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={readOnly}
                            onClick={() => onLayout(withBlurs(layout, blurs.map((x) => ({ ...x, amount: blur.amount }))))}>Độ mờ này cho mọi vùng</button>
                  )}
                </div>
              </>
            )}
          </section>
        )}

        {tab === "decor" && (
          <fieldset className="dx-insp__decor" disabled={readOnly}>
            <DecorControls layout={layout} onChange={(l) => onLayout(l)} orientation={orientation} />
          </fieldset>
        )}

        {tab === "cut" && cutPane}

        {tab === "out" && (
          <section className="dx-insp__sec">
            <label className="qt-field"><span>Tên clip</span>
              <input value={out.name} disabled={readOnly} onChange={(e) => onOut({ name: e.target.value })} placeholder="VD: Mẹo giảm căng bụng cho mẹ bầu" /></label>
            <div className="qt-field"><span>Kiểu làm</span>
              <div className="dx-insp__mode" role="radiogroup" aria-label="Kiểu làm">
                <label className={`dx-insp__modeopt${out.mode === "dub" ? " is-on" : ""}`}>
                  <input type="radio" name="dx-mode" checked={out.mode === "dub"} disabled={readOnly} onChange={() => onOut({ mode: "dub" })} />
                  🎙 Lồng tiếng Việt
                </label>
                <label className={`dx-insp__modeopt${out.mode === "sub" ? " is-on" : ""}`}>
                  <input type="radio" name="dx-mode" checked={out.mode === "sub"} disabled={readOnly} onChange={() => onOut({ mode: "sub" })} />
                  💬 Chỉ phụ đề (giữ tiếng gốc)
                </label>
              </div>
            </div>
            {out.mode === "sub" && (
              <label className="qt-field">
                <span>Ngôn ngữ phụ đề{lang.busy ? " · đang dịch…" : ""}</span>
                <select value={lang.value} disabled={readOnly || lang.busy} onChange={(e) => lang.set(e.target.value as SubLang)}>
                  {SUB_LANGS.map((l) => (
                    <option key={l.key} value={l.key}>{l.key === "orig" ? `Ngôn ngữ gốc của video${lang.source ? ` (${lang.source})` : ""} — không dịch` : l.label}</option>
                  ))}
                </select>
              </label>
            )}
            {out.mode === "sub" && (
              <p className="dx-insp__tip">Đổi ngôn ngữ là viết lại chữ của mọi câu (Google Dịch, hoặc đúng lời gốc) — bấm Hoàn tác (Ctrl+Z) để lấy lại.</p>
            )}
            {out.mode === "dub" && !linesAreVietnamese(lang.value, lang.source) && (
              <div className="dx-insp__warn">
                Lồng tiếng đọc tiếng Việt — các câu đang là {subLangName(lang.value, lang.source)}.
                <button type="button" className="qt-btn qt-btn--small" disabled={readOnly || lang.busy} onClick={() => lang.set("vi")}>
                  {lang.busy ? "Đang dịch…" : "Dịch sang tiếng Việt"}
                </button>
              </div>
            )}
            {out.mode === "dub" && (
              <VoiceField value={out.voice} onChange={(v) => onOut({ voice: v })} disabled={readOnly}
                          sampleText={cues.find((c) => c.text.trim())?.text ?? "Xin chào các mẹ bầu."} />
            )}
            <label className="qt-field">
              <span>Công nghệ phụ đề</span>
              <select value={out.engine} disabled={readOnly} onChange={(e) => {
                const next = e.target.value as DubEngine;
                onOut({ engine: next });
                const opts = next === "remotion" ? status.remotion_styles ?? [] : status.styles;
                if (!opts.some((o) => o.key === style)) onStyle(opts[0]?.key ?? (next === "remotion" ? "rm_box" : "box_yellow"));
              }}>
                <option value="ass">ffmpeg · nhanh</option>
                <option value="remotion" disabled={!status.remotion}>Remotion · font Việt, emoji màu{status.remotion ? "" : " (chưa dùng được)"}</option>
              </select>
            </label>
            {out.mode === "dub" && (
              <label className="qt-check" title={status.separate ? "" : "Máy này chưa có mô hình tách giọng"}>
                <input type="checkbox" checked={out.keepBgm} disabled={!status.separate || readOnly} onChange={(e) => onOut({ keepBgm: e.target.checked })} /> Giữ nhạc nền gốc
              </label>
            )}
            <ChannelPicker value={out.channelId} onChange={(id) => onOut({ channelId: id })} label="Lưu vào kênh" disabled={readOnly} />
            <p className="dx-insp__tip">
              {out.mode === "sub"
                ? "Chỉ phụ đề: video giữ nguyên tiếng gốc, không đọc giọng — xuất nhanh dù sửa chữ hay dời câu."
                : "Đổi giọng, sửa chữ hoặc dời câu thì lúc xuất phải đọc lại giọng (lâu hơn); chỉ đổi vị trí / kiểu / khung / vùng mờ thì chỉ in lại hình (nhanh)."}{" "}
              Kiểu có sẵn của {out.engine === "remotion" ? "Remotion" : "ffmpeg"}: {engineStyles.map((s) => s.label).join(", ")}.
            </p>
          </section>
        )}
      </div>
    </aside>
  );
}

/** "✨ Nhấn": the key moments — on/off, what happens at each (key word, zoom, sound), where the word sits,
 * the list of points (AI-picked or typed), and the sound set. */
function HighlightsPane({ hl, layout, status, readOnly, selected, onSelect }: {
  hl: HighlightsCtl;
  layout: DubLayout;
  status: DubStatus;
  readOnly: boolean;
  selected: Sel;
  onSelect: (s: Sel) => void;
}) {
  const v = hl.value;
  const sel = selected?.kind === "hl" ? selected.i : null;
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (sel === null) return;
    (list.current?.children[sel] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
  }, [sel]);
  const sets = status.sfx_sets ?? [{ key: "builtin" as const, label: "Tiếng có sẵn", count: 4 }];
  const y = emphasisY(layout, v);
  return (
    <>
      <section className="dx-insp__sec">
        <label className="qt-check dx-insp__hlon">
          <input type="checkbox" checked={v.on} disabled={readOnly} onChange={(e) => hl.set({ on: e.target.checked })} />
          <span><strong>✨ Nhấn chữ quan trọng</strong><small>Giá, con số, lợi ích… — chữ to bật lên, hình zoom nhẹ, một tiếng hiệu ứng. Kiểu video TikTok giữ chân người xem.</small></span>
        </label>
        {v.on && (
          <>
            <div className="dx-insp__hlopts">
              <label className="qt-check"><input type="checkbox" checked={v.words} disabled={readOnly} onChange={(e) => hl.set({ words: e.target.checked })} /> Chữ to bật lên</label>
              <label className="qt-check"><input type="checkbox" checked={v.zoom} disabled={readOnly} onChange={(e) => hl.set({ zoom: e.target.checked })} /> Zoom nhẹ (1,12–1,18×)</label>
              <label className="qt-check"><input type="checkbox" checked={v.sfx} disabled={readOnly} onChange={(e) => hl.set({ sfx: e.target.checked })} /> Tiếng hiệu ứng</label>
            </div>
            {v.sfx && (
              <label className="qt-field"><span>Bộ tiếng</span>
                <select value={v.sfx_set} disabled={readOnly} onChange={(e) => hl.set({ sfx_set: e.target.value as DubHighlights["sfx_set"] })}>
                  {sets.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select></label>
            )}
            {v.words && (
              <label className="qt-field">
                <span>Vị trí chữ to <small>{Math.round(y * 100)}%{v.y === null ? " · trên phụ đề" : ""}</small></span>
                <div className="dx-insp__wrow">
                  <input type="range" min={HL_Y_MIN} max={HL_Y_MAX} step={0.005} value={y} disabled={readOnly}
                         onChange={(e) => hl.set({ y: Number(e.target.value) }, "hl-y")} />
                  <label className="qt-check"><input type="checkbox" checked={v.y === null} disabled={readOnly}
                         onChange={(e) => hl.set({ y: e.target.checked ? null : y })} /> Tự động</label>
                </div>
              </label>
            )}
          </>
        )}
      </section>
      {v.on && (
        <section className="dx-insp__sec">
          <div className="dx-insp__cuehead">
            <strong>Chỗ nhấn <small>{v.points.length ? `· ${v.points.length}` : ""}</small></strong>
            <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={readOnly || hl.picking} onClick={hl.pick}
                    title="AI đọc các câu, chọn khoảng 1 chỗ mỗi 12 giây">{hl.picking ? "AI đang chọn…" : v.points.length ? "✨ AI chọn lại" : "✨ AI chọn chữ quan trọng"}</button>
            <button type="button" className="qt-btn qt-btn--small" disabled={readOnly} onClick={hl.addAtNow} title="Thêm một chỗ nhấn tại giờ đang xem">+ Thêm ở {clock(hl.now)}</button>
          </div>
          {v.points.length === 0 ? (
            <p className="dx-insp__tip">Chưa có chỗ nào. Bấm “✨ AI chọn chữ quan trọng”, hoặc tua tới chỗ muốn nhấn rồi “+ Thêm”. Để trống mà xuất thì AI tự chọn lúc xuất.</p>
          ) : (
            <ol className="dx-list dx-hlist" ref={list}>
              {v.points.map((p, k) => {
                const live = hl.now >= p.at && hl.now < p.at + 1.2;
                return (
                  <li key={k} className={`${k === sel ? "is-selected" : ""}${live ? " is-active" : ""}`}>
                    <button type="button" className="dx-list__time" onClick={() => hl.onPickPoint(k)} title="Tua tới chỗ này"><b>✨</b>{clock(p.at)}</button>
                    <div className="dx-list__texts">
                      <input value={p.words} maxLength={40} disabled={readOnly} placeholder="chữ hiện to"
                             onFocus={() => onSelect({ kind: "hl", i: k })}
                             onChange={(e) => hl.setPoint(k, { words: e.target.value })} />
                    </div>
                    <button type="button" className="dx-hlist__del" disabled={readOnly} title="Bỏ chỗ nhấn này" onClick={() => hl.removePoint(k)}>🗑</button>
                  </li>
                );
              })}
            </ol>
          )}
          <p className="dx-insp__tip">
            Trên timeline hàng “✨ Nhấn”: kéo một khối để dời chỗ nhấn. {v.picked === "fallback" ? "Lần trước AI không chọn được nên tool lấy theo số / câu cảm thán." : ""}
          </p>
        </section>
      )}
    </>
  );
}

/** Every line, top to bottom: read the whole translation, fix any line in place. */
function CueList({ cues, origin, selected, active, readOnly, onPick, onText }: {
  cues: EditCue[];
  origin: { start: number; end: number; text: string }[];
  selected: number | null;
  active: number | null;
  readOnly: boolean;
  onPick: (i: number) => void;
  onText: (i: number, text: string) => void;
}) {
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const idx = selected ?? active;
    if (idx === null) return;
    const el = list.current?.children[idx] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [selected, active]);
  return (
    <ol className="dx-list" ref={list}>
      {cues.map((c, k) => {
        const edited = origin[k] && origin[k].text !== c.text;
        const fast = c.text.trim() && readingLoad(c) > 17;
        return (
          <li key={k} className={`${k === selected ? "is-selected" : ""}${k === active ? " is-active" : ""}${c.text.trim() ? "" : " is-empty"}`}>
            <button type="button" className="dx-list__time" onClick={() => onPick(k)} title="Chọn câu này và tua tới">
              <b>{k + 1}</b>{clock(c.start)}
            </button>
            <div className="dx-list__texts">
              {c.src && <small>{c.src}</small>}
              <textarea rows={1} value={c.text} disabled={readOnly} placeholder="(bỏ câu)"
                        onFocus={() => onPick(k)} onChange={(e) => onText(k, e.target.value)} />
              {(edited || fast || c.look) && <em>{[edited ? "đã sửa" : "", fast ? "dài so với thời gian" : "", c.look ? "✎ vị trí / cỡ riêng" : ""].filter(Boolean).join(" · ")}</em>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Load({ cue }: { cue: EditCue }) {
  const text = cue.text.trim();
  if (!text) return <small className="dx-insp__load">Câu này đang bị bỏ — không đọc, không hiện phụ đề.</small>;
  const load = readingLoad(cue);
  const cls = load > 20 ? "is-bad" : load > 17 ? "is-warn" : "";
  return (
    <small className={`dx-insp__load ${cls}`}>
      {text.length} ký tự · {(cue.end - cue.start).toFixed(1)} s · {load.toFixed(0)} ký tự/giây
      {load > 17 ? " — dài so với thời gian, giọng sẽ bị đọc nhanh: rút gọn câu hoặc kéo dài khối trên timeline" : ""}
    </small>
  );
}

function TimeField({ label, value, onChange, disabled }: { label: string; value: number; onChange: (v: number) => void; disabled: boolean }) {
  return (
    <label className="dx-insp__time">
      <span>{label}</span>
      <div>
        <button type="button" disabled={disabled} onClick={() => onChange(Math.max(0, value - 0.1))} title="−0,1 s">−</button>
        <input type="number" step={0.1} min={0} value={value.toFixed(2)} disabled={disabled}
               onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v)) onChange(v); }} />
        <button type="button" disabled={disabled} onClick={() => onChange(value + 0.1)} title="+0,1 s">+</button>
      </div>
      <small>{clock(value)}</small>
    </label>
  );
}
