import { useCallback, useEffect, useRef, useState } from "react";
import { cancelDubAddon, getDubAddon, installDubAddon, removeDubAddon, type DubAddon } from "../../api/dub";
import { announceRunning } from "../../components/BackgroundTasks";
import { askConfirm } from "../../components/Dialogs";
import { toast } from "../../store/toast";
import "../dub.css";

const gb = (mb: number) => `${(mb / 1024).toFixed(1).replace(".", ",")} GB`;
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** The error with its links clickable (the Visual C++ runtime's download, when Windows lacks it) — the app opens
 * them in the normal browser. */
function withLinks(text: string) {
  return text.split(/(https?:\/\/[^\s)]+)/).map((part, i) =>
    /^https?:\/\//.test(part)
      ? <a key={i} href={part} target="_blank" rel="noreferrer">{part}</a>
      : part,
  );
}

function elapsed(since: string | null): string {
  if (!since) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(since).getTime()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * "🎙 Gói lồng tiếng": the speech AI the installed app does not carry (Whisper, spleeter, VieNeu). One click
 * downloads it into the data folder (services/dub_addon.py); dubbing, "chỉ chèn phụ đề", cutting by the words and
 * the VieNeu voices work once it is there. Shown on the dubbing page when nothing is installed, and in
 * Cài đặt → 🖥 Máy này (``compact``: one line when installed, with "Gỡ").
 */
export function DubAddonCard({ initial, compact = false, onReady }: {
  initial?: DubAddon | null;
  compact?: boolean;
  onReady?: () => void;
}) {
  const [st, setSt] = useState<DubAddon | null>(initial ?? null);
  const [busy, setBusy] = useState(false);
  const [, tick] = useState(0);
  const wasRunning = useRef(Boolean(initial?.running));

  const load = useCallback(async () => {
    try {
      const s = await getDubAddon();
      setSt(s);
      if (wasRunning.current && !s.running) {
        if (s.installed) {
          toast.success("Đã cài xong gói lồng tiếng — giờ lồng tiếng được trên máy này.");
          onReady?.();
        } else if (s.error) {
          toast.error(s.error);
        }
      }
      wasRunning.current = s.running;
    } catch (e) {
      toast.error(`Không đọc được gói lồng tiếng: ${errText(e)}`);
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
      const s = await installDubAddon();
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
    if (!(await askConfirm("Huỷ cài gói lồng tiếng? Phần đã tải được giữ lại — bấm Cài lại là tải tiếp chỗ dở.", { ok: "Huỷ cài", cancel: "Tiếp tục cài" }))) return;
    try { setSt(await cancelDubAddon()); } catch (e) { toast.error(errText(e)); }
  };

  const remove = async () => {
    if (!st) return;
    if (!(await askConfirm(`Gỡ gói lồng tiếng (${gb(st.size_mb ?? 0)} ở ${st.dir})? Lồng tiếng sẽ không dùng được tới khi cài lại.`,
      { ok: "Gỡ gói", danger: true }))) return;
    setBusy(true);
    try {
      setSt(await removeDubAddon());
      toast.success("Đã gỡ gói lồng tiếng.");
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
    const onCard = st.info.cuda;
    return (
      <section className={`qt-card qt-addon qt-addon--done${compact ? " qt-addon--compact" : ""}`}>
        <div className="qt-addon__head">
          <span className="qt-addon__icon" aria-hidden="true">✓</span>
          <div>
            <strong>Gói lồng tiếng đã cài</strong>
            <small>
              {onCard ? `Whisper chạy bằng card ${st.info.gpu?.name ?? "NVIDIA"}` : "Whisper chạy bằng CPU"}
              {st.size_mb ? ` · ${gb(st.size_mb)}` : ""} · <code>{st.dir}</code>
            </small>
          </div>
        </div>
        {st.info.cuda_error && <p className="qt-addon__warn">Card NVIDIA không chạy được Whisper ({st.info.cuda_error}) — đang dùng CPU. Cập nhật driver NVIDIA rồi gỡ và cài lại gói.</p>}
        {st.info.note && <p className="qt-addon__muted">Lưu ý: {st.info.note}</p>}
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
        <span className="qt-addon__icon" aria-hidden="true">🎙</span>
        <div>
          <strong>{st.running ? "Đang cài gói lồng tiếng" : "Máy này chưa có gói lồng tiếng"}</strong>
          <small>
            Lồng tiếng, chèn phụ đề, cắt video theo lời nói và giọng VieNeu cần bộ AI nghe tiếng (Whisper), tách nhạc nền và
            giọng đọc. Bộ cài DFlow không kèm sẵn vì quá nặng — bấm cài một lần, tải miễn phí về thư mục dữ liệu, sau đó dùng mãi.
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
            <span>{gb(st.done_mb)} / ~{gb(st.total_mb || st.download_mb)} · {st.progress}% · {elapsed(st.started_at)}</span>
          </div>
          <p className="qt-addon__muted">Có thể rời trang hoặc làm việc khác — nút “việc đang chạy” góc dưới phải theo dõi. Mạng chậm thì mất 15–60 phút.</p>
          <div className="qt-addon__acts">
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void cancel()}>Huỷ</button>
          </div>
        </div>
      ) : (
        <>
          <ul className="qt-addon__facts">
            {st.gpu ? (
              <li className="is-ok">✓ Card {st.gpu.name}{st.gpu.vram_mb ? ` (${gb(st.gpu.vram_mb)})` : ""} — AI chạy bằng card, nhanh.</li>
            ) : (
              <li className="is-warn">Không thấy card NVIDIA — vẫn chạy được bằng CPU nhưng chậm hơn nhiều (video 3 phút có thể mất 5–10 phút nghe).</li>
            )}
            {st.gpu?.old_driver && (
              <li className="is-warn">Driver NVIDIA {st.gpu.driver} đã cũ — cập nhật bản mới (nvidia.com hoặc GeForce Experience) để Whisper chạy bằng card.</li>
            )}
            <li>Tải khoảng {gb(st.download_mb)} · cần trống {gb(st.need_mb)} · {st.free_mb ? `ổ đĩa còn ${gb(st.free_mb)}` : ""}</li>
            <li className="qt-addon__muted">Cài vào <code>{st.dir}</code></li>
          </ul>
          {short && <p className="qt-addon__warn">Ổ đĩa không đủ chỗ — dọn bớt (hoặc đổi Thư mục dữ liệu ở Cài đặt → 🖥 Máy này) rồi cài.</p>}
          {st.error && <p className="qt-addon__err">{withLinks(st.error)}</p>}
          {!st.supported ? (
            <p className="qt-addon__warn">Gói lồng tiếng chỉ có cho Windows.</p>
          ) : (
            <div className="qt-addon__acts">
              <button type="button" className="qt-btn qt-btn--accent" disabled={busy || short} onClick={() => void install()}>
                {st.error || st.done_mb ? "⬇ Cài lại (tải tiếp chỗ dở)" : `⬇ Cài gói lồng tiếng (~${gb(st.download_mb)})`}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
