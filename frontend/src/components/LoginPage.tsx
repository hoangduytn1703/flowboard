import { useState, type FormEvent } from "react";
import { loginWithMessage, type AccountMe } from "../api/account";

/** Full-screen login. Shown by the auth gate until a session cookie exists. */
export function LoginPage({ onLoggedIn }: { onLoggedIn: (me: AccountMe) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const me = await loginWithMessage(username.trim(), password);
      onLoggedIn(me);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={submit}>
        <div className="login__brand">
          <img className="qt-brand__logo" src="/dflow-logo.png" alt="" />
          <span className="dflow-wordmark" aria-label="DFlow"><span className="dflow-wordmark__d">D</span>FLOW</span>
        </div>
        <h1 className="login__title">Đăng nhập</h1>
        <p className="login__hint">Clip, sản phẩm, người mẫu và prompt của bạn đi theo tài khoản này.</p>
        <label className="login__field">
          <span>Tên đăng nhập</span>
          <input type="text" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="login__field">
          <span>Mật khẩu</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="login__error" role="alert">{error}</div>}
        <button type="submit" className="qt-btn qt-btn--accent qt-btn--big" disabled={busy || !username.trim() || !password}>
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
      </form>
    </div>
  );
}
