import { useRef } from "react";

/**
 * A range slider with visible notches: a small tick every ``every`` and a taller one at each ``marks``
 * value (default: both ends and the middle). While dragging with the mouse / finger the thumb snaps to a mark that
 * is close, so "exactly 50 %" or "exactly 100 %" is easy to hit; keyboard arrows keep moving by ``step``.
 */
export function TickRange({ min, max, step, value, onChange, every, marks, disabled, title, ariaLabel }: {
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
  /** distance between small ticks (default: a tenth of the range) */
  every?: number;
  /** values that get a tall tick and pull the thumb in while dragging */
  marks?: number[];
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
}) {
  const dragging = useRef(false);
  const span = max - min || 1;
  const majors = marks ?? [min, (min + max) / 2, max];
  const snapTol = span * 0.02;
  // small ticks at round multiples of ``every`` (so 0.05–0.95 still gets a tick at 10 %, 20 %, …)
  const gap = every ?? span / 10;
  const tickValues: number[] = [];
  for (let k = Math.ceil(min / gap - 1e-9); k * gap <= max + gap * 1e-9; k++) tickValues.push(k * gap);
  const frac = (v: number) => Math.min(1, Math.max(0, (v - min) / span));
  const left = (f: number) => `calc(8px + (100% - 16px) * ${f})`;

  function change(raw: number) {
    let v = raw;
    if (dragging.current) {
      const near = majors.find((m) => Math.abs(m - raw) <= snapTol);
      if (near !== undefined) v = near;
    }
    onChange(v);
  }

  return (
    <span className={`tick-range${disabled ? " is-disabled" : ""}`} title={title}>
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled} aria-label={ariaLabel}
             onPointerDown={() => { dragging.current = true; }}
             onPointerUp={() => { dragging.current = false; }}
             onPointerCancel={() => { dragging.current = false; }}
             onBlur={() => { dragging.current = false; }}
             onKeyDown={() => { dragging.current = false; }}
             onChange={(e) => change(Number(e.target.value))} />
      <span className="tick-range__ticks" aria-hidden="true">
        {tickValues
          .filter((v) => !majors.some((m) => Math.abs(m - v) < span * 1e-6))
          .map((v) => <i key={`t${v}`} style={{ left: left(frac(v)) }} />)}
        {majors.map((m) => (
          <i key={`m${m}`} className={`is-mark${Math.abs(m - value) < step / 2 ? " is-on" : ""}`}
             style={{ left: left(frac(m)) }} />
        ))}
      </span>
    </span>
  );
}
