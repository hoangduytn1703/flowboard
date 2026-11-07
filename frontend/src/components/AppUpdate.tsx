import { useEffect, useState } from "react";
import { api } from "../api/client";
import { checkAppUpdate, inDesktopApp, installAppUpdate, type AppUpdate } from "../lib/desktopApp";
import { toast } from "../store/toast";
import { askConfirm } from "./Dialogs";

const FIRST_CHECK_MS = 20_000;
const EVERY_MS = 6 * 60 * 60 * 1000;
const SKIP_KEY = "dflow.update.skip";

/** Asks first when work is running (the update closes the app), then installs. Shared by the banner and Settings. */
export async function runAppUpdate(version: string): Promise<boolean> {
  try {
    const busy = (await api<{ items: { title?: string }[] }>("/api/running")).items ?? [];
    if (busy.length && !(await askConfirm(
      `Đang có ${busy.length} việc chạy (${busy.slice(0, 2).map((b) => b.title).filter(Boolean).join(", ")}). Cập nhật sẽ đóng app và dừng các việc này.\n\nVẫn cập nhật lên bản ${version}?`,
      { ok: "Vẫn cập nhật" },
    ))) return false;
  } catch { /* the check is a courtesy */ }
  try {
    toast.info(`Đang tải DFlow ${version}… xong app sẽ tự đóng, cài và mở lại (dữ liệu, đăng nhập giữ nguyên).`);
    await installAppUpdate();
    return true;
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e));
    return false;
  }
}

/**
 * The desktop app tells when a newer DFlow is published: a bar at the bottom with "Cập nhật ngay". Checked 20 s after
 * start, then every 6 hours; "Để sau" hides that version until the next one. Nothing in a browser tab.
 */
export function AppUpdateBanner() {
  const [update, setUpdate] = useState<AppUpdate | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!inDesktopApp()) return;
    let alive = true;
    const check = async () => {
      try {
        const u = await checkAppUpdate();
        let skipped = "";
        try { skipped = localStorage.getItem(SKIP_KEY) ?? ""; } catch { /* storage off */ }
        if (alive && u?.version && u.version !== skipped) setUpdate(u);
      } catch { /* offline / no release yet */ }
    };
    const first = window.setTimeout(() => void check(), FIRST_CHECK_MS);
    const every = window.setInterval(() => void check(), EVERY_MS);
    return () => { alive = false; window.clearTimeout(first); window.clearInterval(every); };
  }, []);

  if (!update?.version) return null;
  const version = update.version;
  return (
    <div className="app-update" role="status">
      <span>🎉 Có bản <b>DFlow {version}</b> (đang dùng {update.current})</span>
      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy}
              onClick={async () => { setBusy(true); if (!(await runAppUpdate(version))) setBusy(false); }}>
        {busy ? "Đang tải…" : "⬇ Cập nhật ngay"}
      </button>
      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy}
              onClick={() => { try { localStorage.setItem(SKIP_KEY, version); } catch { /* storage off */ } setUpdate(null); }}>
        Để sau
      </button>
    </div>
  );
}

/** Settings → 🖥 Máy này: the version running, "Kiểm tra cập nhật" and "Cập nhật lên …". Hidden in a browser tab. */
export function AppVersionSection() {
  const [info, setInfo] = useState<AppUpdate | null>(null);
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const desktop = inDesktopApp();

  async function check(quiet = false) {
    setChecking(true);
    try {
      const u = await checkAppUpdate();
      setInfo(u);
      if (!quiet) toast.info(u?.version ? `Có bản mới: ${u.version}` : `Đang là bản mới nhất (${u?.current ?? "?"}).`);
    } catch (e) {
      if (!quiet) toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  }
  useEffect(() => { if (desktop) void check(true); }, [desktop]);

  if (!desktop) return null;
  return (
    <div className="settings-panel__section">
      <div className="settings-panel__label">Phiên bản DFlow {info?.current ? `— đang dùng ${info.current}` : ""}</div>
      <div className="settings-panel__hint">
        {info?.version
          ? <>Có bản mới <b>{info.version}</b>. Bấm cập nhật: app tự tải, đóng, cài và mở lại — dữ liệu và đăng nhập giữ nguyên.</>
          : "App tự kiểm tra bản mới mỗi lần mở và mỗi 6 giờ."}
      </div>
      <div className="qt-post__actions" style={{ marginTop: 8 }}>
        {info?.version && (
          <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={installing}
                  onClick={async () => { setInstalling(true); if (!(await runAppUpdate(info.version!))) setInstalling(false); }}>
            {installing ? "Đang tải bản mới…" : `⬇ Cập nhật lên ${info.version}`}
          </button>
        )}
        <button type="button" className="qt-btn qt-btn--small" disabled={checking || installing} onClick={() => void check()}>
          {checking ? "Đang kiểm tra…" : "↻ Kiểm tra cập nhật"}
        </button>
      </div>
    </div>
  );
}
