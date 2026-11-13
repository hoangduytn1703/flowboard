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

/** "Ghi nhớ đăng nhập": the choice and, when ticked, the user name (never the password) — this browser / app only. */
const REMEMBER_KEY = "dflow.login.remember";
const USER_KEY = "dflow.login.user";
function readKey(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function writeKey(key: string, value: string | null) {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* private mode */ }
}

/** Full-screen login. Shown by the auth gate until a session cookie exists. */
export function LoginPage({ onLoggedIn }: { onLoggedIn: (me: AccountMe) => void }) {
  const [remember, setRemember] = useState(() => readKey(REMEMBER_KEY) !== "0");
  const [username, setUsername] = useState(() => (readKey(REMEMBER_KEY) !== "0" ? readKey(USER_KEY) ?? "" : ""));
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
      const me = await loginWithMessage(username.trim(), password, remember);
      writeKey(REMEMBER_KEY, remember ? "1" : "0");
      writeKey(USER_KEY, remember ? username.trim() : null);
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
        {cloud?.site && (
          <p className="login__site">
            Đăng nhập bằng tài khoản DFlow (tài khoản trên <b>{cloud.site.host}</b>).
          </p>
        )}
        <label className="login__field">
          <span>Tên đăng nhập</span>
          <input type="text" autoComplete="username" autoFocus={!username} value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="login__field">
          <span>Mật khẩu</span>
          <input type="password" autoComplete="current-password" autoFocus={!!username} value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="login__remember" title="Tick: giữ đăng nhập trên máy này 90 ngày (tự gia hạn mỗi lần mở) và nhớ tên đăng nhập. Không tick: đóng app / trình duyệt là phải đăng nhập lại — nên dùng khi ở máy chung.">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>
            Ghi nhớ đăng nhập
            <small>{remember ? "Giữ đăng nhập 90 ngày trên máy này — mở app là vào luôn." : "Đóng app / trình duyệt là phải đăng nhập lại (máy dùng chung)."}</small>
          </span>
        </label>
        {error && <div className="login__error" role="alert">{error}</div>}
        <button type="submit" className="qt-btn qt-btn--accent qt-btn--big" disabled={busy || !username.trim() || !password}>
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
        {cloud?.site && (
          <div className="login__links">
            <span>Chưa có tài khoản? <a href={cloud.site.signup} target="_blank" rel="noreferrer">Đăng ký trên {cloud.site.host}</a></span>
            <span>Quên mật khẩu, hết hạn gói? <a href={cloud.site.forgot} target="_blank" rel="noreferrer">Vào {cloud.site.host}</a></span>
          </div>
        )}
      </form>
    </div>
  );
}
