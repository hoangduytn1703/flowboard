import { useEffect, useRef, useState } from "react";
import { labelOf, type SuggestionGroup } from "./suggestions";

/**
 * A text field that also offers ready-made choices: type freely, or open
 * the list ("▾ Chọn") and pick one. Picking fills the field with the
 * option's value.
 */
export function SuggestField({
  value,
  onChange,
  placeholder,
  groups,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  groups: SuggestionGroup[];
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const q = filter.trim().toLowerCase();
  const match = (s: string) => !q || s.toLowerCase().includes(q);
  const shownGroups = groups
    .map((g) => ({ ...g, items: g.items.filter((i) => match(i.label) || match(i.value)) }))
    .filter((g) => g.items.length);
  const picked = value ? labelOf(value) : null;

  return (
    <div className="qt-suggest" ref={wrapRef}
         onKeyDown={(e) => { if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); } }}>
      <div className="qt-suggest__row">
        <input className="project-modal__input" type="text" maxLength={200} value={value} placeholder={placeholder}
               onChange={(e) => onChange(e.target.value)} disabled={disabled} />
        <button type="button" className="qt-btn qt-btn--ghost qt-suggest__toggle" disabled={disabled}
                aria-expanded={open} onClick={() => { setOpen((o) => !o); setFilter(""); }}>
          ▾ Chọn
        </button>
      </div>
      {picked && <div className="qt-suggest__picked">Đang chọn: {picked}</div>}
      {open && (
        <div className="qt-suggest__pop" role="listbox">
          <input className="qt-suggest__filter" type="search" placeholder="lọc…" value={filter} autoFocus
                 onChange={(e) => setFilter(e.target.value)} />
          {shownGroups.map((g) => (
            <div key={g.title} className="qt-suggest__group">
              <div className="qt-suggest__title">{g.title}</div>
              {g.items.map((i) => (
                <button key={i.value} type="button" className={`qt-suggest__opt${i.value === value ? " qt-suggest__opt--on" : ""}`}
                        role="option" aria-selected={i.value === value}
                        onClick={() => { onChange(i.value); setOpen(false); }}>
                  <span>{i.label}</span>
                  <small>{i.value}</small>
                </button>
              ))}
            </div>
          ))}
          {!shownGroups.length && <div className="qt-suggest__empty">Không có gợi ý khớp.</div>}
        </div>
      )}
    </div>
  );
}
