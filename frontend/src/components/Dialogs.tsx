import { useEffect, useRef, useState } from "react";
import { create } from "zustand";

/**
 * The app's own confirm / prompt boxes, instead of window.confirm / window.prompt.
 *
 * The desktop app (Tauri, WebView2) never showed the browser's native boxes: window.confirm returned false at
 * once, so every action behind one silently did nothing — "🚀 Đăng ngay" never posted (7/11). These work the
 * same in the browser and in the app, and look like the rest of DFlow. Usage:
 *
 *   if (!(await askConfirm("Đăng bài này lên Page ngay?"))) return;
 *   const name = await askText("Tên mẫu", "Mẫu 1");   // null = cancelled
 */
interface Pending {
  id: number;
  kind: "confirm" | "text";
  message: string;
  ok: string;
  cancel: string;
  danger: boolean;
  value: string;
  placeholder: string;
  resolve: (value: boolean | string | null) => void;
}

interface ConfirmOptions {
  /** the OK button's label (default "Đồng ý") */
  ok?: string;
  cancel?: string;
  /** a red OK button, for deletions */
  danger?: boolean;
}

interface TextOptions extends ConfirmOptions {
  placeholder?: string;
}

const useDialogs = create<{ queue: Pending[] }>(() => ({ queue: [] }));
let nextId = 1;

function open(item: Omit<Pending, "id" | "resolve">): Promise<boolean | string | null> {
  return new Promise((resolve) => {
    useDialogs.setState((s) => ({ queue: [...s.queue, { ...item, id: nextId++, resolve }] }));
  });
}

export function askConfirm(message: string, opts: ConfirmOptions = {}): Promise<boolean> {
  return open({
    kind: "confirm", message, ok: opts.ok ?? "Đồng ý", cancel: opts.cancel ?? "Huỷ", danger: !!opts.danger, value: "", placeholder: "",
  }).then((v) => v === true);
}

export function askText(message: string, value = "", opts: TextOptions = {}): Promise<string | null> {
  return open({
    kind: "text", message, ok: opts.ok ?? "Lưu", cancel: opts.cancel ?? "Huỷ", danger: !!opts.danger, value,
    placeholder: opts.placeholder ?? "",
  }).then((v) => (typeof v === "string" ? v : null));
}

function close(item: Pending, value: boolean | string | null) {
  useDialogs.setState((s) => ({ queue: s.queue.filter((q) => q.id !== item.id) }));
  item.resolve(value);
}

/** Mounted once at the root (App.tsx): shows the first pending box; Enter = OK, Esc = cancel. */
export function DialogHost() {
  const item = useDialogs((s) => s.queue[0]);
  const [text, setText] = useState("");
  const okRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!item) return;
    setText(item.value);
    const t = window.setTimeout(() => (item.kind === "text" ? inputRef.current?.select() : okRef.current?.focus()), 0);
    return () => window.clearTimeout(t);
  }, [item]);

  useEffect(() => {
    if (!item) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(item, item.kind === "text" ? null : false);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [item]);

  if (!item) return null;
  const submit = () => close(item, item.kind === "text" ? text : true);
  return (
    <div className="project-modal-backdrop dlg-backdrop" role="presentation"
         onMouseDown={(e) => { if (e.target === e.currentTarget) close(item, item.kind === "text" ? null : false); }}>
      <form className="project-modal dlg" role="alertdialog" aria-modal="true" aria-label="Xác nhận"
            onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <p className="dlg__message">{item.message}</p>
        {item.kind === "text" && (
          <input ref={inputRef} className="project-modal__input" type="text" value={text} placeholder={item.placeholder}
                 maxLength={200} onChange={(e) => setText(e.target.value)} />
        )}
        <div className="project-modal__actions">
          <button type="button" className="project-modal__btn" onClick={() => close(item, item.kind === "text" ? null : false)}>
            {item.cancel}
          </button>
          <button ref={okRef} type="submit"
                  className={`project-modal__btn ${item.danger ? "project-modal__btn--danger" : "project-modal__btn--primary"}`}>
            {item.ok}
          </button>
        </div>
      </form>
    </div>
  );
}
