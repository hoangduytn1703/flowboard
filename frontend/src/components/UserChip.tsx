import { useState } from "react";
import { logoutAccount } from "../api/account";
import { useAccountStore } from "../store/account";
import { toast } from "../store/toast";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { askConfirm } from "./Dialogs";

/** Sidebar row: who is logged in to DFlow, "Đổi mật khẩu" + sign out. Hidden when the
 * agent runs without login (FLOWBOARD_AUTH=off). */
export function UserChip() {
  const me = useAccountStore((s) => s.me);
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState(false);
  if (!me || !me.auth) return null;

  async function logout() {
    if (busy) return;
    if (!await askConfirm(`Đăng xuất ${me!.username}? Việc đang tạo sẽ vẫn chạy tiếp trên máy này.`)) return;
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
    <div className="user-chip" title="Tài khoản DFlow (dữ liệu clip / sản phẩm / người mẫu đi theo tài khoản này)">
      <span className="user-chip__name">👤 {me.username}{me.is_admin && <span className="user-chip__role">quản trị</span>}</span>
      <span className="user-chip__actions">
        <button type="button" className="qt-link" onClick={() => setChanging(true)} title="Đổi mật khẩu đăng nhập DFlow">
          Đổi mật khẩu
        </button>
        <button type="button" className="qt-link" onClick={() => void logout()} disabled={busy}>
          {busy ? "…" : "Đăng xuất"}
        </button>
      </span>
      {changing && <ChangePasswordDialog username={me.username} onClose={() => setChanging(false)} />}
    </div>
  );
}
