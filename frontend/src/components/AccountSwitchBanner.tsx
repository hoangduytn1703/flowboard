import { useEffect, useState } from "react";
import { checkPool, dismissPoolSwitch, getPool, openPoolFlowTab, type PoolStatus } from "../api/accountPool";

/**
 * Orange bar across the top of the Quicktool screen while the agent waits
 * for the Flow tab to be on the account it switched to. Polls the pool
 * status every 20 s (every 5 s while a switch is pending) and offers the
 * two things the user can do: open the Flow tab for that account, and
 * "I switched, check now".
 */
export function AccountSwitchBanner() {
  const [status, setStatus] = useState<PoolStatus | null>(null);
  const [busy, setBusy] = useState<"" | "open" | "check">("");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const s = await getPool();
        if (!alive) return;
        setStatus(s);
        timer = setTimeout(tick, s.pending ? 5000 : 20000);
      } catch {
        if (alive) timer = setTimeout(tick, 30000);
      }
    };
    void tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const pending = status?.pending;
  if (!pending) return null;

  async function openTab() {
    setBusy("open");
    setNote(null);
    try {
      const r = await openPoolFlowTab(pending!.to_email);
      setNote(r.ok ? "Đã mở tab Flow — chọn đúng tài khoản ở góc phải trên rồi bấm \"Đã đổi, kiểm tra\"." : "Extension không mở được tab — mở flow.google.com tay.");
    } catch (err) {
      setNote(err instanceof Error ? err.message : "lỗi");
    } finally {
      setBusy("");
    }
  }

  async function check() {
    setBusy("check");
    setNote(null);
    try {
      const r = await checkPool();
      setStatus(r.status);
      if (r.switched) setNote(`Xong — đang dùng ${r.email} (${r.credits ?? "?"} credit). Việc đang chờ sẽ chạy tiếp.`);
      else if (r.error === "account_also_exhausted") setNote(`${r.email} cũng hết credit — agent đã chuyển sang tài khoản kế.`);
      else if (r.error) setNote(`Chưa đọc được tab Flow: ${r.error}`);
      else setNote(`Tab Flow đang ở ${r.email ?? "tài khoản khác"} — hãy chuyển sang ${pending!.to_email}.`);
    } catch (err) {
      setNote(err instanceof Error ? err.message : "lỗi");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="qt-switch" role="alert">
      <div className="qt-switch__text">
        <strong>Đổi tài khoản Flow:</strong>{" "}
        {pending.from_email ? `${pending.from_email} ${pending.reason}. ` : `${pending.reason}. `}
        Đã ghim project của <strong>{pending.to_email}</strong>. Trên tab Flow, bấm avatar → <em>Chuyển đổi tài khoản</em> →
        chọn <strong>{pending.to_email}</strong>. Việc đang chạy sẽ chờ.
        {note && <div className="qt-switch__note">{note}</div>}
      </div>
      <div className="qt-switch__actions">
        <button type="button" className="qt-btn qt-btn--small" disabled={busy !== ""} onClick={() => void openTab()}>
          {busy === "open" ? "Đang mở…" : "Mở tab Flow"}
        </button>
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy !== ""} onClick={() => void check()}>
          {busy === "check" ? "Đang đọc…" : "Đã đổi, kiểm tra"}
        </button>
        <button type="button" className="qt-link" onClick={() => void dismissPoolSwitch().then(setStatus)}>ẩn</button>
      </div>
    </div>
  );
}
