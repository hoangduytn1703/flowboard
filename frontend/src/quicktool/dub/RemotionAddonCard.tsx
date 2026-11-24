import { useCallback, useEffect, useRef, useState } from "react";
import { cancelRemotionAddon, getRemotionAddon, installRemotionAddon, removeRemotionAddon, type RemotionAddon } from "../../api/dub";
import { announceRunning } from "../../components/BackgroundTasks";
import { askConfirm } from "../../components/Dialogs";
import { toast } from "../../store/toast";
import "../dub.css";

const mbText = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1).replace(".", ",")} GB` : `${Math.max(0, Math.round(mb))} MB`);
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

function elapsed(since: string | null): string {
  if (!since) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(since).getTime()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * "🎬 Bộ cài phụ đề đẹp": the second subtitle engine (font Việt, emoji màu, karaoke) needs Node + the Remotion packages +
 * a headless Chrome, which the installed app does not carry. One click installs them next to the user's data
 * (services/remotion_addon.py). Shown where Remotion is offered but does not run yet, and in Cài đặt → 🖥 Máy này
 * (``compact``: one line when installed, with "Gỡ").
 */
export function RemotionAddonCard({ initial, compact = false, onReady }: {
  initial?: RemotionAddon | null;
  compact?: boolean;
  onReady?: () => void;
}) {
  const [st, setSt] = useState<RemotionAddon | null>(initial ?? null);
  const [busy, setBusy] = useState(false);
  const [, tick] = useState(0);
  const wasRunning = useRef(Boolean(initial?.running));

  const load = useCallback(async () => {
    try {
      const s = await getRemotionAddon();
      setSt(s);
      if (wasRunning.current && !s.running) {
        if (s.installed) {
          toast.success("Đã cài xong bộ cài phụ đề đẹp — chọn được phụ đề đẹp trên máy này.");
          onReady?.();
        } else if (s.error) {
          toast.error(s.error);
        }
      }
      wasRunning.current = s.running;
    } catch (e) {
      toast.error(`Không đọc được bộ cài phụ đề đẹp: ${errText(e)}`);
    }
  }, [onReady]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!st?.running) return;
    const t = window.setInterval(() => { void load(); tick((n) => n + 1); }, 1500);
    return () => window.clearInterval(t);
  }, [st?.running, load]);

  const install = async () => {
    setBusy(true);
    try {
      const s = await installRemotionAddon();
      wasRunning.current = true;
      setSt(s);
      announceRunning();
    } catch (e) {
      toast.error(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!(await askConfirm("Huỷ cài bộ cài phụ đề đẹp?", { ok: "Huỷ cài", cancel: "Tiếp tục cài" }))) return;
    try { setSt(await cancelRemotionAddon()); } catch (e) { toast.error(errText(e)); }
  };

  const remove = async () => {
    if (!st) return;
    if (!(await askConfirm(`Gỡ bộ cài phụ đề đẹp (${mbText(st.size_mb ?? 0)} ở ${st.dir})? Phụ đề đẹp sẽ không dùng được tới khi cài lại.`,
      { ok: "Gỡ gói", danger: true }))) return;
    setBusy(true);
    try {
      setSt(await removeRemotionAddon());
      toast.success("Đã gỡ bộ cài phụ đề đẹp.");
      onReady?.();
    } catch (e) {
      toast.error(errText(e));
    } finally {
      setBusy(false);
    }
  };

  if (!st) {
    return <section className={`qt-card qt-addon${compact ? " qt-addon--compact" : ""}`}><p className="qt-addon__muted">Đang kiểm tra máy…</p></section>;
  }

  if (st.installed && !st.running) {
    return (
      <section className={`qt-card qt-addon qt-addon--done${compact ? " qt-addon--compact" : ""}`}>
        <div className="qt-addon__head">
          <span className="qt-addon__icon" aria-hidden="true">✓</span>
          <div>
            <strong>Bộ cài phụ đề đẹp đã cài</strong>
            <small>
              Remotion {st.info.remotion ?? ""} · Node {st.info.node ?? ""}{st.size_mb ? ` · ${mbText(st.size_mb)}` : ""} · <code>{st.dir}</code>
            </small>
          </div>
        </div>
        <div className="qt-addon__acts">
          <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={busy} onClick={() => void remove()}>🗑 Gỡ gói</button>
        </div>
      </section>
    );
  }

  const short = st.free_mb > 0 && st.free_mb < st.need_mb;
  return (
    <section className={`qt-card qt-addon${compact ? " qt-addon--compact" : ""}`}>
      <div className="qt-addon__head">
        <span className="qt-addon__icon" aria-hidden="true">🎬</span>
        <div>
          <strong>{st.running ? "Đang cài bộ cài phụ đề đẹp" : "Máy này chưa có bộ cài phụ đề đẹp"}</strong>
          <small>
            Phụ đề đẹp (font Việt đẹp, emoji màu, chữ sáng từng từ kiểu TikTok) cần Node.js, bộ Remotion và một trình duyệt ẩn để
            vẽ. Bộ cài DFlow không kèm sẵn — bấm cài một lần, tải miễn phí về thư mục dữ liệu, sau đó dùng mãi.
          </small>
        </div>
      </div>

      {st.running ? (
        <div className="qt-addon__run">
          <div className="qt-addon__bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={st.progress}>
            <span style={{ width: `${Math.max(2, st.progress)}%` }} />
          </div>
          <div className="qt-addon__line">
            <span>{st.phase || "Đang chuẩn bị…"}</span>
            <span>{mbText(st.done_mb)} / ~{mbText(st.total_mb || st.download_mb)} · {st.progress}% · {elapsed(st.started_at)}</span>
          </div>
          <p className="qt-addon__muted">Có thể rời trang hoặc làm việc khác — nút “việc đang chạy” theo dõi. Thường mất 3–15 phút tuỳ mạng.</p>
          <div className="qt-addon__acts">
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void cancel()}>Huỷ</button>
          </div>
        </div>
      ) : (
        <>
          <ul className="qt-addon__facts">
            <li>Tải khoảng {mbText(st.download_mb)} · cần trống {mbText(st.need_mb)}{st.free_mb ? ` · ổ đĩa còn ${mbText(st.free_mb)}` : ""}</li>
            <li className="qt-addon__muted">Cài vào <code>{st.dir}</code></li>
          </ul>
          {short && <p className="qt-addon__warn">Ổ đĩa không đủ chỗ — dọn bớt (hoặc đổi Thư mục dữ liệu ở Cài đặt → 🖥 Máy này) rồi cài.</p>}
          {st.error && <p className="qt-addon__err">{st.error}</p>}
          {!st.supported ? (
            <p className="qt-addon__warn">Bộ cài phụ đề đẹp chưa có cho máy này.</p>
          ) : (
            <div className="qt-addon__acts">
              <button type="button" className="qt-btn qt-btn--accent" disabled={busy || short} onClick={() => void install()}>
                {st.error ? "⬇ Cài lại" : `⬇ Cài bộ cài phụ đề đẹp (~${mbText(st.download_mb)})`}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
