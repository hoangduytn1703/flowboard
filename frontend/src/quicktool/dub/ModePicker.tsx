import type { DubMode } from "../../api/dub";
import "./modepicker.css";

/** line icons (currentColor): a microphone, a subtitle bar */
const ICONS: Record<DubMode, JSX.Element> = {
  dub: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0" />
      <path d="M12 17.5V21" />
    </svg>
  ),
  sub: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="3" />
      <path d="M7 12.5h4M13.5 12.5H17M7 15.5h7" />
    </svg>
  ),
};

const MODES: { key: DubMode; title: string; hint: string }[] = [
  { key: "dub", title: "Lồng tiếng Việt", hint: "Giọng Việt đọc thay tiếng gốc, kèm phụ đề" },
  { key: "sub", title: "Chỉ chèn phụ đề", hint: "Giữ tiếng gốc, chỉ thêm phụ đề — nhanh hơn" },
];

/** "Làm gì với video": voice-over or subtitles only, as two cards (the dub page and "🎙 Lồng tiếng ngay"). */
export function ModePicker({ value, onChange, disabled = false, name }: {
  value: DubMode; onChange: (m: DubMode) => void; disabled?: boolean; name: string;
}) {
  return (
    <div className="qt-modes">
      <div className="qt-modes__grid" role="radiogroup" aria-label="Làm gì với video">
        {MODES.map((m) => {
          const on = value === m.key;
          return (
            <label key={m.key} className={`qt-mode${on ? " is-on" : ""}${disabled ? " is-off" : ""}`}>
              <input type="radio" name={name} checked={on} disabled={disabled} onChange={() => onChange(m.key)} />
              <span className="qt-mode__top">
                <span className="qt-mode__icon">{ICONS[m.key]}</span>
                <span className="qt-mode__dot" aria-hidden="true">{on ? "✓" : ""}</span>
              </span>
              <strong>{m.title}</strong>
              <small>{m.hint}</small>
            </label>
          );
        })}
      </div>
    </div>
  );
}
