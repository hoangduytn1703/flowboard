import { useState } from "react";
import { logoutAccount } from "../api/account";
import { useAccountStore } from "../store/account";
import { toast } from "../store/toast";

/** Sidebar row: who is logged in to Flowboard + sign out. Hidden when the
 * agent runs without login (FLOWBOARD_AUTH=off). */
export function UserChip() {
  const me = useAccountStore((s) => s.me);
  const [busy, setBusy] = useState(false);
  if (!me || !me.auth) return null;

  async function logout() {
    if (busy) return;
    if (!window.confirm(`Đăng xuất ${me!.username}? Việc đang tạo sẽ vẫn chạy tiếp trên máy này.`)) return;
    setBusy(true);
    try {
      await logoutAccount();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Đăng xuất thất bại.");
      setBusy(false);
      return;
    }
    window.dispatchEvent(new Event("flowboard:unauthorized"));
  }

  return (
    <div className="user-chip" title="Tài khoản Flowboard (dữ liệu clip / sản phẩm / người mẫu đi theo tài khoản này)">
      <span className="user-chip__name">👤 {me.username}</span>
      <button type="button" className="qt-link" onClick={() => void logout()} disabled={busy}>
        {busy ? "…" : "Đăng xuất"}
      </button>
    </div>
  );
}
