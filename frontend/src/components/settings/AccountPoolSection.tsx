import { useEffect, useState } from "react";
import {
  getPool,
  removePoolAccount,
  setPoolAuto,
  switchPoolAccount,
  upsertPoolAccount,
  type PoolStatus,
} from "../../api/accountPool";
import { toast } from "../../store/toast";

function fmt(n: number | null): string {
  return n === null ? "—" : n.toLocaleString("vi-VN");
}

/**
 * Settings → Danh sách tài khoản Flow. Several Google accounts signed in to
 * the same Chrome, each with its own Flow project; when the one in use runs
 * out of credits the agent pins the next account's project and asks for its
 * Flow tab. The signed-in account joins the list by itself (with the pinned
 * project) the first time its panel is read, so the usual way to add one is:
 * switch the Flow tab to it, pin its project, done.
 */
export function AccountPoolSection({ onProjectChange }: { onProjectChange?: () => void }) {
  const [status, setStatus] = useState<PoolStatus | null>(null);
  const [email, setEmail] = useState("");
  const [project, setProject] = useState("");
  const [busy, setBusy] = useState<"" | "add" | "auto" | string>("");

  async function load() {
    try {
      setStatus(await getPool());
    } catch {
      setStatus({ auto: true, accounts: [], active_email: null, pinned_project_id: "", pending: null, last_switch: null });
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function run(key: string, fn: () => Promise<PoolStatus>, okNote?: string) {
    setBusy(key);
    try {
      setStatus(await fn());
      if (okNote) toast.success(okNote);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "lỗi");
    } finally {
      setBusy("");
    }
  }

  async function add() {
    if (!email.trim()) return;
    await run("add", () => upsertPoolAccount({ email: email.trim(), project_id: project.trim() || null }), "Đã thêm.");
    setEmail("");
    setProject("");
  }

  const accounts = status?.accounts ?? [];

  return (
    <div className="settings-panel__section">
      <div className="settings-panel__label">Danh sách tài khoản Flow ({accounts.length}) · tự chuyển khi hết credit</div>
      <label className="pool__auto">
        <input
          type="checkbox"
          checked={status?.auto ?? true}
          disabled={busy !== "" || status === null}
          onChange={(e) => void run("auto", () => setPoolAuto(e.target.checked))}
        />
        Hết credit thì tự ghim project của tài khoản kế tiếp và báo tôi đổi tài khoản trên tab Flow
      </label>
      {status === null ? (
        <div className="settings-panel__hint">Đang tải…</div>
      ) : accounts.length === 0 ? (
        <div className="settings-panel__hint">
          Chưa có tài khoản nào. Tài khoản đang đăng nhập trên tab Flow sẽ tự vào danh sách (kèm project đang ghim)
          khi extension đọc được nó; hoặc thêm tay bên dưới.
        </div>
      ) : (
        <div className="pool">
          {accounts.map((a) => {
            const active = a.email === status.active_email;
            const dry = a.credits !== null ? a.credits < 25 : !!a.exhausted_at;
            return (
              <div key={a.email} className={`pool__row${active ? " pool__row--active" : ""}${dry ? " pool__row--dry" : ""}`}>
                <div className="pool__main">
                  <div className="pool__line">
                    <strong>{a.email}</strong>
                    {a.label && <span className="pool__label">{a.label}</span>}
                    {a.tier && <span className="model-badge">{a.tier}</span>}
                    {active && <span className="model-badge">Đang dùng</span>}
                    {!a.enabled && <span className="pool__muted">tắt</span>}
                  </div>
                  <div className="pool__line pool__meta">
                    <span className={dry ? "flow-accounts__low" : ""}>⚡ {fmt(a.credits)} credit{dry ? " · hết" : ""}</span>
                    <span>
                      project{" "}
                      <input
                        className="pool__project"
                        defaultValue={a.project_id ?? ""}
                        placeholder="dán uuid / link project"
                        onBlur={(e) => {
                          const v = e.target.value.trim();
                          if (v !== (a.project_id ?? "")) void run(a.email, () => upsertPoolAccount({ email: a.email, project_id: v || null }), "Đã lưu project.");
                        }}
                      />
                      {a.project_id && a.project_id === status.pinned_project_id && <span className="pool__muted"> (đang ghim)</span>}
                    </span>
                  </div>
                </div>
                <div className="pool__actions">
                  {!active && a.project_id && (
                    <button type="button" className="flow-accounts__btn" disabled={busy !== ""}
                            onClick={() => void run(a.email, () => switchPoolAccount(a.email), `Đã ghim project của ${a.email} — mở tab Flow và chọn tài khoản này.`).then(() => onProjectChange?.())}>
                      Dùng tài khoản này
                    </button>
                  )}
                  <button type="button" className="flow-accounts__btn" disabled={busy !== ""}
                          onClick={() => void run(a.email, () => upsertPoolAccount({ email: a.email, enabled: !a.enabled }))}>
                    {a.enabled ? "Tắt" : "Bật"}
                  </button>
                  <button type="button" className="flow-accounts__btn" disabled={busy !== ""}
                          onClick={() => { if (window.confirm(`Bỏ ${a.email} khỏi danh sách?`)) void run(a.email, () => removePoolAccount(a.email)); }}>
                    Bỏ
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="pool__add">
        <input className="settings-panel__project-input" type="email" placeholder="email Google" value={email}
               onChange={(e) => setEmail(e.target.value)} />
        <input className="settings-panel__project-input" type="text" placeholder="project id hoặc link project của tài khoản đó" value={project}
               onChange={(e) => setProject(e.target.value)} />
        <button type="button" className="flow-accounts__btn" disabled={busy !== "" || !email.trim()} onClick={() => void add()}>
          {busy === "add" ? "Đang thêm…" : "+ Thêm"}
        </button>
      </div>
      <div className="settings-panel__hint">
        Mỗi tài khoản Google Pro có 100 credit/tháng (~4 clip Omni 8 s). Khi tài khoản đang dùng không đủ credit cho
        clip kế tiếp, agent ghim project của tài khoản tiếp theo, mở tab Flow cho tài khoản đó và chờ bạn đổi tài khoản
        trên tab Flow (banner màu cam sẽ hiện). Việc đang chạy chờ tối đa 15 phút chứ không hỏng. Ảnh/video đã có được
        upload lại vào project mới khi cần.
      </div>
    </div>
  );
}
