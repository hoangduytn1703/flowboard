import { useEffect, useRef, useState } from "react";

/** Seconds → the two boxes' texts: minutes, and seconds padded ("05"; one decimal only when there is one). */
function split(v: number): [string, string] {
  const t = Math.max(0, Math.round(v * 10) / 10);
  const m = Math.floor(t / 60);
  const s = Math.round((t - m * 60) * 10) / 10;
  return [String(m), Number.isInteger(s) ? String(s).padStart(2, "0") : s.toFixed(1).padStart(4, "0")];
}

/** "m:ss" for labels and hints. */
export function clockText(v: number): string {
  const [m, s] = split(v);
  return `${m}:${s}`;
}

/**
 * A time as two boxes — minutes and seconds — so nothing but digits is typed (no ":"). Tab, ":", "." or a space in the
 * minutes box jumps to the seconds; seconds of 60 or more carry into the minutes when the box is left. ``null`` = not
 * filled in: the boxes then show ``hint`` (the time the tool will use, e.g. the end of the video) in grey.
 */
export function MinSec({ value, onChange, disabled, bad, label, hint, hintTitle, inputRef }: {
  value: number | null;
  onChange: (v: number | null) => void;
  disabled?: boolean;
  bad?: boolean;
  /** what this time is ("Đoạn 2 — bắt đầu"), for screen readers and the tooltip */
  label: string;
  /** shown in grey while empty: the time that will be used */
  hint?: number | null;
  hintTitle?: string;
  inputRef?: (el: HTMLInputElement | null) => void;
}) {
  const [m, setM] = useState(() => (value === null ? "" : split(value)[0]));
  const [s, setS] = useState(() => (value === null ? "" : split(value)[1]));
  const focused = useRef(false);
  const latest = useRef(value);
  latest.current = value;
  const secBox = useRef<HTMLInputElement>(null);

  const show = (v: number | null) => {
    const [mm, ss] = v === null ? ["", ""] : split(v);
    setM(mm);
    setS(ss);
  };
  // a value set from outside (the AI's rows, ⏱, a new row) is shown; what is being typed is left alone
  useEffect(() => { if (!focused.current) show(value); }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  // the seconds box was just emptied (as opposed to "0" typed into the minutes of an empty time)
  const wiped = useRef(false);
  function typed(mm: string, ss: string) {
    wiped.current = !ss.trim() && !!s.trim();
    setM(mm);
    setS(ss);
    // nothing typed — or the seconds wiped with only a "0" left in the minutes — is "not filled in"
    if (!ss.trim() && !(parseInt(mm, 10) > 0) && (!mm.trim() || wiped.current)) { onChange(null); return; }
    const v = (parseInt(mm, 10) || 0) * 60 + (parseFloat(ss.replace(",", ".")) || 0);
    onChange(Math.round(v * 10) / 10);
  }
  const [hm, hs] = value === null && hint !== null && hint !== undefined ? split(hint) : ["", ""];

  return (
    <span className={`ct-ms${bad ? " is-bad" : ""}${disabled ? " is-disabled" : ""}`}
          title={value === null && hintTitle ? hintTitle : `${label} — ô trái là phút, ô phải là giây`}
          onFocus={() => { focused.current = true; }}
          onBlur={(e) => {
            if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
            focused.current = false;
            show(latest.current); // "90" seconds → 1 : 30
          }}>
      <input ref={inputRef} className="ct-ms__box" inputMode="numeric" value={m} disabled={disabled} maxLength={3}
             placeholder={hm || "phút"} aria-label={`${label} — phút`}
             onChange={(e) => typed(e.target.value.replace(/\D/g, ""), s)}
             onKeyDown={(e) => {
               if ([":", ".", ",", " "].includes(e.key)) { e.preventDefault(); secBox.current?.focus(); secBox.current?.select(); }
             }} />
      <i aria-hidden="true">:</i>
      <input ref={secBox} className="ct-ms__box" inputMode="decimal" value={s} disabled={disabled} maxLength={4}
             placeholder={hs || "giây"} aria-label={`${label} — giây`}
             onChange={(e) => typed(m, e.target.value.replace(/[^\d.,]/g, ""))} />
    </span>
  );
}
