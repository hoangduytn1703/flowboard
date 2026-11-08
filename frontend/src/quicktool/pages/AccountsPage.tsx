import { useCallback, useEffect, useState } from "react";
import {
  createAccount, dayText, extendPlan, getPlans, listAccounts, logoutAccountEverywhere, randomPassword, resetAccountPassword, termLabel, timeLeft, vnd,
  updateAccount, type AccountList, type ManagedAccount, type PlansData,
} from "../../api/account";
import { askConfirm, askText } from "../../components/Dialogs";
import { useAccountStore } from "../../store/account";
import { toast } from "../../store/toast";
import { PageEmpty, PageLoading } from "../PageState";
import { PlansEditor } from "./PlansEditor";
import { BillingEditor } from "./BillingEditor";
import { PlanAssignDialog } from "./PlanAssignDialog";
import "./accounts.css";

/** Times from the agent are naive UTC ("2026-11-08T03:12:00"). */
function when(iso: string | null): string {
  if (!iso) return "chưa đăng nhập";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
}

async function copy(text: string, done: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(done);
  } catch {
    toast.warning("Không copy được — chọn chữ rồi Ctrl+C.");
  }
}

function loginNote(username: string, password: string) {
  return `Tài khoản DFlow\nTên đăng nhập: ${username}\nMật khẩu: ${password}\n(Đăng nhập xong bấm vào tên của bạn ở góc dưới trái → "Đổi mật khẩu" để đặt mật khẩu của bạn.)`;
}

/**
 * "👥 Quản lý tài khoản" — the admin account only (the menu item is hidden for others and the API says 403):
 * create accounts for friends, reset a forgotten password, lock / unlock, log an account out everywhere.
 */
export function AccountsPage() {
  const me = useAccountStore((s) => s.me);
  const [data, setData] = useState<AccountList | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState(() => randomPassword());
  const [note, setNote] = useState("");
  const [cloud, setCloud] = useState(true);
  const [made, setMade] = useState<{ username: string; password: string; cloud: boolean } | null>(null);
  const [plansData, setPlansData] = useState<PlansData | null>(null);
  const [planId, setPlanId] = useState("");
  const [newMonths, setNewMonths] = useState(0);
  const [assigning, setAssigning] = useState<ManagedAccount | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, pl] = await Promise.all([listAccounts(), getPlans()]);
      setData(list);
      setPlansData(pl);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => { document.title = "Quản lý tài khoản · DFlow"; }, []);
  useEffect(() => { if (me?.is_admin) void load(); }, [me?.is_admin, load]);

  if (!me?.is_admin) {
    return (
      <>
        <header className="qt-header"><span className="qt-header__crumb">Quản lý tài khoản</span></header>
        <PageEmpty icon="🔒" title="Chỉ tài khoản quản trị mới vào được trang này">
          Bạn đổi được mật khẩu, tên hiển thị và xem gói của mình ở trang <b>Tài khoản của tôi</b> (bấm vào tên ở góc dưới trái).
        </PageEmpty>
      </>
    );
  }
  if (!data) {
    return error
      ? <PageEmpty icon="⚠️" title="Không tải được danh sách tài khoản" actions={<button type="button" className="qt-btn" onClick={() => void load()}>Thử lại</button>}>{error}</PageEmpty>
      : <PageLoading text="Đang tải danh sách tài khoản…" />;
  }

  const min = data.min_password;
  const nameOk = /^[a-zA-Z0-9._-]{1,64}$/.test(username.trim());
  const createProblem = !username.trim() ? "Nhập tên đăng nhập."
    : !nameOk ? "Tên đăng nhập chỉ gồm chữ không dấu, số, dấu . _ -"
    : password.length < min ? `Mật khẩu cần ít nhất ${min} ký tự.`
    : data.accounts.some((a) => a.username === username.trim().toLowerCase()) ? "Tên đăng nhập này đã có."
    : "";

  async function create() {
    if (createProblem) { toast.warning(createProblem); return; }
    setBusy("create");
    try {
      const row = await createAccount({ username: username.trim(), password, note, cloud: data!.cloud && cloud, plan: newPlan || undefined,
        ...(newPlan && newPlan !== plansData?.trial_id ? { months: newMonths } : {}) });
      setMade({ username: row.username, password, cloud: row.backend === "postgres" });
      setUsername("");
      setNote("");
      setPassword(randomPassword());
      toast.success(`Đã tạo tài khoản ${row.username}.`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function act(a: ManagedAccount, key: string, run: () => Promise<unknown>, done: string) {
    setBusy(`${a.username}:${key}`);
    try {
      await run();
      if (done) toast.success(done);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function resetPassword(a: ManagedAccount) {
    const next = await askText(
      `Mật khẩu mới cho ${a.username} (ít nhất ${min} ký tự). Các máy đang đăng nhập tài khoản này sẽ bị đăng xuất.`,
      randomPassword(), { ok: "Đặt mật khẩu" },
    );
    if (next === null) return;
    if (next.length < min) { toast.warning(`Mật khẩu cần ít nhất ${min} ký tự.`); return; }
    await act(a, "pw", async () => {
      await resetAccountPassword(a.username, next);
      await copy(loginNote(a.username, next), `Đã đặt mật khẩu mới cho ${a.username} và copy thông tin đăng nhập để gửi cho họ.`);
    }, "");
  }

  async function toggleLock(a: ManagedAccount) {
    if (!a.disabled && !(await askConfirm(
      `Khoá tài khoản ${a.username}? Họ bị đăng xuất ở mọi máy và không đăng nhập được nữa cho tới khi bạn mở khoá. Dữ liệu của họ giữ nguyên.`,
      { ok: "Khoá tài khoản", danger: true },
    ))) return;
    await act(a, "lock", () => updateAccount(a.username, { disabled: !a.disabled }),
      a.disabled ? `Đã mở khoá ${a.username}.` : `Đã khoá ${a.username}.`);
  }

  async function editNote(a: ManagedAccount) {
    const next = await askText(`Ghi chú cho ${a.username} (ai dùng, hết hạn khi nào…)`, a.note, { placeholder: "Ví dụ: bạn Nam, dùng thử tới 30/11" });
    if (next === null) return;
    await act(a, "note", () => updateAccount(a.username, { note: next }), "Đã lưu ghi chú.");
  }

  async function extend(a: ManagedAccount) {
    const days = plansData?.plans.find((p) => p.id === plansData.trial_id)?.days ?? 7;
    await act(a, "extend", () => extendPlan(a.username), `Đã gia hạn dùng thử cho ${a.username}: thêm ${days} ngày tính từ hôm nay.`);
  }

  async function logoutAll(a: ManagedAccount) {
    const self = a.username === data!.me;
    if (!(await askConfirm(self
      ? "Đăng xuất tài khoản của bạn ở mọi máy / trình duyệt khác? Máy này vẫn giữ đăng nhập."
      : `Đăng xuất ${a.username} ở mọi máy? Họ đăng nhập lại bằng mật khẩu như cũ.`, { ok: "Đăng xuất" }))) return;
    await act(a, "out", async () => {
      const r = await logoutAccountEverywhere(a.username);
      toast.success(`Đã đăng xuất ${r.logged_out ?? 0} phiên của ${a.username}.`);
    }, "");
  }

  const users = data.accounts.filter((a) => a.role !== "admin").length;
  const plansList = plansData?.plans ?? [];
  const newPlan = planId && plansList.some((p) => p.id === planId) ? planId : plansData?.default ?? "";
  const planOf = (a: ManagedAccount) => (a.plan && plansList.some((p) => p.id === a.plan) ? a.plan : plansData?.default ?? "");
  const planLabel = (id: string) => plansList.find((p) => p.id === id)?.name ?? id;
  return (
    <>
      <header className="qt-header"><span className="qt-header__crumb">Quản lý tài khoản</span></header>
      <div className="qt-home acc">
        {data.licensing?.active && (data.licensing.can_sign ? (
          <div className="acc-lic acc-lic--key">
            🔑 Máy này có <b>khoá ký</b> ({data.licensing.key_path}) — gói, hạn, khoá tài khoản, bảng gói và thông tin chuyển khoản được ký bằng khoá này,
            ai sửa tay cơ sở dữ liệu cũng vô hiệu. <b>Sao lưu file khoá</b> (USB / trình quản lý mật khẩu): mất là không cấp gói mới được.
          </div>
        ) : (
          <div className="acc-lic acc-lic--nokey">
            🔒 Máy này <b>không có khoá ký</b> nên chỉ xem được: tạo tài khoản, đổi gói / hạn, khoá, lưu bảng gói / thanh toán và duyệt nâng cấp phải làm
            trên máy có khoá. (Muốn quản lý ở máy này: chép file <code>dflow-license.key</code> từ máy có khoá vào <code>{data.licensing.key_path}</code>.)
          </div>
        ))}
        <section className="qt-card acc-new">
          <div className="qt-card__head"><h3 className="qt-card__title">＋ Tạo tài khoản cho người khác</h3></div>
          <p className="qt-card__hint">
            Mỗi tài khoản có dữ liệu riêng (clip, sản phẩm, bài viết, kênh, ảnh / video) — <strong>không ai thấy của ai</strong>.
            Chỉ tài khoản quản trị (bạn) tạo được tài khoản; người khác chỉ đổi được mật khẩu của họ.
          </p>
          <form className="acc-new__grid" onSubmit={(e) => { e.preventDefault(); void create(); }}>
            <label className="qt-field">
              <span>Tên đăng nhập</span>
              <input value={username} maxLength={64} placeholder="vd: nam.nguyen" autoComplete="off"
                     onChange={(e) => setUsername(e.target.value.replace(/\s/g, ""))} />
            </label>
            <label className="qt-field">
              <span>Mật khẩu (ít nhất {min} ký tự)</span>
              <span className="acc-new__pw">
                <input value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" spellCheck={false} />
                <button type="button" className="qt-btn qt-btn--small" title="Tạo mật khẩu ngẫu nhiên" onClick={() => setPassword(randomPassword())}>🎲</button>
              </span>
            </label>
            <label className="qt-field acc-new__note">
              <span>Ghi chú (không bắt buộc)</span>
              <input value={note} maxLength={200} placeholder="vd: bạn Nam, dùng thử tới 30/11" onChange={(e) => setNote(e.target.value)} />
            </label>
            <label className="qt-field">
              <span>Gói</span>
              <select value={newPlan} onChange={(e) => { const id = e.target.value; setPlanId(id); setNewMonths(plansList.find((p) => p.id === id)?.terms?.[0]?.months ?? 0); }}>
                {plansList.map((p) => <option key={p.id} value={p.id}>{p.name}{p.id === plansData?.trial_id ? ` (${p.days ?? 7} ngày)` : ""}</option>)}
              </select>
            </label>
            {newPlan && newPlan !== plansData?.trial_id && (
              <label className="qt-field">
                <span>Thời hạn</span>
                <select value={newMonths} onChange={(e) => setNewMonths(Number(e.target.value))}>
                  {(plansData?.term_months ?? [0]).map((m) => {
                    const sold = plansList.find((p) => p.id === newPlan)?.terms?.find((x) => x.months === m);
                    return <option key={m} value={m}>{termLabel(m)}{sold ? ` · ${vnd(sold.price)}` : ""}</option>;
                  })}
                </select>
              </label>
            )}
            {data.cloud && (
              <label className="acc-new__cloud">
                <input type="checkbox" checked={cloud} onChange={(e) => setCloud(e.target.checked)} />
                <span>Lưu dữ liệu của tài khoản này trên cloud — đăng nhập máy nào cũng thấy (nên bật)</span>
              </label>
            )}
            <div className="acc-new__go">
              <button type="submit" className="qt-btn qt-btn--accent" disabled={busy === "create"}>
                {busy === "create" ? "Đang tạo…" : "Tạo tài khoản"}
              </button>
              {username && createProblem && <span className="acc-new__problem">{createProblem}</span>}
            </div>
          </form>
          {made && (
            <div className="acc-made">
              <div>
                <b>✓ Đã tạo {made.username}</b> — gửi cho họ thông tin đăng nhập
                {made.cloud ? " (dữ liệu trên cloud)" : " (dữ liệu nằm trên máy họ đăng nhập lần đầu)"}:
              </div>
              <pre className="acc-made__text">{loginNote(made.username, made.password)}</pre>
              <div className="acc-made__btns">
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
                        onClick={() => void copy(loginNote(made.username, made.password), "Đã copy thông tin đăng nhập.")}>📋 Copy để gửi</button>
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setMade(null)}>Đóng</button>
              </div>
              <p className="qt-card__hint">Mật khẩu chỉ hiện lúc này. Quên thì bấm 🔑 Đặt lại mật khẩu ở danh sách dưới.</p>
            </div>
          )}
        </section>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">Tài khoản ({data.accounts.length})</h3>
            <button type="button" className="qt-btn qt-btn--small" onClick={() => void load()}>↻ Tải lại</button>
          </div>
          {users === 0 && <p className="qt-card__hint">Chưa có tài khoản nào ngoài bạn. Tạo ở khung trên.</p>}
          <div className="acc-table" role="table">
            <div className="acc-row acc-row--head" role="row">
              <span>Tài khoản</span><span>Gói</span><span>Ghi chú</span><span>Dữ liệu</span><span>Đăng nhập gần nhất</span><span>Thao tác</span>
            </div>
            {data.accounts.map((a) => {
              const admin = a.role === "admin";
              const b = (k: string) => busy === `${a.username}:${k}`;
              return (
                <div key={a.username} className={`acc-row${a.disabled ? " acc-row--off" : ""}`} role="row">
                  <span className="acc-name">
                    <b>{a.username}</b>
                    {admin && <span className="acc-chip acc-chip--admin">quản trị</span>}
                    {a.username === data.me && <span className="acc-chip">bạn</span>}
                    {a.disabled && <span className="acc-chip acc-chip--off">đã khoá</span>}
                    {a.expired && !a.disabled && <span className="acc-chip acc-chip--off" title="Hết hạn gói: không đăng nhập được">hết hạn</span>}
                    {data.licensing?.active && a.license === "missing" && (
                      <span className="acc-chip acc-chip--off" title="Chưa có chữ ký: không đăng nhập được. Mở “Gói & thời hạn”, chọn gói rồi lưu để ký.">⚠ chưa ký</span>
                    )}
                    {data.licensing?.active && a.license === "invalid" && (
                      <span className="acc-chip acc-chip--off" title="Chữ ký không khớp (bị sửa tay): không đăng nhập được. Mở “Gói & thời hạn”, chọn gói rồi lưu để ký lại.">⚠ chữ ký sai</span>
                    )}
                    {a.tampered && (
                      <span className="acc-chip acc-chip--warn" title="Dòng tài khoản trong cơ sở dữ liệu bị sửa tay (gói / hạn / quyền / khoá). App dùng giá trị đã ký, phần sửa không có tác dụng.">⚠ bị sửa tay</span>
                    )}
                    {a.display_name && <small className="acc-display">{a.display_name}</small>}
                  </span>
                  <span className="acc-plan">
                    {admin ? <span className="acc-chip acc-chip--admin" title="Tài khoản quản trị luôn có mọi tính năng">Toàn quyền</span> : (
                      (() => {
                        const pid = planOf(a);
                        const isTrial = pid === plansData?.trial_id;
                        const left = timeLeft(a.plan_expires);
                        return (
                          <>
                            <button type="button" className={`acc-planbtn${isTrial ? " acc-planbtn--trial" : ""}`} disabled={!plansData}
                                    title="Đổi gói / thời hạn của tài khoản này" onClick={() => setAssigning(a)}>
                              <b>{planLabel(pid)}</b><span aria-hidden="true">✎</span>
                            </button>
                            <span className={`acc-trial${left.over ? " acc-trial--over" : a.plan_expires && left.days <= 3 ? " acc-trial--soon" : ""}`}>
                              {a.plan_expires
                                ? <span title={`Hết hạn ngày ${dayText(a.plan_expires)}`}>{left.over ? `Hết hạn ${dayText(a.plan_expires)}` : `${left.text} · tới ${dayText(a.plan_expires)}`}</span>
                                : <span>vĩnh viễn</span>}
                              {isTrial ? (
                                <button type="button" className="qt-link" disabled={b("extend")} onClick={() => void extend(a)}
                                        title="Dùng thử lại từ hôm nay (số ngày đặt ở bảng Gói)">Gia hạn</button>
                              ) : a.plan_expires && (
                                <button type="button" className="qt-link" onClick={() => setAssigning(a)} title="Gia hạn / đổi thời hạn">Gia hạn</button>
                              )}
                            </span>
                          </>
                        );
                      })()
                    )}
                  </span>
                  <span className="acc-note">
                    {a.note || <i className="acc-muted">—</i>}
                    <button type="button" className="qt-link" disabled={b("note")} onClick={() => void editNote(a)}>✎</button>
                  </span>
                  <span title={a.backend === "postgres" ? "Trên cloud: đăng nhập máy nào cũng thấy" : "Trên một máy (máy đăng nhập lần đầu)"}>
                    {a.backend === "postgres" ? "☁ Cloud" : "💻 Một máy"}
                  </span>
                  <span className="acc-seen">
                    {when(a.last_seen)}
                    {a.last_seen && <small>{a.last_host ? `máy ${a.last_host} · ` : ""}{a.sessions} phiên</small>}
                  </span>
                  <span className="acc-acts">
                    {!admin && (
                      <button type="button" className="qt-btn qt-btn--small" disabled={b("pw")} onClick={() => void resetPassword(a)}
                              title="Đặt mật khẩu mới (khi họ quên)">🔑 Mật khẩu</button>
                    )}
                    {!admin && (
                      <button type="button" className={`qt-btn qt-btn--small${a.disabled ? "" : " qt-btn--danger"}`} disabled={b("lock")}
                              onClick={() => void toggleLock(a)}>{a.disabled ? "🔓 Mở khoá" : "🔒 Khoá"}</button>
                    )}
                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={b("out") || a.sessions === 0}
                            onClick={() => void logoutAll(a)} title="Đăng xuất tài khoản này ở mọi máy / trình duyệt">⎋ Đăng xuất</button>
                  </span>
                </div>
              );
            })}
          </div>
          <p className="qt-card__hint">
            Khoá = không đăng nhập được, dữ liệu vẫn giữ (mở khoá là dùng lại như cũ). Hết hạn dùng thử cũng vậy — bấm <b>Gia hạn</b> hoặc
            chuyển sang gói khác là đăng nhập lại được. Đổi mật khẩu / khoá có hiệu lực ngay trên máy này; máy khác đang mở app nhận ra trong vòng 5 phút.
          </p>
        </section>

        {assigning && plansData && (
          <PlanAssignDialog account={assigning} plans={plansData} onClose={() => setAssigning(null)} onSaved={() => void load()} />
        )}
        {plansData && <PlansEditor data={plansData} onSaved={(next) => { setPlansData(next); void load(); }} />}
        {plansData && <BillingEditor plans={plansData.plans.filter((p) => p.id !== plansData.trial_id)} onDecided={() => void load()} />}
      </div>
    </>
  );
}
