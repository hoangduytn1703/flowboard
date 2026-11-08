import { useCallback, useEffect, useMemo, useRef, useState, type InputHTMLAttributes } from "react";
import { useNavigate } from "react-router-dom";
import {
  agentDate, cancelUpgrade, changeAccountPassword, dayText, getAccountMe, getUpgradeOffer, listMyUpgrades, logoutOthers, saveProfile,
  timeLeft, vnd, type AccountProfile, type UpgradeOffer, type UpgradeRequest,
} from "../../api/account";
import { askConfirm } from "../../components/Dialogs";
import { signOut } from "../../components/UserChip";
import { UpgradeDialog } from "../../components/UpgradeDialog";
import { useAccountStore } from "../../store/account";
import { toast } from "../../store/toast";
import { PageLoading } from "../PageState";
import "./account.css";

const MIN_PASSWORD = 6;
const EMPTY: AccountProfile = { display_name: "", phone: "", email: "", contact: "" };

const STATUS: Record<UpgradeRequest["status"], { text: string; tone: string }> = {
  pending: { text: "⏳ Chờ kiểm tra tiền", tone: "wait" },
  approved: { text: "✓ Đã nâng gói", tone: "ok" },
  rejected: { text: "✕ Bị từ chối", tone: "bad" },
  cancelled: { text: "Đã huỷ", tone: "off" },
};

function stamp(iso: string | null): string {
  const d = agentDate(iso);
  if (!d) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
}

/**
 * "Tài khoản của tôi" (`/account`, opened by clicking your name at the bottom of the sidebar): your plan (+ when it runs
 * out — trial or paid term — and "⬆ Nâng cấp / gia hạn"), your details, change password, the upgrade requests you sent (transaction history)
 * and logging out other machines. Every account has it; the admin also gets a link to account management.
 */
export function AccountPage() {
  const me = useAccountStore((s) => s.me);
  const navigate = useNavigate();
  const [offer, setOffer] = useState<UpgradeOffer | null>(null);
  const [history, setHistory] = useState<UpgradeRequest[] | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [busy, setBusy] = useState("");

  const [profile, setProfile] = useState<AccountProfile>(EMPTY);
  const savedProfile = useMemo(() => ({ ...EMPTY, ...(me?.profile ?? {}) }), [me?.profile]);
  useEffect(() => setProfile(savedProfile), [savedProfile]);

  const [pw, setPw] = useState({ current: "", next: "", again: "" });
  const [showPw, setShowPw] = useState(false);
  const pwBox = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    // the plan may have changed since the app opened (the admin approved an upgrade / extended the trial)
    try {
      useAccountStore.getState().setMe(await getAccountMe());
    } catch { /* the 401 handler takes over */ }
    const admin = useAccountStore.getState().me?.is_admin;
    const [o, h] = await Promise.allSettled([admin ? Promise.resolve(null) : getUpgradeOffer(), listMyUpgrades()]);
    if (o.status === "fulfilled") setOffer(o.value);
    setHistory(h.status === "fulfilled" ? h.value.requests : []);
  }, []);

  useEffect(() => { document.title = "Tài khoản của tôi · DFlow"; }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("focus") === "password") pwBox.current?.focus();
  }, []);

  if (!me || !me.auth) return <PageLoading text="Đang tải tài khoản…" />;

  const name = me.profile?.display_name || me.username;
  const plan = me.plan;
  const trial = !!plan?.trial;
  const left = timeLeft(plan?.expires_at);
  const pending = history?.find((r) => r.status === "pending") ?? null;
  const featureLabels = offer?.features ?? [];
  const mine = new Set(me.features ?? []);
  const profileDirty = JSON.stringify(profile) !== JSON.stringify(savedProfile);

  async function saveInfo() {
    setBusy("profile");
    try {
      const next = await saveProfile(profile);
      useAccountStore.getState().setMe(next);
      toast.success("Đã lưu thông tin tài khoản.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  const pwProblem = !pw.current ? "Nhập mật khẩu hiện tại."
    : pw.next.length < MIN_PASSWORD ? `Mật khẩu mới cần ít nhất ${MIN_PASSWORD} ký tự.`
    : pw.next === pw.current ? "Mật khẩu mới phải khác mật khẩu hiện tại."
    : pw.next !== pw.again ? "Hai ô mật khẩu mới chưa giống nhau."
    : "";

  async function changePassword() {
    if (pwProblem) { toast.warning(pwProblem); return; }
    setBusy("pw");
    try {
      const r = await changeAccountPassword(pw.current, pw.next);
      setPw({ current: "", next: "", again: "" });
      toast.success(r.logged_out
        ? `Đã đổi mật khẩu. ${r.logged_out} máy / trình duyệt khác đang đăng nhập tài khoản này đã bị đăng xuất.`
        : "Đã đổi mật khẩu.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function others() {
    if (!(await askConfirm("Đăng xuất tài khoản này ở mọi máy / trình duyệt khác? Máy này vẫn giữ đăng nhập.", { ok: "Đăng xuất máy khác" }))) return;
    setBusy("others");
    try {
      const r = await logoutOthers();
      toast.success(r.logged_out ? `Đã đăng xuất ${r.logged_out} máy / trình duyệt khác.` : "Không có máy nào khác đang đăng nhập.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function withdraw() {
    setBusy("cancel");
    try {
      await cancelUpgrade();
      toast.info("Đã huỷ yêu cầu nâng cấp.");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  const field = (key: keyof AccountProfile, label: string, props: InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="qt-field">
      <span>{label}</span>
      <input value={profile[key]} maxLength={120} onChange={(e) => setProfile((p) => ({ ...p, [key]: e.target.value }))} {...props} />
    </label>
  );
  const pwType = showPw ? "text" : "password";

  return (
    <>
      <header className="qt-header"><span className="qt-header__crumb">Tài khoản của tôi</span></header>
      <div className="qt-home me">
        <section className="qt-card me-hero">
          <div className="me-hero__who">
            <div className="me-avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</div>
            <div className="me-hero__names">
              <h2>{name}</h2>
              <div className="me-hero__sub">
                <span>@{me.username}</span>
                {me.is_admin && <span className="me-chip me-chip--admin">quản trị</span>}
                <span>{me.backend === "postgres" ? "☁ Dữ liệu trên cloud" : "💻 Dữ liệu trên máy này"}</span>
                {me.created_at && <span>Tạo ngày {dayText(me.created_at)}</span>}
              </div>
            </div>
          </div>

          <div className={`me-plan${trial ? " me-plan--trial" : ""}${left.over ? " me-plan--over" : ""}`}>
            <div className="me-plan__label">Gói đang dùng</div>
            <div className="me-plan__name">{me.is_admin ? "Toàn quyền" : plan?.name ?? "—"}</div>
            {!me.is_admin && (plan?.expires_at ? (
              <div className="me-plan__ends">
                {left.over ? "Đã hết hạn" : `${trial ? "Dùng thử " : "Còn "}${left.text.replace(/^còn /, "")}`} · hết hạn ngày <b>{dayText(plan.expires_at)}</b>
                {left.days <= 3 && !left.over && (
                  <div className="me-plan__warn">Sắp hết hạn — hết hạn là không đăng nhập được. {trial ? "Nâng gói" : "Gia hạn"} để dùng tiếp.</div>
                )}
              </div>
            ) : plan && !trial && <div className="me-plan__ends">Dùng <b>vĩnh viễn</b> — không cần gia hạn</div>)}
            {me.is_admin ? (
              <button type="button" className="qt-btn qt-btn--small" onClick={() => navigate("/accounts")}>👥 Quản lý tài khoản & gói</button>
            ) : (
              <button type="button" className="qt-btn qt-btn--accent" onClick={() => setUpgrading(true)}>
                {plan?.expires_at && !trial ? "↻ Gia hạn / nâng cấp gói" : "⬆ Nâng cấp gói"}
              </button>
            )}
            {pending && (
              <div className="me-plan__pending">⏳ Đã gửi yêu cầu <b>{pending.plan_name} · {pending.term}</b> — chờ người quản lý kiểm tra tiền.</div>
            )}
          </div>
        </section>

        {!me.is_admin && featureLabels.length > 0 && (
          <section className="qt-card">
            <div className="qt-card__head"><h3 className="qt-card__title">Gói {plan?.name} có những gì</h3></div>
            <ul className="me-feats">
              {featureLabels.map((f) => {
                const on = mine.has(f.key);
                return (
                  <li key={f.key} className={on ? "is-on" : ""} title={f.desc}>
                    <span className="me-feats__mark" aria-hidden="true">{on ? "✓" : "—"}</span>
                    <span>{f.icon} {f.label}</span>
                  </li>
                );
              })}
            </ul>
            <p className="qt-card__hint">Làm clip, sản phẩm, người mẫu, prompt, lịch sử thì gói nào cũng có. Muốn thêm tính năng: bấm <b>⬆ Nâng cấp gói</b>.</p>
          </section>
        )}

        <div className="me-grid">
          <form className="qt-card" onSubmit={(e) => { e.preventDefault(); void saveInfo(); }}>
            <div className="qt-card__head"><h3 className="qt-card__title">Thông tin cá nhân</h3></div>
            <div className="me-form">
              {field("display_name", "Tên hiển thị (hiện ở góc dưới trái)", { placeholder: me.username, autoComplete: "name" })}
              {field("phone", "Số điện thoại", { placeholder: "vd: 0901 234 567", inputMode: "tel", autoComplete: "tel" })}
              {field("email", "Email", { placeholder: "vd: ban@gmail.com", type: "email", autoComplete: "email" })}
              {field("contact", "Liên hệ khác (Zalo, Facebook…)", { placeholder: "vd: Zalo 0901 234 567" })}
            </div>
            <p className="qt-card__hint">Tên đăng nhập <b>{me.username}</b> không đổi được. Người quản lý dùng số điện thoại / Zalo để liên hệ khi bạn nâng gói.</p>
            <div className="me-actions">
              <button type="submit" className="qt-btn qt-btn--accent" disabled={!profileDirty || busy === "profile"}>
                {busy === "profile" ? "Đang lưu…" : "💾 Lưu thông tin"}
              </button>
              {profileDirty && <button type="button" className="qt-btn qt-btn--ghost" onClick={() => setProfile(savedProfile)}>Huỷ</button>}
            </div>
          </form>

          <form className="qt-card" onSubmit={(e) => { e.preventDefault(); void changePassword(); }}>
            <div className="qt-card__head"><h3 className="qt-card__title">🔑 Đổi mật khẩu</h3></div>
            <div className="me-form">
              <input type="text" name="username" autoComplete="username" value={me.username} readOnly hidden />
              <label className="qt-field">
                <span>Mật khẩu hiện tại</span>
                <input ref={pwBox} type={pwType} autoComplete="current-password" value={pw.current}
                       onChange={(e) => setPw((p) => ({ ...p, current: e.target.value }))} />
              </label>
              <label className="qt-field">
                <span>Mật khẩu mới (ít nhất {MIN_PASSWORD} ký tự)</span>
                <input type={pwType} autoComplete="new-password" value={pw.next} onChange={(e) => setPw((p) => ({ ...p, next: e.target.value }))} />
              </label>
              <label className="qt-field">
                <span>Nhập lại mật khẩu mới</span>
                <input type={pwType} autoComplete="new-password" value={pw.again} onChange={(e) => setPw((p) => ({ ...p, again: e.target.value }))} />
              </label>
              <label className="me-check">
                <input type="checkbox" checked={showPw} onChange={(e) => setShowPw(e.target.checked)} /> Hiện mật khẩu
              </label>
            </div>
            <p className="qt-card__hint">Đổi xong, các máy / trình duyệt khác đang đăng nhập tài khoản này sẽ bị đăng xuất. Máy này vẫn giữ đăng nhập.</p>
            <div className="me-actions">
              <button type="submit" className="qt-btn qt-btn--accent" disabled={busy === "pw" || !pw.current}>
                {busy === "pw" ? "Đang đổi…" : "Đổi mật khẩu"}
              </button>
              {pw.current && pwProblem && <span className="me-problem">{pwProblem}</span>}
            </div>
          </form>
        </div>

        <section className="qt-card">
          <div className="qt-card__head">
            <h3 className="qt-card__title">🧾 Lịch sử giao dịch</h3>
            <button type="button" className="qt-btn qt-btn--small" onClick={() => void load()}>↻ Tải lại</button>
          </div>
          {history === null ? <p className="qt-card__hint">Đang tải…</p>
            : history.length === 0 ? (
              <p className="qt-card__hint">
                Chưa có giao dịch nào.{!me.is_admin && <> Bấm <b>⬆ Nâng cấp gói</b> để chọn gói và chuyển khoản.</>}
              </p>
            ) : (
              <div className="me-tx" role="table">
                <div className="me-tx__row me-tx__row--head" role="row">
                  <span>Thời gian</span><span>Gói</span><span>Số tiền</span><span>Nội dung chuyển khoản</span><span>Trạng thái</span>
                </div>
                {history.map((r) => (
                  <div key={r.id} className={`me-tx__row me-tx__row--${STATUS[r.status]?.tone ?? "off"}`} role="row">
                    <span className="me-tx__when">{stamp(r.created_at)}</span>
                    <span><b>{r.plan_name}</b> · {r.term}</span>
                    <span className="me-tx__amount">{vnd(r.amount)}</span>
                    <span className="me-tx__content">{r.content}</span>
                    <span className="me-tx__status">
                      {STATUS[r.status]?.text ?? r.status}
                      {r.decided_at && r.status !== "pending" && <small>{stamp(r.decided_at)}</small>}
                      {r.status === "pending" && (
                        <button type="button" className="qt-link" disabled={busy === "cancel"} onClick={() => void withdraw()}>Huỷ yêu cầu</button>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            )}
        </section>

        <section className="qt-card">
          <div className="qt-card__head"><h3 className="qt-card__title">Đăng nhập</h3></div>
          <div className="me-sessions">
            <button type="button" className="qt-btn" disabled={busy === "others"} onClick={() => void others()}>⎋ Đăng xuất các máy khác</button>
            <button type="button" className="qt-btn qt-btn--danger" onClick={() => void signOut(me.username)}>Thoát khỏi máy này</button>
          </div>
          <p className="qt-card__hint">Quên mật khẩu: nhờ người quản lý DFlow đặt lại. Việc đang tạo (ảnh, video, lồng tiếng…) vẫn chạy tiếp khi bạn thoát.</p>
        </section>
      </div>
      {upgrading && <UpgradeDialog onClose={() => { setUpgrading(false); void load(); }} />}
    </>
  );
}
