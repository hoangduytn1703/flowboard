import { useEffect, useState } from "react";
import {
  accountErrorText,
  activateFlowAccount,
  listFlowAccounts,
  refreshFlowAccounts,
  type FlowAccountsResponse,
} from "../../api/accounts";
import { toast } from "../../store/toast";

function credits(n: number | null): string {
  return n === null ? "—" : n.toLocaleString("vi-VN");
}

/**
 * Settings → Tài khoản Flow. Each Chrome profile that runs the Flowboard
 * extension shows up here with the e-mail, plan and credits read from its
 * Flow tab; one of them is the account generation uses. Switching re-pins
 * the Flow project that account used last, because projects (and the media
 * ids inside them) belong to a Google account.
 */
export function FlowAccountsSection({ onProjectChange }: { onProjectChange?: () => void }) {
  const [data, setData] = useState<FlowAccountsResponse | null>(null);
  const [busy, setBusy] = useState<"" | "refresh" | number>("");

  async function load() {
    try {
      setData(await listFlowAccounts());
    } catch {
      setData({ accounts: [], active_id: null, pinned_project_id: "" });
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function refresh() {
    setBusy("refresh");
    try {
      const r = await refreshFlowAccounts();
      setData(r);
      const failed = Object.values(r.results ?? {}).filter((x) => x.error).length;
      if (failed) toast.warning(`${failed} tài khoản chưa đọc được (xem lỗi bên dưới).`);
      else toast.success("Đã cập nhật credit.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "không đọc được");
    } finally {
      setBusy("");
    }
  }

  async function activate(id: number) {
    setBusy(id);
    try {
      const r = await activateFlowAccount(id);
      setData(r);
      if (r.repinned_project_id) {
        toast.success(`Đã chuyển tài khoản và ghim lại project ${r.repinned_project_id.slice(0, 8)}…`);
        onProjectChange?.();
      } else {
        const acc = r.accounts.find((a) => a.id === id);
        if (acc?.project_id) toast.success("Đã chuyển tài khoản.");
        else toast.warning("Đã chuyển tài khoản. Tài khoản này chưa có project ghim — chọn project ở mục Google Flow project bên dưới.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "không chuyển được");
    } finally {
      setBusy("");
    }
  }

  const accounts = data?.accounts ?? [];

  return (
    <div className="settings-panel__section">
      <div className="settings-panel__label">Tài khoản Flow ({accounts.length})</div>
      {data === null ? (
        <div className="settings-panel__hint">Đang tải…</div>
      ) : accounts.length === 0 ? (
        <div className="settings-panel__hint">Chưa có extension nào kết nối. Mở Chrome có cài Flowboard extension và một tab flow.google.com.</div>
      ) : (
        <div className="flow-accounts">
          {accounts.map((a) => {
            const err = accountErrorText(a.account_error);
            return (
              <label key={a.id} className={`flow-accounts__row${a.active ? " flow-accounts__row--active" : ""}`}>
                <input
                  type="radio"
                  name="flow-account"
                  checked={a.active}
                  disabled={busy !== ""}
                  onChange={() => void activate(a.id)}
                />
                <div className="flow-accounts__body">
                  <div className="flow-accounts__line">
                    <strong>{a.email ?? `Kết nối #${a.id}`}</strong>
                    {a.tier && <span className="model-badge">{a.tier}</span>}
                    {a.active && <span className="model-badge">Đang dùng</span>}
                  </div>
                  <div className="flow-accounts__line flow-accounts__meta">
                    <span className={a.credits !== null && a.credits < 100 ? "flow-accounts__low" : ""}>
                      ⚡ {credits(a.credits)} credit
                    </span>
                    <span>extension {a.version ?? "cũ"}</span>
                    {a.project_id && (
                      <span title={a.project_id}>
                        project {a.project_id.slice(0, 8)}…{a.project_is_pinned ? " (đang ghim)" : ""}
                      </span>
                    )}
                  </div>
                  {err && <div className="flow-accounts__err">{err}</div>}
                </div>
              </label>
            );
          })}
        </div>
      )}
      <div className="settings-panel__project-row">
        <button type="button" className="flow-accounts__btn" onClick={() => void refresh()} disabled={busy !== "" || accounts.length === 0}>
          {busy === "refresh" ? "Đang đọc…" : "↻ Đọc lại credit"}
        </button>
      </div>
      <div className="settings-panel__hint">
        Thêm tài khoản: mở một <strong>Chrome profile khác</strong> đã đăng nhập Google khác, cài cùng extension
        (Load unpacked → thư mục <code>extension/</code>) và mở flow.google.com — nó tự hiện ở đây. Credit được đọc
        từ bảng tài khoản trên tab Flow (tab sẽ nháy một chút khi đọc). Chuyển tài khoản thì project ghim đổi theo;
        clip tạo bằng tài khoản cũ vẫn mở được, ảnh/video đã có được upload lại khi cần.
      </div>
    </div>
  );
}
