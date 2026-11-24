import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchVoiceGroups } from "../../api/client";
import {
  createVoiceClone, deleteVoiceClone, listVoiceClones, updateVoiceClone, type CloneGender, type VoiceClone,
} from "../../api/voices";
import { askConfirm, askText } from "../../components/Dialogs";
import { useSettingsStore } from "../../store/settings";
import { toast } from "../../store/toast";
import { PageEmpty, PageLoading } from "../PageState";
import { VoicePreview } from "../VoiceField";
import "../voiceclone.css";

/** Longest a recording runs before it stops by itself (VieNeu hears 8 s of speech; a little room for pauses). */
const RECORD_MAX_S = 15;
const SAMPLE_LINE = "Chào cả nhà, hôm nay mình review một món đồ mình dùng gần một tháng rồi, thấy khá ổn nên chia sẻ với mọi người nhé.";
const GENDERS: { value: CloneGender; label: string }[] = [
  { value: "female", label: "Nữ" }, { value: "male", label: "Nam" }, { value: "", label: "Không ghi" },
];

interface Take { blob: Blob; name: string; url: string; from: "mic" | "file" }

/**
 * /voices — "🧬 Giọng nhân bản": record ~10 s (or pick a recording) → VieNeu learns the voice → it shows in every
 * voice picker (dubbing, clip export, saved models…) and reads any text. Saved with the account, not the recording.
 */
export function VoicesPage() {
  const navigate = useNavigate();
  const dubVoice = useSettingsStore((s) => s.dubVoice);
  const setDubVoice = useSettingsStore((s) => s.setDubVoice);
  const [items, setItems] = useState<VoiceClone[] | null>(null);
  const [machine, setMachine] = useState<{ ok: boolean; reason: string } | null>(null);
  const [take, setTake] = useState<Take | null>(null);
  const [name, setName] = useState("Giọng của tôi");
  const [gender, setGender] = useState<CloneGender>("female");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const prev = document.title;
    document.title = "Giọng nhân bản · DFlow";
    return () => { document.title = prev; };
  }, []);
  async function load() {
    try {
      setItems(await listVoiceClones());
    } catch (e) {
      setItems([]);
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    void load();
    fetchVoiceGroups(true).then((groups) => {
      const vn = groups.find((g) => g.id === "vieneu");
      setMachine({ ok: vn?.available !== false, reason: vn?.reason ?? "" });
    }).catch(() => setMachine({ ok: true, reason: "" }));
  }, []);
  useEffect(() => () => {  // leaving the page: stop the microphone and free the preview
    if (timer.current) window.clearInterval(timer.current);
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);
  useEffect(() => () => { if (take) URL.revokeObjectURL(take.url); }, [take]);

  async function startRecording() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      toast.error("Không mở được micro — cho phép DFlow dùng micro, hoặc thu bằng điện thoại rồi bấm “📁 Chọn file ghi âm”.");
      return;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      if (timer.current) window.clearInterval(timer.current);
      timer.current = null;
      setRecording(false);
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      if (blob.size < 2000) { toast.warning("Chưa thu được gì — thử lại."); return; }
      setTake({ blob, name: `thu-am.${(rec.mimeType || "audio/webm").includes("ogg") ? "ogg" : "webm"}`,
                url: URL.createObjectURL(blob), from: "mic" });
    };
    recorder.current = rec;
    setTake(null);
    setElapsed(0);
    setRecording(true);
    rec.start();
    const started = Date.now();
    timer.current = window.setInterval(() => {
      const s = (Date.now() - started) / 1000;
      setElapsed(s);
      if (s >= RECORD_MAX_S && rec.state === "recording") rec.stop();
    }, 200);
  }
  function stopRecording() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }
  function pickFile(f: File | null | undefined) {
    if (!f) return;
    if (f.size > 30 * 1024 * 1024) { toast.warning("File quá lớn — chỉ cần khoảng 10 giây nói."); return; }
    setTake({ blob: f, name: f.name, url: URL.createObjectURL(f), from: "file" });
  }

  async function submit() {
    if (!take || busy) return;
    setBusy(true);
    try {
      const v = await createVoiceClone(take.blob, take.name, name.trim(), gender, consent);
      toast.success(`Đã nhân bản “${v.name}” (từ ${v.speech_s.toLocaleString("vi-VN")} giây tiếng nói) — bấm ▶ để nghe.`);
      setTake(null);
      setConsent(false);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function rename(v: VoiceClone) {
    const next = await askText("Tên mới của giọng", v.name);
    if (next === null || !next.trim() || next.trim() === v.name) return;
    try {
      await updateVoiceClone(v.uid, { name: next.trim() });
      await load();
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
  }
  async function changeGender(v: VoiceClone, g: CloneGender) {
    try {
      await updateVoiceClone(v.uid, { gender: g });
      await load();
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
  }
  async function remove(v: VoiceClone) {
    const ok = await askConfirm(`Xoá giọng “${v.name}”? Clip / video đã làm vẫn giữ nguyên tiếng; lần xuất sau của chúng phải chọn giọng khác.`,
      { ok: "Xoá giọng", danger: true });
    if (!ok) return;
    try {
      await deleteVoiceClone(v.uid);
      toast.success("Đã xoá giọng.");
      await load();
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
  }

  const canSubmit = !!take && !!name.trim() && consent && !busy && !recording && machine?.ok !== false;
  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Giọng nhân bản</span>
      </header>
      <div className="qt-home vc">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Thư viện</div>
            <h2 className="qt-card__title">🧬 Giọng nhân bản{items && <span className="vc__count"> · {items.length}</span>}</h2>
            <p className="qt-card__hint">Thu khoảng 10 giây giọng của bạn → tool học giọng → giọng đó đọc mọi lời thoại, lồng tiếng, bài
              đọc… Chạy trên máy, miễn phí (VieNeu). Chỉ lưu “dấu vân giọng”, không lưu file ghi âm.</p>
          </div>
        </div>

        {machine && !machine.ok && (
          <div className="vc__warn" role="status">
            <strong>Máy này chưa nhân bản giọng được:</strong> {machine.reason || "cần bộ cài lồng tiếng"}.
            <button type="button" className="qt-btn qt-btn--small" onClick={() => navigate("/settings")}>Mở Cài đặt → 🖥 Máy này</button>
          </div>
        )}

        <section className="qt-card vc__new" aria-label="Nhân bản giọng mới">
          <h3 className="vc__h">Tạo giọng mới</h3>
          <div className="vc__grid">
            <div className="vc__rec">
              <div className="qt-row">
                {recording ? (
                  <button type="button" className="qt-btn qt-btn--danger" onClick={stopRecording}>
                    ■ Dừng thu ({Math.floor(elapsed)}s / {RECORD_MAX_S}s)
                  </button>
                ) : (
                  <button type="button" className="qt-btn qt-btn--accent" onClick={() => void startRecording()} disabled={busy}>
                    🎙 {take?.from === "mic" ? "Thu lại" : "Thu bằng micro"}
                  </button>
                )}
                <button type="button" className="qt-btn" onClick={() => fileInput.current?.click()} disabled={busy || recording}>
                  📁 Chọn file ghi âm
                </button>
                <input ref={fileInput} type="file" hidden accept="audio/*,.m4a,.mp3,.wav,.ogg,.webm,.aac,.amr"
                       onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
              </div>
              {recording && (
                <div className="vc__meter" aria-live="polite">
                  <span className="vc__dot" /> Đang thu… đọc câu bên dưới bằng giọng tự nhiên
                  <span className="vc__bar"><span style={{ width: `${Math.min(100, (elapsed / RECORD_MAX_S) * 100)}%` }} /></span>
                </div>
              )}
              <blockquote className="vc__sample">Câu gợi ý để đọc: “{SAMPLE_LINE}”</blockquote>
              {take && !recording && (
                <div className="vc__take">
                  <span>{take.from === "mic" ? `🎙 Bản thu ${Math.round(elapsed)} giây` : `📁 ${take.name}`}</span>
                  <audio src={take.url} controls preload="metadata" />
                </div>
              )}
            </div>
            <div className="qt-form">
              <label className="qt-field">
                <span>Tên giọng</span>
                <input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="VD: Giọng của mình" />
              </label>
              <label className="qt-field">
                <span>Giọng nam hay nữ</span>
                <select value={gender} onChange={(e) => setGender(e.target.value as CloneGender)}>
                  {GENDERS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
                </select>
              </label>
              <label className="qt-check vc__consent">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>Đây là giọng của tôi, hoặc tôi được chủ giọng cho phép nhân bản và sử dụng. Tôi không dùng nó để giả mạo người khác.</span>
              </label>
              <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={!canSubmit} onClick={() => void submit()}>
                {busy ? "⏳ Đang học giọng… (10–60 giây)" : "🧬 Nhân bản giọng"}
              </button>
              {!take && <small className="vc__need">Thu âm hoặc chọn file ghi âm trước.</small>}
              {take && !consent && <small className="vc__need">Tick ô xác nhận ở trên để nhân bản.</small>}
            </div>
          </div>
          <details className="vc__tips">
            <summary>Mẹo thu để giọng giống nhất</summary>
            <ul>
              <li><strong>Khoảng 10 giây nói liền</strong> — tool chỉ dùng tối đa 8 giây tiếng nói; thu dài hơn không giúp gì thêm.</li>
              <li>Phòng yên tĩnh, không nhạc / TV, chỉ một người nói; micro cách miệng khoảng một gang tay.</li>
              <li>Nói đúng kiểu bạn muốn video đọc (review hào hứng thì thu giọng hào hứng) — tool học cả cách nói.</li>
              <li>Thu bằng điện thoại cũng được: chép file (m4a, mp3…) vào máy rồi bấm “📁 Chọn file ghi âm”.</li>
            </ul>
          </details>
        </section>

        {!items && <PageLoading text="Đang tải giọng đã nhân bản…" compact />}
        {items && items.length === 0 && (
          <PageEmpty icon="🧬" title="Chưa có giọng nhân bản nào" compact>
            Thu ~10 giây giọng của bạn ở trên — giọng đó sẽ có trong mọi ô chọn giọng (Lồng tiếng, Bước 4 / 5 của clip, Người mẫu…).
          </PageEmpty>
        )}
        {items && items.length > 0 && (
          <ul className="vc__list">
            {items.map((v) => (
              <li key={v.uid} className="qt-card vc__item">
                <div className="vc__itemhead">
                  <span className="vc__avatar" aria-hidden="true">🧬</span>
                  <div className="vc__meta">
                    <strong title={v.name}>{v.name}</strong>
                    <small>học từ {v.speech_s.toLocaleString("vi-VN")} giây tiếng nói
                      {v.created_at ? ` · ${new Date(v.created_at).toLocaleDateString("vi-VN")}` : ""}</small>
                  </div>
                  {dubVoice === v.voice && <span className="vc__badge">Giọng lồng tiếng mặc định</span>}
                </div>
                <div className="qt-row vc__actions">
                  <VoicePreview voice={v.voice} iconOnly={false} disabled={machine?.ok === false} />
                  {dubVoice !== v.voice && (
                    <button type="button" className="qt-btn qt-btn--small" onClick={() => { setDubVoice(v.voice); toast.success(`Lồng tiếng mới sẽ dùng giọng “${v.name}”.`); }}>
                      Dùng cho lồng tiếng
                    </button>
                  )}
                  <select className="vc__gender" value={v.gender} aria-label="Giọng nam hay nữ"
                          onChange={(e) => void changeGender(v, e.target.value as CloneGender)}>
                    {GENDERS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
                  </select>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void rename(v)}>✎ Đổi tên</button>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => void remove(v)}>🗑 Xoá</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
