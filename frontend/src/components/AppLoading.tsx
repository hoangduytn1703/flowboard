import { useEffect, useState } from "react";

/** How long a start-up may take before the screen suggests the agent is down. */
const SLOW_AFTER_MS = 6000;

/**
 * Full-screen start-up state while the first board list loads. Past a few
 * seconds it says what usually went wrong (the local agent is not running or
 * is stuck) instead of leaving a bare "Loading…" forever.
 */
export function AppLoading() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="app-loading" role="status" aria-live="polite">
      <div className="app-loading__brand">
        <span className="app-loading__logo" aria-hidden="true">⚡</span>
        <span className="app-loading__name">Flowboard</span>
      </div>
      <div className="app-loading__spinner" aria-hidden="true" />
      <p className="app-loading__text">Đang khởi động…</p>
      {slow && (
        <div className="app-loading__slow">
          <p>
            Lâu hơn bình thường. Kiểm tra agent đang chạy (<code>make agent</code>) và không bị treo,
            rồi tải lại trang.
          </p>
          <button type="button" className="app-loading__btn" onClick={() => window.location.reload()}>
            Tải lại
          </button>
        </div>
      )}
    </div>
  );
}
