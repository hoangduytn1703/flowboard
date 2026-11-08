import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { logoutAccount, timeLeft } from "../api/account";
import { useAccountStore } from "../store/account";
import { toast } from "../store/toast";
import { askConfirm } from "./Dialogs";

/** Sign out of DFlow on this machine (asks first). Shared by the sidebar chip and "Tài khoản của tôi". */
export async function signOut(username: string): Promise<void> {
  if (!await askConfirm(`Thoát tài khoản ${username} trên máy này? Việc đang tạo sẽ vẫn chạy tiếp.`, { ok: "Thoát" })) return;
  try {
    await logoutAccount();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "Đăng xuất thất bại.");
    return;
  }
  window.dispatchEvent(new Event("flowboard:unauthorized"));
}

/** Sidebar row: avatar + name + plan — click it for "Tài khoản của tôi" (`/account`) — and one "Thoát" button.
 * Hidden when the agent runs without login (FLOWBOARD_AUTH=off). */
export function UserChip() {
  const me = useAccountStore((s) => s.me);
  const navigate = useNavigate();
  const here = useLocation().pathname === "/account";
  const [busy, setBusy] = useState(false);
  if (!me || !me.auth) return null;

  const name = me.profile?.display_name || me.username;
  const left = !me.is_admin && me.plan?.expires_at ? timeLeft(me.plan.expires_at) : null;
  const planText = me.is_admin ? "Quản trị" : me.plan ? `Gói ${me.plan.name}` : "";
  return (
    <div className="user-chip">
      <button type="button" className={`user-chip__me${here ? " is-here" : ""}`} onClick={() => navigate("/account")}
              title="Tài khoản của tôi: thông tin, đổi mật khẩu, gói & nâng cấp, lịch sử giao dịch">
        <span className="user-chip__avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
        <span className="user-chip__text">
          <span className="user-chip__name">{name}</span>
          <span className={`user-chip__plan${me.is_admin ? " user-chip__plan--admin" : ""}${left && left.days <= 3 ? " user-chip__plan--soon" : ""}`}>
            {planText}{left && left.text ? ` · ${left.text}` : ""}
          </span>
        </span>
      </button>
      <button type="button" className="user-chip__out" disabled={busy} title="Thoát tài khoản trên máy này"
              onClick={async () => { setBusy(true); await signOut(me.username); setBusy(false); }}>
        Thoát
      </button>
    </div>
  );
}
