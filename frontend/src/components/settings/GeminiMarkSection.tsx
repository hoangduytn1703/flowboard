import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";

interface MarkStatus {
  enabled: boolean;
  /** cached generated images that could still carry the stamp */
  candidates: number;
}

/**
 * Settings → Tạo ảnh & video: the Gemini sparkle Flow stamps in the corner
 * of every generated image. On by default: each image is cleaned the
 * moment it lands in the cache; the button cleans the ones already there.
 */
export function GeminiMarkSection() {
  const [status, setStatus] = useState<MarkStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<MarkStatus>("/api/media/clean-marks").then(setStatus).catch(() => setStatus({ enabled: true, candidates: 0 }));
  }, []);

  async function toggle(enabled: boolean) {
    try {
      setStatus(await api<MarkStatus>("/api/media/clean-marks", { method: "PUT", body: JSON.stringify({ enabled }) }));
      toast.success(enabled ? "Ảnh tạo mới sẽ được xoá logo Gemini ✦ tự động." : "Đã tắt — ảnh tạo mới giữ nguyên logo.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }
  async function runAll() {
    setBusy(true);
    try {
      const r = await api<{ checked: number; cleaned: number }>("/api/media/clean-marks/run", { method: "POST" });
      toast.success(`Đã kiểm tra ${r.checked} ảnh, xoá logo trên ${r.cleaned} ảnh. Tải lại trang để thấy ảnh mới.`, { duration: 8000 });
      setStatus((s) => (s ? { ...s, candidates: 0 } : s));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-panel__section">
      <label className="settings-field settings-field--check">
        <input type="checkbox" checked={status?.enabled ?? true} disabled={!status} onChange={(e) => void toggle(e.target.checked)} />
        <span className="settings-panel__label">Tự xoá logo Gemini ✦ ở góc ảnh sau khi tạo</span>
      </label>
      <div className="settings-panel__hint">
        Flow in một ngôi sao mờ ở góc dưới phải mọi ảnh tạo ra. Tool hoàn nguyên đúng điểm ảnh gốc dưới ngôi sao (không làm mờ),
        ngay khi ảnh về máy. Ảnh bạn upload không bị đụng tới. Video Veo chưa xử lý.
      </div>
      <div className="qt-post__actions" style={{ marginTop: 8 }}>
        <button type="button" className="qt-btn qt-btn--small" disabled={busy || !status} onClick={() => void runAll()}>
          {busy ? "Đang xoá…" : `Xoá trên ảnh đã có${status?.candidates ? ` (${status.candidates} ảnh)` : ""}`}
        </button>
      </div>
    </div>
  );
}
