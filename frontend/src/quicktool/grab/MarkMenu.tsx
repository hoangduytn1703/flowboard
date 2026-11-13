import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** The colour class of a video label: the ready-made ones each have theirs, the seller's own share one. */
export function markClass(tag: string, presets: string[]): string {
  const i = presets.findIndex((p) => p.toLowerCase() === tag.toLowerCase());
  return i >= 0 && i < 4 ? `gb-mark gb-mark--p${i}` : "gb-mark gb-mark--own";
}

interface Props {
  /** where the button that opened it is (the menu sits under it, or above when there is no room) */
  anchor: DOMRect;
  /** how many videos it labels, and the labels each of them has now */
  marks: string[][];
  /** the labels to offer: the ready-made ones, then every label already in use */
  known: string[];
  presets: string[];
  onApply: (add: string[], remove: string[]) => Promise<void> | void;
  onClose: () => void;
}

/**
 * "🏷 Nhãn" of one video or of every picked one: tick / untick a label for all of them (a label only some have shows
 * as "–" and the first click puts it on all), or type a new one. Labels are kept by the video, so a rescan, or the
 * channel removed and added again, finds them.
 */
export function MarkMenu({ anchor, marks, known, presets, onApply, onClose }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: anchor.left, top: anchor.bottom + 6 });
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const n = marks.length;
  const have = (tag: string) => marks.filter((m) => m.some((t) => t.toLowerCase() === tag.toLowerCase())).length;

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    const left = Math.max(8, Math.min(anchor.left, window.innerWidth - w - 8));
    const below = anchor.bottom + 6 + h <= window.innerHeight - 8;
    setPos({ left, top: below ? anchor.bottom + 6 : Math.max(8, anchor.top - h - 6) });
  }, [anchor]);

  useEffect(() => {
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const t = window.setTimeout(() => document.addEventListener("mousedown", away), 0);
    document.addEventListener("keydown", key);
    return () => { window.clearTimeout(t); document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [onClose]);

  async function apply(add: string[], remove: string[]) {
    if (busy) return;
    setBusy(true);
    try { await onApply(add, remove); } finally { setBusy(false); }
  }
  function toggle(tag: string) {
    void apply(have(tag) === n ? [] : [tag], have(tag) === n ? [tag] : []);
  }
  function addDraft() {
    const tags = draft.split(",").map((t) => t.trim().replace(/^#/, "")).filter(Boolean);
    if (!tags.length) return;
    setDraft("");
    void apply(tags, []);
  }

  return createPortal(
    <div ref={box} className="gb-markmenu" role="dialog" aria-label="Gắn nhãn video" style={{ left: pos.left, top: pos.top }}>
      <div className="gb-markmenu__head">🏷 Nhãn cho {n > 1 ? `${n} video` : "video này"}</div>
      <div className="gb-markmenu__list">
        {known.map((tag) => {
          const k = have(tag);
          const state = k === 0 ? "" : k === n ? "✓" : "–";
          return (
            <button key={tag} type="button" className={`gb-markmenu__row${k === n ? " is-on" : k ? " is-some" : ""}`} disabled={busy}
                    onClick={() => toggle(tag)} title={k === n ? "Bấm để gỡ nhãn này" : k ? `${k}/${n} video đang có — bấm để gắn cho cả ${n}` : "Bấm để gắn"}>
              <span className="gb-markmenu__box" aria-hidden="true">{state}</span>
              <span className={markClass(tag, presets)}>{tag}</span>
              {n > 1 && k > 0 && k < n && <small>{k}/{n}</small>}
            </button>
          );
        })}
      </div>
      <div className="gb-markmenu__new">
        <input value={draft} placeholder="Nhãn mới… (vd. kênh A, tuần 46)" maxLength={60} disabled={busy}
               onChange={(e) => setDraft(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addDraft(); } }} autoFocus />
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy || !draft.trim()} onClick={addDraft}>Gắn</button>
      </div>
      <p className="gb-markmenu__hint">Nhãn được nhớ theo video — quét lại, hay bỏ kênh rồi thêm lại, video vẫn giữ nhãn.</p>
    </div>,
    document.body,
  );
}
