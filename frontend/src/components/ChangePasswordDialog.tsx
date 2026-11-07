import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { changeAccountPassword } from "../api/account";
import { toast } from "../store/toast";

const MIN_PASSWORD = 6;

/** "Đổi mật khẩu" for the account logged in (every account has it; only the admin manages other accounts).
 * Portalled to <body>: opened from the sidebar, whose stacking context would put the page above it. */
export function ChangePasswordDialog({ username, onClose }: { username: string; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const problem = !current ? "Nhập mật khẩu hiện tại."
    : next.length < MIN_PASSWORD ? `Mật khẩu mới cần ít nhất ${MIN_PASSWORD} ký tự.`
    : next === current ? "Mật khẩu mới phải khác mật khẩu hiện tại."
    : next !== again ? "Hai ô mật khẩu mới chưa giống nhau."
    : "";

  async function submit() {
    if (problem || busy) { setError(problem); return; }
    setBusy(true);
    setError("");
    try {
      const r = await changeAccountPassword(current, next);
      toast.success(r.logged_out
        ? `Đã đổi mật khẩu. ${r.logged_out} máy / trình duyệt khác đang đăng nhập tài khoản này đã bị đăng xuất.`
        : "Đã đổi mật khẩu.");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  const type = show ? "text" : "password";
  return createPortal(
    <div className="project-modal-backdrop pw-backdrop" role="presentation"
         onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <form className="project-modal pw-dialog" role="dialog" aria-modal="true" aria-label="Đổi mật khẩu"
            onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <h3 className="pw-dialog__title">🔑 Đổi mật khẩu — {username}</h3>
        <label className="pw-dialog__field">
          <span>Mật khẩu hiện tại</span>
          <input ref={first} className="project-modal__input" type={type} autoComplete="current-password"
                 value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label className="pw-dialog__field">
          <span>Mật khẩu mới (ít nhất {MIN_PASSWORD} ký tự)</span>
          <input className="project-modal__input" type={type} autoComplete="new-password"
                 value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
        <label className="pw-dialog__field">
          <span>Nhập lại mật khẩu mới</span>
          <input className="project-modal__input" type={type} autoComplete="new-password"
                 value={again} onChange={(e) => setAgain(e.target.value)} />
        </label>
        <label className="pw-dialog__show">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} /> Hiện mật khẩu
        </label>
        <p className="pw-dialog__hint">Đổi xong, các máy / trình duyệt khác đang đăng nhập tài khoản này sẽ bị đăng xuất. Máy này vẫn giữ đăng nhập.</p>
        {error && <div className="login__error">{error}</div>}
        <div className="project-modal__actions">
          <button type="button" className="project-modal__btn" disabled={busy} onClick={onClose}>Huỷ</button>
          <button type="submit" className="project-modal__btn project-modal__btn--primary" disabled={busy}>
            {busy ? "Đang đổi…" : "Đổi mật khẩu"}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
