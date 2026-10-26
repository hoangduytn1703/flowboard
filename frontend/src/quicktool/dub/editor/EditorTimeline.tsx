import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Timeline, type TimelineState } from "@xzdarcy/react-timeline-editor";
import type { TimelineAction, TimelineRow } from "@xzdarcy/timeline-engine";
import "@xzdarcy/react-timeline-editor/dist/react-timeline-editor.css";
import { clock, readingLoad, type EditCue } from "./cues";
import type { Sel } from "./EditorStage";

export interface TimelineHandle {
  /** move the playhead (and keep it in view while playing) */
  setTime(t: number): void;
}

const START_LEFT = 16;
const TIME_AREA = 42; // the library's ruler (32 px) + its 10 px gap above the rows
const NICE_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
const MIN_PX_PER_SEC = 0.4, MAX_PX_PER_SEC = 400;

type Track = { id: string; label: string; icon: string; height: number };

/**
 * The CapCut-style timeline under the preview: the video (thumbnails), every
 * dubbed line as a block you can drag to move or stretch at either end, the
 * voice waveform, and the whole-clip layers (blur, frame, sticker). Built on
 * @xzdarcy/react-timeline-editor; the clock belongs to the preview — this
 * only follows it and seeks it.
 */
export const EditorTimeline = forwardRef<TimelineHandle, {
  duration: number;
  cues: EditCue[];
  /** the original timings, to mark moved lines */
  origin: { start: number; end: number; text: string }[];
  selected: Sel;
  activeCue: number | null;
  readOnly: boolean;
  filmstrip: string | null;
  wave: string | null;
  hasBlur: boolean;
  hasFrame: boolean;
  hasMascot: boolean;
  onSeek: (t: number) => void;
  onSelect: (s: Sel) => void;
  onTiming: (i: number, start: number, end: number) => void;
  onEditCue: (i: number) => void;
}>(function EditorTimeline({
  duration, cues, origin, selected, activeCue, readOnly, filmstrip, wave, hasBlur, hasFrame, hasMascot,
  onSeek, onSelect, onTiming, onEditCue,
}, ref) {
  const tl = useRef<TimelineState>(null);
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [pxPerSec, setPxPerSec] = useState<number | null>(null); // null = fit the whole clip
  const scrollLeft = useRef(0);
  const following = useRef(true);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const dur = Math.max(1, duration);
  const fitPx = Math.max(MIN_PX_PER_SEC, (width - START_LEFT - 24) / dur);
  const pps = pxPerSec ?? fitPx;
  // a ruler mark every "nice" step at least ~70 px apart
  const scale = NICE_STEPS.find((s) => s * pps >= 70) ?? NICE_STEPS[NICE_STEPS.length - 1];
  const scaleWidth = scale * pps;
  const marks = Math.ceil(dur / scale) + 1;

  useImperativeHandle(ref, () => ({
    setTime(t: number) {
      const s = tl.current;
      if (!s) return;
      s.setTime(t);
      if (!following.current) return;
      const x = START_LEFT + t * pps;
      const view = width - 60;
      if (x < scrollLeft.current + 20 || x > scrollLeft.current + view) s.setScrollLeft(Math.max(0, x - 80));
    },
  }), [pps, width]);

  function zoom(f: number) {
    setPxPerSec(Math.min(MAX_PX_PER_SEC, Math.max(fitPx, pps * f)));
  }

  const tracks: Track[] = [
    { id: "video", label: "Video", icon: "🎞", height: 46 },
    { id: "sub", label: "Phụ đề", icon: "💬", height: 40 },
    ...(wave ? [{ id: "voice", label: "Giọng", icon: "🎙", height: 34 }] : []),
    ...(hasBlur ? [{ id: "blur", label: "Làm mờ", icon: "🌫", height: 26 }] : []),
    ...(hasFrame ? [{ id: "frame", label: "Khung", icon: "🖼", height: 26 }] : []),
    ...(hasMascot ? [{ id: "mascot", label: "Nhân vật", icon: "💃", height: 26 }] : []),
  ];

  const data: TimelineRow[] = useMemo(() => {
    const whole = (id: string, effectId: string): TimelineAction => ({ id, start: 0, end: dur, effectId, movable: false, flexible: false });
    return tracks.map((tr) => {
      if (tr.id === "sub") {
        return {
          id: "sub", rowHeight: tr.height,
          actions: cues.map((c, i) => ({
            id: `c${i}`, start: c.start, end: c.end, effectId: "cue",
            movable: !readOnly, flexible: !readOnly,
            minStart: i > 0 ? cues[i - 1].end : 0,
            maxEnd: i < cues.length - 1 ? cues[i + 1].start : dur,
            selected: selected?.kind === "cue" && selected.i === i,
          })),
        };
      }
      const effect = tr.id === "video" ? "film" : tr.id === "voice" ? "wave" : tr.id;
      return { id: tr.id, rowHeight: tr.height, actions: [whole(tr.id, effect)] };
    });
  }, [cues, dur, readOnly, selected, wave, hasBlur, hasFrame, hasMascot]); // eslint-disable-line react-hooks/exhaustive-deps

  const effects = useMemo(() => Object.fromEntries(["cue", "film", "wave", "blur", "frame", "mascot"].map((id) => [id, { id, name: id }])), []);
  const cueIndex = (a: TimelineAction) => Number(a.id.slice(1));

  function renderAction(a: TimelineAction) {
    if (a.effectId === "cue") {
      const i = cueIndex(a);
      const c = cues[i];
      if (!c) return null;
      const o = origin[i];
      const moved = !!o && (Math.abs(o.start - c.start) > 0.005 || Math.abs(o.end - c.end) > 0.005);
      const edited = !!o && o.text !== c.text;
      const fast = c.text.trim() && readingLoad(c) > 17;
      const cls = ["dx-tl__cue",
        !c.text.trim() ? "is-empty" : "",
        selected?.kind === "cue" && selected.i === i ? "is-selected" : "",
        activeCue === i ? "is-active" : "",
        fast ? "is-fast" : "",
        c.look ? "is-custom" : ""].filter(Boolean).join(" ");
      return (
        <div className={cls} title={`Câu ${i + 1} · ${clock(c.start)}–${clock(c.end)}\n${c.text || "(bỏ câu này)"}${fast ? "\n⚠ Câu dài so với thời gian — giọng sẽ đọc nhanh" : ""}`}
             onDoubleClick={() => onEditCue(i)}>
          <span className="dx-tl__num">{c.look ? "✎" : ""}{i + 1}</span>
          <span className="dx-tl__txt">{c.text.trim() || "— bỏ —"}</span>
          {(moved || edited) && <span className="dx-tl__dot" title={edited ? "đã sửa chữ" : "đã dời thời gian"} />}
        </div>
      );
    }
    if (a.effectId === "film") {
      return <div className="dx-tl__film" style={filmstrip ? { backgroundImage: `url(${filmstrip})` } : undefined} />;
    }
    if (a.effectId === "wave") {
      return <div className="dx-tl__wave">{wave && <img src={wave} alt="" draggable={false} />}</div>;
    }
    const sel = selected?.kind === a.effectId;
    const label = a.effectId === "blur" ? "🌫 Vùng làm mờ chữ gốc · cả clip" : a.effectId === "frame" ? "🖼 Khung video · cả clip" : "💃 Nhân vật · cả clip";
    return <div className={`dx-tl__layer dx-tl__layer--${a.effectId}${sel ? " is-selected" : ""}`}>{label}</div>;
  }

  const height = TIME_AREA + tracks.reduce((n, t) => n + t.height, 0) + 14;

  return (
    <div className="dx-tl">
      <div className="dx-tl__bar">
        <span className="dx-tl__hint">Kéo khối phụ đề để dời · kéo mép để kéo dài / rút ngắn · bấm đúp để sửa chữ</span>
        <div className="dx-tl__zoom">
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => zoom(1 / 1.6)} title="Thu nhỏ">−</button>
          <input type="range" min={0} max={100} step={1} aria-label="Phóng to timeline"
                 value={Math.round(100 * Math.log(pps / fitPx) / Math.log(Math.max(1.0001, MAX_PX_PER_SEC / fitPx)))}
                 onChange={(e) => {
                   const k = Number(e.target.value) / 100;
                   setPxPerSec(k <= 0 ? null : fitPx * Math.pow(MAX_PX_PER_SEC / fitPx, k));
                 }} />
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => zoom(1.6)} title="Phóng to">+</button>
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setPxPerSec(null)} title="Vừa cả clip">⤢ Vừa khung</button>
        </div>
      </div>
      <div className="dx-tl__body">
        <div className="dx-tl__heads" style={{ paddingTop: TIME_AREA }}>
          {tracks.map((t) => (
            <button key={t.id} type="button" className="dx-tl__head" style={{ height: t.height }}
                    onClick={() => onSelect(t.id === "sub" ? { kind: "style" } : t.id === "blur" ? { kind: "blur" } : t.id === "frame" ? { kind: "frame" } : t.id === "mascot" ? { kind: "mascot" } : null)}>
              <span>{t.icon}</span>{t.label}
            </button>
          ))}
        </div>
        <div className="dx-tl__host" ref={host}
             onPointerDown={() => { following.current = true; }}
             onWheel={() => { following.current = false; }}>
          <Timeline
            ref={tl}
            editorData={data}
            effects={effects}
            scale={scale}
            scaleWidth={scaleWidth}
            scaleSplitCount={scale >= 60 ? 6 : scale >= 5 ? 5 : 10}
            startLeft={START_LEFT}
            minScaleCount={marks}
            maxScaleCount={marks}
            rowHeight={32}
            autoScroll
            dragLine
            style={{ width: "100%", height }}
            getScaleRender={(s) => <span>{clock(s, false)}</span>}
            getActionRender={(a) => renderAction(a)}
            onScroll={(p) => { scrollLeft.current = p.scrollLeft; }}
            onChange={() => false}
            onActionMoveEnd={({ action, start, end }) => { if (action.effectId === "cue") onTiming(cueIndex(action), start, end); }}
            onActionResizeEnd={({ action, start, end }) => { if (action.effectId === "cue") onTiming(cueIndex(action), start, end); }}
            onClickActionOnly={(_, { action, time }) => {
              if (action.effectId === "cue") {
                const i = cueIndex(action);
                onSelect({ kind: "cue", i });
                const c = cues[i];
                if (c && (time < c.start || time >= c.end)) onSeek(c.start);
                else onSeek(time);
              } else {
                onSelect(action.effectId === "blur" ? { kind: "blur" } : action.effectId === "frame" ? { kind: "frame" } : action.effectId === "mascot" ? { kind: "mascot" } : null);
                onSeek(time);
              }
            }}
            onClickRow={(_, { time }) => onSeek(time)}
            onClickTimeArea={(time) => { onSeek(time); return true; }}
            onCursorDrag={(time) => onSeek(time)}
            onCursorDragEnd={(time) => onSeek(time)}
          />
        </div>
      </div>
    </div>
  );
});
