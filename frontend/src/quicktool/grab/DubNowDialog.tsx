import { useEffect, useState } from "react";
import { getDefaultLook, getDubStatus, listLookPresets, type DecorPreset, type DubStatus } from "../../api/dub";
import type { DubNowOptions } from "../../api/grab";
import { useSettingsStore } from "../../store/settings";
import { VoiceField } from "../VoiceField";
import { ModePicker } from "../dub/ModePicker";

const KEY = "dflow.grab.dubnow";
const DEFAULT_VOICE = "vi-VN-HoaiMyNeural";

/** What was chosen last time (this machine); the voice falls back to the account's dubbing voice. */
export function savedDubNow(dubVoice: string): DubNowOptions {
  const base: DubNowOptions = { mode: "dub", voice: dubVoice || DEFAULT_VOICE, keep_bgm: true, look_preset_id: null, sub_lang: "vi", translator: "google" };
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) || "null") as Partial<DubNowOptions> | null;
    if (!raw) return base;
    return { ...base, ...raw, mode: raw.mode === "sub" ? "sub" : "dub", voice: raw.voice || base.voice };
  } catch {
    return base;
  }
}
function remember(o: DubNowOptions) {
  try { window.localStorage.setItem(KEY, JSON.stringify(o)); } catch { /* private mode */ }
}

/**
 * "🎙 Lồng tiếng ngay" on the grab list: voice-over or subtitles only, the voice, the saved look — then one click and
 * the agent downloads what is missing and dubs, the cards of the list showing each video's progress.
 */
export function DubNowDialog({ count, missing, onStart, onClose, onOpenPage }: {
  count: number;
  /** how many of them still have to be downloaded */
  missing: number;
  onStart: (o: DubNowOptions) => Promise<void>;
  onClose: () => void;
  /** the full dubbing page with these videos (every other option) */
  onOpenPage?: () => void;
}) {
  const dubVoice = useSettingsStore((s) => s.dubVoice);
  const setDubVoice = useSettingsStore((s) => s.setDubVoice);
  const [o, setO] = useState<DubNowOptions>(() => savedDubNow(dubVoice));
  const [looks, setLooks] = useState<DecorPreset[]>([]);
  const [status, setStatus] = useState<DubStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const hadSaved = (() => { try { return !!window.localStorage.getItem(KEY); } catch { return false; } })();

  useEffect(() => {
    void getDubStatus().then(setStatus).catch(() => undefined);
    void listLookPresets().then(async (ps) => {
      setLooks(ps);
      if (hadSaved) {  // a look deleted since: back to none
        setO((x) => (x.look_preset_id && !ps.some((p) => p.id === x.look_preset_id) ? { ...x, look_preset_id: null } : x));
        return;
      }
      const d = await getDefaultLook().catch(() => ({ id: null }));
      if (d.id && ps.some((p) => p.id === d.id)) setO((x) => ({ ...x, look_preset_id: d.id }));
    }).catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const blocked = status && !status.available ? (status.reason || "Máy này chưa lồng tiếng được") : "";
  async function go() {
    if (busy || blocked) return;
    setBusy(true);
    remember(o);
    if (o.mode === "dub") setDubVoice(o.voice);
    try {
      await onStart(o);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gb-now__back" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="gb-now" role="dialog" aria-modal="true" aria-label="Lồng tiếng ngay">
        <header className="gb-now__head">
          <h3>🎙 Lồng tiếng {count} video</h3>
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={onClose} disabled={busy} aria-label="Đóng">×</button>
        </header>
        <ModePicker name="gb-now-mode" value={o.mode === "sub" ? "sub" : "dub"} onChange={(mode) => setO({ ...o, mode })} disabled={busy} />
        {o.mode === "dub" ? (
          <>
            <label className="qt-field"><span>Giọng đọc</span></label>
            <VoiceField value={o.voice} onChange={(voice) => setO({ ...o, voice })} disabled={busy} />
            {status?.separate && (
              <label className="qt-check">
                <input type="checkbox" checked={o.keep_bgm} onChange={(e) => setO({ ...o, keep_bgm: e.target.checked })} />
                <span>Giữ nhạc nền gốc (tách giọng nói ra)</span>
              </label>
            )}
          </>
        ) : (
          <label className="qt-field">
            <span>Phụ đề bằng</span>
            <select value={o.sub_lang} onChange={(e) => setO({ ...o, sub_lang: e.target.value })}>
              <option value="vi">Tiếng Việt (dịch)</option>
              <option value="orig">Đúng lời trong video (không dịch)</option>
              <option value="en">Tiếng Anh</option>
            </select>
          </label>
        )}
        {looks.length > 0 && (
          <label className="qt-field">
            <span>Kiểu chỉnh sửa <small>(khung, nền, kiểu phụ đề đã lưu)</small></span>
            <select value={o.look_preset_id ?? ""} onChange={(e) => setO({ ...o, look_preset_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— Không dùng mẫu —</option>
              {looks.map((p) => <option key={p.id} value={p.id}>★ {p.name}</option>)}
            </select>
          </label>
        )}
        {blocked && <p className="gb-now__warn">⚠ {blocked}</p>}
        <p className="gb-now__note">
          {missing > 0 ? `Tool tải ${missing} video còn thiếu rồi lồng tiếng lần lượt` : "Các video lồng tiếng lần lượt"} — tiến độ hiện ngay trên từng thẻ video,
          video nào xong mở chỉnh được luôn. Bạn rời trang này vẫn chạy tiếp.
        </p>
        <footer className="gb-now__foot">
          {onOpenPage && <button type="button" className="qt-link" onClick={onOpenPage} disabled={busy}>Tuỳ chọn khác (mở trang Lồng tiếng) →</button>}
          <span className="gb__barspace" />
          <button type="button" className="qt-btn" onClick={onClose} disabled={busy}>Huỷ</button>
          <button type="button" className="qt-btn qt-btn--accent" onClick={() => void go()} disabled={busy || !!blocked} autoFocus>
            {busy ? "Đang gửi…" : "▶ Bắt đầu"}
          </button>
        </footer>
      </div>
    </div>
  );
}
