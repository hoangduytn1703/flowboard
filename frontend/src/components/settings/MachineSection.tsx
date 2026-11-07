import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";

interface AppStatus {
  /** the desktop app (DFlow.exe) — not start.ps1 */
  app: boolean;
  can_restart: boolean;
  can_open: boolean;
  env_file: string;
  storage_dir: string;
  storage_custom: string;
  logs_dir: string;
  extension_dir: string | null;
  paygate_tier: string;
  plan: string;
  cloud_db: { set: boolean; host: string; active: boolean };
  erase_root: string;
  erase_python: string;
  capcut_drafts: string;
  /** keys saved that only take effect after a restart */
  restart_pending: string[];
}

type Settings = Partial<{
  paygate_tier: string; central_db_url: string; storage_dir: string; erase_root: string; erase_python: string; capcut_drafts: string;
}>;

const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * Settings → 🖥 Máy này: what only this machine knows, so nobody has to edit the .env file by hand —
 * the Flow plan, the cloud data line, where the data / dubbing kit / CapCut projects live — and, in the desktop
 * app, the extension folder to load into Chrome, the app's folders and a restart.
 */
export function MachineSection() {
  const [st, setSt] = useState<AppStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [dbLine, setDbLine] = useState("");
  const [storage, setStorage] = useState("");
  const [eraseRoot, setEraseRoot] = useState("");
  const [erasePython, setErasePython] = useState("");
  const [restarting, setRestarting] = useState(false);

  async function load() {
    try {
      const s = await api<AppStatus>("/api/app/status");
      setSt(s);
      setStorage(s.storage_custom);
      setEraseRoot(s.erase_root);
      setErasePython(s.erase_python);
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  useEffect(() => { void load(); }, []);

  async function save(body: Settings, done: string) {
    setBusy(true);
    try {
      const s = await api<AppStatus>("/api/app/settings", { method: "PUT", body: JSON.stringify(body) });
      setSt(s);
      toast.success(done);
      return true;
    } catch (e) {
      toast.error(errMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function open(what: "extension" | "data" | "logs" | "settings") {
    try {
      await api("/api/app/open", { method: "POST", body: JSON.stringify({ what }) });
    } catch (e) {
      toast.error(errMessage(e));
    }
  }

  async function restart(force = false) {
    setRestarting(true);
    try {
      await api("/api/app/restart", { method: "POST", body: JSON.stringify({ force }) });
    } catch (e) {
      setRestarting(false);
      const msg = errMessage(e);
      if (msg.includes("Đang có việc chạy") && window.confirm(`${msg}\n\nVẫn khởi động lại ngay? (việc đang chạy sẽ dừng giữa chừng)`)) {
        void restart(true);
      } else {
        toast.error(msg);
      }
      return;
    }
    // the app starts the agent again: wait for it, then reload into the fresh one
    const started = Date.now();
    await new Promise((r) => setTimeout(r, 1500));
    for (;;) {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (res.ok) break;
      } catch { /* not up yet */ }
      if (Date.now() - started > 90_000) {
        setRestarting(false);
        toast.error("DFlow chưa chạy lại được — tắt hẳn DFlow (chuột phải biểu tượng ở khay → Thoát DFlow) rồi mở lại.");
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
    window.location.reload();
  }

  if (!st) return <div className="settings-panel__section"><div className="settings-panel__hint">Đang tải…</div></div>;

  const pending = st.restart_pending.length > 0;
  return (
    <>
      {pending && (
        <div className="settings-panel__section settings-machine__pending">
          <div className="settings-panel__label">Cần khởi động lại để áp dụng</div>
          <div className="settings-panel__hint">
            Đã lưu {st.restart_pending.map((k) => (k.includes("CENTRAL") ? "dòng dữ liệu cloud" : "thư mục dữ liệu")).join(" và ")}.
            {st.can_restart ? "" : " Tắt cửa sổ DFlow (start.ps1) rồi chạy lại."}
          </div>
          {st.can_restart && (
            <div className="qt-post__actions" style={{ marginTop: 8 }}>
              <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={restarting} onClick={() => void restart()}>
                {restarting ? "Đang khởi động lại…" : "↻ Khởi động lại DFlow"}
              </button>
            </div>
          )}
        </div>
      )}

      <div className="settings-panel__section">
        <div className="settings-panel__label">Gói Google Flow của tài khoản trên máy này</div>
        <div className="qt-post__actions" role="radiogroup" aria-label="Gói Flow">
          {[["PAYGATE_TIER_ONE", "Pro"], ["PAYGATE_TIER_TWO", "Ultra"]].map(([key, label]) => (
            <button key={key} type="button" role="radio" aria-checked={st.paygate_tier === key} disabled={busy}
                    className={`qt-btn qt-btn--small${st.paygate_tier === key ? " qt-btn--accent" : " qt-btn--ghost"}`}
                    onClick={() => st.paygate_tier !== key && void save({ paygate_tier: key }, `Đã chọn gói ${label} — có hiệu lực ngay.`)}>
              {label}
            </button>
          ))}
        </div>
        <div className="settings-panel__hint">
          Xem ở flow.google.com: bấm ảnh đại diện góc trên phải. Chọn sai gói thì Flow từ chối hoặc dùng model kém hơn.
        </div>
      </div>

      {st.extension_dir && (
        <div className="settings-panel__section">
          <div className="settings-panel__label">Extension DFlow Bridge (cầu nối với Google Flow)</div>
          <div className="settings-panel__hint">
            Mở Chrome → gõ <code>chrome://extensions</code> → bật <b>Developer mode</b> (góc trên phải) → <b>Load unpacked</b> → chọn thư mục:
            <br /><code>{st.extension_dir}</code>
            <br />Sau mỗi lần cập nhật DFlow, bấm nút tải lại (↻) ở ô DFlow Bridge rồi F5 tab flow.google.com.
          </div>
          {st.can_open && (
            <div className="qt-post__actions" style={{ marginTop: 8 }}>
              <button type="button" className="qt-btn qt-btn--small" onClick={() => void open("extension")}>📂 Mở thư mục extension</button>
            </div>
          )}
        </div>
      )}

      <div className="settings-panel__section">
        <div className="settings-panel__label">Dùng chung dữ liệu với máy khác (cloud)</div>
        <div className="settings-panel__hint">
          {st.cloud_db.active
            ? <>Đang dùng dữ liệu trên cloud (<code>{st.cloud_db.host}</code>) — đăng nhập máy nào cũng thấy cùng dữ liệu.</>
            : st.cloud_db.set
              ? <>Đã lưu dòng kết nối (<code>{st.cloud_db.host}</code>) — khởi động lại để dùng.</>
              : <>Đang dùng dữ liệu trên máy này. Muốn thấy cùng sản phẩm, clip, bài viết với máy khác: dán dòng kết nối người quản lý DFlow gửi
                  riêng (bắt đầu bằng <code>postgresql://</code> hoặc <code>FLOWBOARD_CENTRAL_DB_URL=</code>). <b>Giữ bí mật dòng này.</b></>}
        </div>
        <div className="settings-machine__row">
          <input type="password" className="settings-panel__select" value={dbLine} placeholder="Dán dòng kết nối vào đây" autoComplete="off"
                 onChange={(e) => setDbLine(e.target.value)} disabled={busy} />
          <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy || !dbLine.trim()}
                  onClick={() => void save({ central_db_url: dbLine.trim() }, "Đã lưu — khởi động lại DFlow để dùng dữ liệu cloud.").then((ok) => ok && setDbLine(""))}>
            Lưu
          </button>
          {st.cloud_db.set && (
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy}
                    onClick={() => window.confirm("Bỏ kết nối cloud? Sau khi khởi động lại, DFlow dùng dữ liệu trên máy này (dữ liệu cloud vẫn còn nguyên).")
                      && void save({ central_db_url: "" }, "Đã bỏ — khởi động lại để dùng dữ liệu trên máy này.")}>
              Bỏ kết nối
            </button>
          )}
        </div>
      </div>

      <div className="settings-panel__section">
        <div className="settings-panel__label">Thư mục lưu ảnh, video, dữ liệu</div>
        <div className="settings-panel__hint">
          Đang ở <code>{st.storage_dir}</code>. Ổ C đầy thì chọn thư mục ở ổ khác (ví dụ <code>D:\DFlow-data</code>). Dữ liệu cũ <b>không</b> tự chuyển
          sang — nếu cần, tắt DFlow rồi chép nội dung thư mục cũ sang thư mục mới. Dùng dữ liệu cloud thì ảnh / video tự tải về lại khi cần.
        </div>
        <div className="settings-machine__row">
          <input type="text" className="settings-panel__select" value={storage} placeholder="để trống = thư mục mặc định"
                 onChange={(e) => setStorage(e.target.value)} disabled={busy} />
          <button type="button" className="qt-btn qt-btn--small" disabled={busy || storage.trim() === st.storage_custom}
                  onClick={() => void save({ storage_dir: storage.trim() }, "Đã lưu — khởi động lại DFlow để dùng thư mục mới.")}>
            Lưu
          </button>
        </div>
      </div>

      <div className="settings-panel__section">
        <div className="settings-panel__label">Bộ lồng tiếng VieDub (pyvideotrans) — chỉ khi dùng lồng tiếng</div>
        <div className="settings-panel__hint">
          Để trống nếu VieDub nằm ở <code>D:\codes\pyvideotrans</code>. Trang Lồng tiếng video tự báo còn thiếu gì.
        </div>
        <label className="settings-field">
          <span className="settings-panel__hint">Thư mục VieDub</span>
          <input type="text" className="settings-panel__select" value={eraseRoot} placeholder="ví dụ E:\VieDub"
                 onChange={(e) => setEraseRoot(e.target.value)} disabled={busy} />
        </label>
        <label className="settings-field">
          <span className="settings-panel__hint">Python của VieDub</span>
          <input type="text" className="settings-panel__select" value={erasePython} placeholder="ví dụ E:\VieDub\.venv\Scripts\python.exe"
                 onChange={(e) => setErasePython(e.target.value)} disabled={busy} />
        </label>
        <div className="qt-post__actions" style={{ marginTop: 8 }}>
          <button type="button" className="qt-btn qt-btn--small"
                  disabled={busy || (eraseRoot.trim() === st.erase_root && erasePython.trim() === st.erase_python)}
                  onClick={() => void save({ erase_root: eraseRoot.trim(), erase_python: erasePython.trim() }, "Đã lưu đường dẫn VieDub.")}>
            Lưu
          </button>
        </div>
      </div>

      {st.can_open && (
        <div className="settings-panel__section">
          <div className="settings-panel__label">Thư mục của DFlow</div>
          <div className="qt-post__actions">
            <button type="button" className="qt-btn qt-btn--small" onClick={() => void open("data")}>📂 Dữ liệu</button>
            <button type="button" className="qt-btn qt-btn--small" onClick={() => void open("logs")}>📄 Nhật ký (log)</button>
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void open("settings")}>⚙ File cấu hình (.env)</button>
          </div>
          <div className="settings-panel__hint">Gặp lỗi: gửi file <code>agent.log</code> trong thư mục Nhật ký cho người hỗ trợ.</div>
        </div>
      )}
    </>
  );
}
