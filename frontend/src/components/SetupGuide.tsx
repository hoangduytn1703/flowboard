import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { openFlowTab, type SetupStatus, type SetupStep } from "../api/setup";
import { useSetupStore } from "../store/setup";
import { toast } from "../store/toast";
import "./setup.css";

const SETTINGS_TAB = "flowboard.settings.tab";
const HIDE_KEY = "dflow.setup.hidden";
const KEY_URL = "https://aistudio.google.com/apikey";

/** Keep the status current while a guide is on screen: a cheap read every 4 s, a look at the Flow tab every 12 s. */
function useSetupPolling(active: boolean) {
  const refresh = useSetupStore((s) => s.refresh);
  const check = useSetupStore((s) => s.check);
  useEffect(() => {
    if (!active) return;
    void refresh();
    let n = 0;
    const t = window.setInterval(() => {
      n += 1;
      const st = useSetupStore.getState().status;
      if (st && !st.ready && st.flow.connected && n % 3 === 0) void check();
      else void refresh();
    }, 4000);
    return () => window.clearInterval(t);
  }, [active, refresh, check]);
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`Đã copy ${what}`);
  } catch {
    toast.warning(`Không copy được — chép tay: ${text}`);
  }
}

/** What to do for the step that is not done yet. */
function StepActions({ step, status, onGo }: { step: SetupStep; status: SetupStatus; onGo: () => void }) {
  const navigate = useNavigate();
  const check = useSetupStore((s) => s.check);
  const busy = useSetupStore((s) => s.busy);
  const [link, setLink] = useState("");
  const [saving, setSaving] = useState(false);

  const openFlow = async () => {
    if (status.flow.connected) {
      const r = await openFlowTab().catch(() => ({ ok: false }));
      if (r.ok) { toast.info("Đã mở tab Google Flow trong Chrome"); return; }
    }
    window.open(status.flow_url, "_blank", "noopener");
  };
  const recheck = (
    <button type="button" className="qt-btn qt-btn--small" disabled={busy} onClick={() => void check()}>
      {busy ? "Đang kiểm tra…" : "↻ Kiểm tra lại"}
    </button>
  );

  if (step.id === "extension") {
    const dir = status.extension_dir;
    return (
      <div className="su-act">
        <ol className="su-how">
          <li>Mở <b>Chrome</b>, gõ <code>chrome://extensions</code> vào thanh địa chỉ.{" "}
            <button type="button" className="su-link" onClick={() => void copy("chrome://extensions", "địa chỉ")}>Copy</button></li>
          <li>Bật <b>Developer mode</b> (Chế độ dành cho nhà phát triển) ở góc trên phải.</li>
          <li>Bấm <b>Load unpacked</b> (Tải tiện ích đã giải nén) rồi chọn thư mục:{" "}
            {dir ? <code className="su-path">{dir}</code> : <i>thư mục “extension” trong nơi cài DFlow</i>}</li>
        </ol>
        <div className="su-btns">
          {dir && <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
            onClick={() => void api("/api/app/open", { method: "POST", body: JSON.stringify({ what: "extension" }) })
              .catch(() => toast.warning("Không mở được thư mục — copy đường dẫn rồi dán vào hộp chọn thư mục"))}>📂 Mở thư mục extension</button>}
          {dir && <button type="button" className="qt-btn qt-btn--small" onClick={() => void copy(dir, "đường dẫn")}>📋 Copy đường dẫn</button>}
        </div>
        <p className="su-wait">⏳ DFlow tự nhận ra khi extension kết nối — không cần bấm gì thêm.</p>
      </div>
    );
  }
  if (step.id === "flow") {
    return (
      <div className="su-act">
        <div className="su-btns">
          <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => void openFlow()}>↗ Mở Google Flow</button>
          {recheck}
        </div>
        <p className="su-wait">Cần tài khoản Google có gói <b>Google AI Pro</b> hoặc <b>Ultra</b> (Flow vẽ ảnh và video bằng credit của gói đó).</p>
      </div>
    );
  }
  if (step.id === "project") {
    const pin = async () => {
      setSaving(true);
      try {
        await api("/api/flow/projects/pinned", { method: "PUT", body: JSON.stringify({ flow_project_id: link.trim() }) });
        toast.success("Đã chọn dự án Flow");
        setLink("");
        await check();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Link dự án chưa đúng");
      } finally {
        setSaving(false);
      }
    };
    return (
      <div className="su-act">
        <div className="su-btns">
          {status.flow.tab_project
            ? <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy} onClick={() => void check(true)}>✓ Dùng dự án đang mở</button>
            : <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => void openFlow()}>↗ Mở Google Flow</button>}
          {recheck}
        </div>
        <details className="su-more">
          <summary>Hoặc dán link dự án</summary>
          <div className="su-paste">
            <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://flow.google.com/…/project/…"
                   onKeyDown={(e) => { if (e.key === "Enter" && link.trim()) void pin(); }} />
            <button type="button" className="qt-btn qt-btn--small" disabled={!link.trim() || saving} onClick={() => void pin()}>Lưu</button>
          </div>
        </details>
      </div>
    );
  }
  if (step.id === "ai") {
    return (
      <div className="su-act">
        <div className="su-btns">
          <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
                  onClick={() => { try { localStorage.setItem(SETTINGS_TAB, "keys"); } catch { /* private mode */ } onGo(); navigate("/settings"); }}>🔑 Dán Gemini key</button>
          <a className="qt-btn qt-btn--small" href={KEY_URL} target="_blank" rel="noreferrer">Lấy key miễn phí ↗</a>
        </div>
      </div>
    );
  }
  if (step.id === "product") {
    return <div className="su-act"><div className="su-btns">
      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => { onGo(); navigate("/products"); }}>＋ Thêm sản phẩm</button>
    </div></div>;
  }
  return <div className="su-act"><div className="su-btns">
    <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => { onGo(); navigate("/clips/new"); }}>🎬 Tạo clip đầu tiên</button>
  </div></div>;
}

/** The numbered list: done steps as one green line, the first open one unfolded with its buttons. */
export function SetupSteps({ status, onlyRequired = false, onGo = () => {} }: { status: SetupStatus; onlyRequired?: boolean; onGo?: () => void }) {
  const steps = status.steps.filter((s) => !onlyRequired || s.required);
  const current = steps.find((s) => !s.ok && (s.required || status.ready));
  return (
    <ol className="su-steps">
      {steps.map((s, i) => {
        const open = s === current;
        return (
          <li key={s.id} className={`su-step${s.ok ? " is-done" : open ? " is-now" : " is-later"}`}>
            <span className="su-step__n" aria-hidden="true">{s.ok ? "✓" : i + 1}</span>
            <div className="su-step__body">
              <div className="su-step__title">{s.title}{!s.required && !s.ok && <span className="su-step__opt">tiếp theo</span>}</div>
              <div className="su-step__detail">{s.detail}</div>
              {open && <StepActions step={s} status={status} onGo={onGo} />}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** "Hôm nay": the guide for an install that is not finished. Gone once everything is done (or hidden after the required part). */
export function SetupCard() {
  const status = useSetupStore((s) => s.status);
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(HIDE_KEY) === "1"; } catch { return false; } });
  const allDone = !!status && status.steps.every((s) => s.ok);
  useSetupPolling(!allDone && !(hidden && !!status?.ready));
  if (!status || allDone || (hidden && status.ready)) return null;
  const need = status.steps.filter((s) => s.required);
  const done = need.filter((s) => s.ok).length;
  return (
    <section className={`su-card${status.ready ? " su-card--ready" : ""}`}>
      <header className="su-card__head">
        <div>
          <h2 className="su-card__title">{status.ready ? "🎉 DFlow đã sẵn sàng" : "🚀 Thiết lập DFlow — làm một lần"}</h2>
          <p className="su-card__sub">{status.ready
            ? "Phần kết nối đã xong. Thêm sản phẩm rồi tạo clip đầu tiên."
            : `Xong ${done}/${need.length} bước. Làm theo thứ tự từ trên xuống — DFlow tự nhận ra khi bạn làm xong từng bước.`}</p>
        </div>
        {status.ready && <button type="button" className="su-hide" title="Ẩn hướng dẫn này"
          onClick={() => { try { localStorage.setItem(HIDE_KEY, "1"); } catch { /* ignore */ } setHidden(true); }}>Ẩn</button>}
      </header>
      {!status.ready && <div className="su-bar" aria-hidden="true"><span style={{ width: `${(done / need.length) * 100}%` }} /></div>}
      <SetupSteps status={status} />
    </section>
  );
}

/** Opened by `ensureReady()` when a generation is asked for before the install is finished. */
export function SetupDialog() {
  const open = useSetupStore((s) => s.guideOpen);
  const reason = useSetupStore((s) => s.reason);
  const status = useSetupStore((s) => s.status);
  const close = useSetupStore((s) => s.closeGuide);
  useSetupPolling(open);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);
  if (!open || !status) return null;
  return createPortal(
    <div className="project-modal-backdrop su-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="project-modal su-dialog qt-app" role="dialog" aria-modal="true" aria-label="Thiết lập DFlow">
        <header className="su-dialog__head">
          <h2>{status.can_generate ? "✓ Đã sẵn sàng" : "Còn thiếu một bước trước khi tạo được"}</h2>
          <button type="button" className="su-x" onClick={close} aria-label="Đóng">×</button>
        </header>
        <p className="su-dialog__sub">{status.can_generate
          ? "Mọi thứ đã kết nối. Đóng hộp này rồi bấm lại nút bạn vừa bấm."
          : `${reason ? `Để ${reason}, ` : ""}DFlow cần Google Flow trong Chrome của bạn. Làm bước đang mở bên dưới — xong là hộp này tự cập nhật.`}</p>
        <SetupSteps status={status} onlyRequired onGo={close} />
        <footer className="su-dialog__foot">
          <button type="button" className={`qt-btn${status.can_generate ? " qt-btn--accent" : ""}`} onClick={close}>{status.can_generate ? "Tiếp tục" : "Để sau"}</button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

/** Sidebar: one line that says whether Flow is wired, with the credit balance when it is. Click = the guide. */
export function FlowPill() {
  const status = useSetupStore((s) => s.status);
  const refresh = useSetupStore((s) => s.refresh);
  const openGuide = useSetupStore((s) => s.openGuide);
  const check = useSetupStore((s) => s.check);
  const busy = useSetupStore((s) => s.busy);
  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), 30000);
    return () => window.clearInterval(t);
  }, [refresh]);
  if (!status) return null;
  const missing = status.steps.find((s) => s.required && !s.ok);
  if (missing) {
    return (
      <button type="button" className="su-pill su-pill--todo" onClick={() => openGuide()} title={missing.detail}>
        <span className="su-pill__dot" aria-hidden="true" />
        <span className="su-pill__text"><b>Chưa sẵn sàng</b><small>{missing.title}</small></span>
        <span className="su-pill__go" aria-hidden="true">Thiết lập →</span>
      </button>
    );
  }
  const credits = status.flow.credits;
  const low = typeof credits === "number" && credits < 100;
  return (
    <button type="button" className={`su-pill su-pill--ok${low ? " su-pill--low" : ""}`} disabled={busy} onClick={() => void check()}
            title={`${status.flow.email ?? ""}\nGói Flow ${status.flow.plan}\nBấm để đọc lại số credit`}>
      <span className="su-pill__dot" aria-hidden="true" />
      <span className="su-pill__text">
        <b>{typeof credits === "number" ? `${credits.toLocaleString("vi-VN")} credit` : "Flow đã kết nối"}</b>
        <small>Google Flow · gói {status.flow.plan}{low ? " · sắp hết" : ""}</small>
      </span>
      <span className="su-pill__go" aria-hidden="true">{busy ? "…" : "↻"}</span>
    </button>
  );
}
