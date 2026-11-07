import { useEffect, useState, type FormEvent } from "react";
import { connectCloud, getConnectStatus, loginWithMessage, type AccountMe, type ConnectStatus } from "../api/account";

const RESTART_WAIT_MS = 120_000;

/**
 * A fresh install only knows its own empty account store: the accounts the admin made live on the cloud database,
 * so the cloud line (sent with the account) is pasted here first — before logging in. The agent tests it, saves it
 * and (desktop app) restarts itself; this box then disappears.
 */
function CloudConnect({ status, onConnected }: { status: ConnectStatus; onConnected: () => void }) {
  const [open, setOpen] = useState(false);
  const [line, setLine] = useState("");
  const [state, setState] = useState<"idle" | "testing" | "restarting" | "manual">(
    status.restart_pending && !status.app ? "manual" : "idle",
  );
  const [error, setError] = useState<string | null>(null);

  async function waitForRestart() {
    const end = Date.now() + RESTART_WAIT_MS;
    await new Promise((r) => setTimeout(r, 2500)); // the agent exits ~0.6 s after answering
    while (Date.now() < end) {
      try {
        const s = await getConnectStatus();
        if (s.cloud) { onConnected(); return; }
      } catch { /* restarting */ }
      await new Promise((r) => setTimeout(r, 1500));
    }
    setState("idle");
    setError("DFlow chưa khởi động lại xong. Thoát DFlow (chuột phải biểu tượng ở khay → Thoát) rồi mở lại.");
  }

  async function submit() {
    if (!line.trim() || state === "testing") return;
    setState("testing");
    setError(null);
    try {
      const r = await connectCloud(line.trim());
      if (r.restarting) {
        setState("restarting");
        await waitForRestart();
      } else {
        setState("manual");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setState("idle");
    }
  }

  if (state === "manual") {
    return (
      <div className="login__cloud login__cloud--done">
        ✓ Đã lưu dòng kết nối. Tắt DFlow (cửa sổ start.ps1) rồi chạy lại, sau đó đăng nhập bằng tài khoản được cấp.
      </div>
    );
  }
  if (state === "restarting") {
    return <div className="login__cloud login__cloud--done"><span className="qt-spinner" /> Đã nối dữ liệu cloud — DFlow đang khởi động lại (khoảng 20–40 giây)…</div>;
  }
  if (!open) {
    return (
      <div className="login__cloud">
        <span>Mới cài DFlow trên máy này, được cấp tài khoản kèm <b>dòng kết nối dữ liệu</b>?</span>
        <button type="button" className="qt-btn qt-btn--small" onClick={() => setOpen(true)}>🌐 Dán dòng kết nối trước</button>
      </div>
    );
  }
  return (
    <div className="login__cloud login__cloud--open">
      <span>Dán nguyên dòng được gửi (bắt đầu bằng <code>postgresql://</code> hoặc <code>FLOWBOARD_CENTRAL_DB_URL=</code>):</span>
      <textarea rows={3} spellCheck={false} autoComplete="off" value={line} onChange={(e) => setLine(e.target.value)}
                placeholder="postgresql://…" />
      {error && <div className="login__error" role="alert">{error}</div>}
      <div className="login__cloud-btns">
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!line.trim() || state === "testing"} onClick={() => void submit()}>
          {state === "testing" ? "Đang kiểm tra kết nối…" : "Kết nối"}
        </button>
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={state === "testing"} onClick={() => setOpen(false)}>Huỷ</button>
      </div>
      <small>Dòng này chỉ cần dán một lần trên mỗi máy. Đừng gửi nó cho người khác.</small>
    </div>
  );
}

/** Full-screen login. Shown by the auth gate until a session cookie exists. */
export function LoginPage({ onLoggedIn }: { onLoggedIn: (me: AccountMe) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloud, setCloud] = useState<ConnectStatus | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    getConnectStatus().then(setCloud).catch(() => setCloud(null)); // older agents: no box
  }, []);

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
        {connected && <div className="login__cloud login__cloud--done">✓ Đã nối dữ liệu cloud. Giờ đăng nhập bằng tài khoản được cấp.</div>}
        {cloud && !cloud.cloud && !connected && (
          <CloudConnect status={cloud} onConnected={() => { setConnected(true); setCloud({ ...cloud, cloud: true }); }} />
        )}
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
