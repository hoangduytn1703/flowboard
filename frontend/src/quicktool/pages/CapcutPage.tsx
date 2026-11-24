// ✂️ Edit auto CapCut (`/tools/capcut`): a dubbed video, a finished clip or the
// user's own video becomes a CapCut desktop project — subtitles in their own
// subtitle style, key words + zoom + a sound effect at the key moments (AI) —
// then the video exported from CapCut comes back onto its clip.
// Backend: routes/capcut.py, services/capcut_auto.py, services/capcut_draft.py.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import {
  capcutSrtUrl,
  chooseCapcutStyles,
  fetchCapcutLink,
  forgetCapcutProject,
  getCapcutJob,
  getCapcutSources,
  getCapcutStatus,
  learnCapcut,
  listCapcutProjects,
  returnCapcutVideo,
  startCapcutJob,
  uploadCapcutVideo,
} from "../../api/capcut";
import type {
  CapcutJob,
  CapcutJobOptions,
  CapcutProject,
  CapcutSourceKind,
  CapcutSources,
  CapcutStatus,
  CapcutStyles,
  CapcutSubtitles,
  CapcutUpload,
} from "../../api/capcut";
import { DEFAULT_VOICE } from "../../api/client";
import { toast } from "../../store/toast";
import { useSettingsStore } from "../../store/settings";
import { PageLoading } from "../PageState";
import { VoiceField } from "../VoiceField";
import "../quicktool.css";
import "../capcut.css";

type Source = { kind: CapcutSourceKind; id: string; title: string };

function fmtDur(s: number | null | undefined): string {
  if (!s || s <= 0) return "—";
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return m ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
}

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const ROLE_LABEL: Record<"subtitle" | "emphasis" | "title", string> = {
  subtitle: "Phụ đề",
  emphasis: "Chữ nhấn mạnh",
  title: "Tiêu đề / chữ to",
};

// ── requirements ─────────────────────────────────────────────────────────

function Check({ ok, warn, title, children }: { ok: boolean; warn?: boolean; title: string; children?: React.ReactNode }) {
  const mark = ok ? "✓" : warn ? "!" : "✕";
  return (
    <li className={`cc-check cc-check--${ok ? "ok" : warn ? "warn" : "bad"}`}>
      <span className="cc-check__mark">{mark}</span>
      <div>
        <strong>{title}</strong>
        {children && <p>{children}</p>}
      </div>
    </li>
  );
}

function Requirements({ st, onRefresh, refreshing }: { st: CapcutStatus; onRefresh: () => void; refreshing: boolean }) {
  const styles = st.styles;
  return (
    <section className="qt-card">
      <div className="qt-card__head">
        <div>
          <span className="qt-card__eyebrow">Yêu cầu</span>
          <h2 className="qt-card__title">Máy này có đủ chưa?</h2>
        </div>
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Đang kiểm tra…" : "↻ Kiểm tra lại"}
        </button>
      </div>
      <ul className="cc-checks">
        <Check ok={st.windows} title="Máy Windows">
          {st.windows ? "CapCut bản máy tính trên Windows." : "Chỉ chạy trên Windows (CapCut bản máy tính lưu dự án theo cách của Windows)."}
        </Check>
        <Check ok={st.capcut_installed} title="CapCut bản máy tính">
          {st.capcut_installed
            ? <>Đã cài · {st.capcut_projects} dự án · <code>{st.capcut_root}</code></>
            : "Chưa thấy — tải CapCut tại capcut.com, cài, mở lên một lần rồi bấm Kiểm tra lại."}
        </Check>
        <Check ok={!st.capcut_running} warn title={st.capcut_running ? "CapCut đang mở" : "CapCut đang đóng"}>
          {st.capcut_running
            ? "Đóng hẳn CapCut (cả biểu tượng ở khay góc phải) trước khi Học hoặc Tạo dự án — CapCut đang mở sẽ ghi đè lên dự án mới khi tắt."
            : "Tốt — tool chỉ ghi dự án khi CapCut đang đóng."}
        </Check>
        <Check ok={!!styles && styles.texts.length > 0 && styles.has_video} title="Kiểu chữ & âm thanh của bạn">
          {styles && styles.texts.length > 0
            ? <>{styles.texts.length} kiểu chữ · {styles.sounds.length} hiệu ứng âm thanh{!styles.has_video && " · thiếu mẫu video (kéo một video vào dự án rồi học lại)"}</>
            : "Chưa học — làm bước ① bên dưới."}
        </Check>
        <Check ok={st.ai.ok} warn title="AI chọn chữ quan trọng">
          {st.ai.ok
            ? <>{st.ai.provider} — giống AI viết bài, viết kịch bản.</>
            : <>{st.ai.reason} Không có AI thì tool tự chọn theo số / câu cảm thán.</>}
        </Check>
        <Check ok={st.whisper} warn title="Whisper nghe lời (bộ cài lồng tiếng)">
          {st.whisper
            ? "Dùng cho clip đã ghép và video của bạn (để biết lúc nào nói chữ gì)."
            : <>Chưa có — video lồng tiếng vẫn làm được (đã có lời); clip đã ghép / video của bạn chỉ vào CapCut, không có phụ đề.
              {" "}<a className="qt-link" href="/tools/dub">Cài bộ cài lồng tiếng →</a></>}
        </Check>
        <Check ok={st.ffmpeg} title="ffmpeg">{st.ffmpeg ? "Có." : "Thiếu ffmpeg trên PATH."}</Check>
      </ul>
    </section>
  );
}

function Guide({ firstTime }: { firstTime: boolean }) {
  // open by itself until the styles are learned: the first visit is when the steps matter
  return (
    <details className="qt-card cc-guide" open={firstTime || undefined}>
      <summary>
        <span className="qt-card__eyebrow">Hướng dẫn</span>
        <span className="qt-card__title">Dùng thế nào?</span>
      </summary>
      <ol className="cc-steps">
        <li>
          <strong>Một lần đầu — dạy tool kiểu chữ của bạn.</strong> Mở CapCut, tạo một dự án bất kỳ, kéo vào một video.
          Thêm 3 dòng chữ và gõ đúng nội dung <code>Phụ đề</code>, <code>Nhấn mạnh</code>, <code>Tiêu đề</code> — chỉnh font,
          màu, viền, vị trí từng dòng theo ý (tool làm y như vậy). Thêm 3–5 <em>hiệu ứng âm thanh</em> bạn hay dùng. Đóng hẳn CapCut,
          rồi bấm <strong>"Học từ CapCut"</strong> ở bước ①.
        </li>
        <li>
          <strong>Chọn video</strong> ở bước ②: dán link / chọn file một video mới, hoặc lấy video đã lồng tiếng, clip đã ghép. Video mới (nước
          ngoài) có thể <strong>lồng tiếng Việt trước</strong> ở bước ③ — không bắt buộc, y như menu “Lồng tiếng video” nhưng phần chỉnh làm trong CapCut.
        </li>
        <li>
          <strong>Chọn kiểu dựng</strong> (phụ đề kiểu TikTok ≤ 4 chữ / cả câu / không, chữ nhấn mạnh + zoom + âm thanh ở chữ quan
          trọng, cắt khoảng lặng) rồi bấm <strong>"✂️ Tạo dự án CapCut"</strong> — CapCut phải đang đóng.
        </li>
        <li><strong>Mở CapCut</strong>: dự án mới nằm đầu danh sách. Xem lại, sửa tay chỗ chưa ưng (chữ, vị trí, zoom, âm thanh) rồi <em>Xuất</em>.</li>
        <li>
          <strong>Đưa bản CapCut về clip</strong> ở bước ④: thả video vừa xuất vào dự án đó — clip sẽ dùng bản này khi tải về,
          lên lịch, đăng Facebook.
        </li>
      </ol>
      <div className="cc-notes">
        <strong>Lưu ý</strong>
        <ul>
          <li>Chỉ CapCut bản máy tính trên Windows. CapCut cập nhật lớn có thể đổi cách lưu dự án — khi đó tool cần sửa lại.</li>
          <li>Tool chỉ <em>thêm</em> dự án mới, không sửa dự án có sẵn của bạn. Mỗi lần tạo có lưu bản sao danh sách dự án (<code>root_meta_info.json.flowboard.bak</code>).</li>
          <li>Video lồng tiếng: khung, vùng làm mờ, nhân vật được in sẵn vào video nền; giọng đọc, nhạc nền, phụ đề là các track riêng để sửa.</li>
          <li>Whisper có thể nghe sai tên riêng / chữ tiếng Anh; AI chọn chữ quan trọng không phải lúc nào cũng trúng — xem lại trong CapCut.</li>
          <li>Font, âm thanh lấy từ CapCut của chính bạn — bạn tự chịu trách nhiệm bản quyền của chúng.</li>
        </ul>
      </div>
    </details>
  );
}

// ── ① styles ─────────────────────────────────────────────────────────────

function StylesCard({ styles, canLearn, learning, onLearn, onChoose }: {
  styles: CapcutStyles | null;
  canLearn: boolean;
  learning: boolean;
  onLearn: () => void;
  onChoose: (role: "subtitle" | "emphasis" | "title", id: string) => void;
}) {
  return (
    <section className="qt-card">
      <div className="qt-card__head">
        <div>
          <span className="qt-card__eyebrow">Bước ① · Một lần đầu</span>
          <h2 className="qt-card__title">Kiểu chữ & âm thanh của bạn</h2>
        </div>
        <button type="button" className={`qt-btn qt-btn--small${styles ? " qt-btn--ghost" : " qt-btn--accent"}`}
                onClick={onLearn} disabled={!canLearn || learning}>
          {learning ? "Đang học…" : styles ? "🔄 Học lại từ CapCut" : "📥 Học từ CapCut"}
        </button>
      </div>
      {!styles ? (
        <p className="qt-card__hint">
          Tool đọc các dòng chữ và hiệu ứng âm thanh bạn đã dùng trong CapCut để làm theo đúng gu của bạn.
          Xem <strong>Hướng dẫn</strong> bước 1 nếu CapCut chưa có chữ / âm thanh nào.
        </p>
      ) : (
        <>
          <p className="qt-card__hint">
            Học lúc {fmtWhen(styles.learned_at)} từ {styles.scanned} dòng thời gian. Thêm kiểu chữ / âm thanh mới trong CapCut rồi bấm Học lại.
          </p>
          <div className="cc-roles">
            {(["subtitle", "emphasis", "title"] as const).map((role) => (
              <label key={role} className="qt-field cc-role">
                <span>{ROLE_LABEL[role]}</span>
                <select value={styles.aliases[role] ?? ""} onChange={(e) => onChoose(role, e.target.value)}>
                  <option value="">— Không dùng —</option>
                  {styles.texts.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.examples[0] ? `“${t.examples[0]}” — ` : ""}{t.label}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <div className="cc-sounds">
            <span>Âm thanh ({styles.sounds.length}):</span>
            {styles.sounds.length === 0 && <em>chưa có — thêm vài hiệu ứng âm thanh trong CapCut rồi học lại</em>}
            {styles.sounds.map((s) => <span key={s.id} className="qt-chip" title={`${s.duration}s`}>🔊 {s.label}</span>)}
          </div>
        </>
      )}
    </section>
  );
}

// ── ② source ─────────────────────────────────────────────────────────────

function SourceCard({ sources, source, onPick, uploaded, onUpload, uploading, onLink }: {
  sources: CapcutSources | null;
  source: Source | null;
  onPick: (s: Source) => void;
  uploaded: CapcutUpload | null;
  onUpload: (f: File) => void;
  uploading: boolean;
  onLink: (url: string) => void;
}) {
  const [tab, setTab] = useState<CapcutSourceKind>("upload");
  const [drag, setDrag] = useState(false);
  const [link, setLink] = useState("");
  const dubs = sources?.dubs ?? [];
  const clips = sources?.clips ?? [];
  return (
    <section className="qt-card">
      <span className="qt-card__eyebrow">Bước ② · Video</span>
      <h2 className="qt-card__title">Chọn video đưa vào CapCut</h2>
      <div className="cc-tabs" role="tablist">
        <button type="button" role="tab" className={`cc-tab${tab === "upload" ? " cc-tab--on" : ""}`} onClick={() => setTab("upload")}>
          🆕 Video mới (link / file)
        </button>
        <button type="button" role="tab" className={`cc-tab${tab === "dub" ? " cc-tab--on" : ""}`} onClick={() => setTab("dub")}>
          🎙 Đã lồng tiếng <span>{dubs.length}</span>
        </button>
        <button type="button" role="tab" className={`cc-tab${tab === "clip" ? " cc-tab--on" : ""}`} onClick={() => setTab("clip")}>
          🎬 Clip đã ghép <span>{clips.length}</span>
        </button>
      </div>
      {!sources && tab !== "upload" ? (
        <PageLoading compact text="Đang tải danh sách…" />
      ) : tab === "dub" ? (
        dubs.length === 0 ? <p className="qt-card__hint">Chưa có video lồng tiếng nào — làm ở “🎙 Lồng tiếng video”.</p> : (
          <ul className="cc-list">
            {dubs.map((d) => {
              const on = source?.kind === "dub" && source.id === d.id;
              return (
                <li key={d.id}>
                  <button type="button" className={`cc-item${on ? " cc-item--on" : ""}`} disabled={!d.has_voice}
                          onClick={() => onPick({ kind: "dub", id: d.id, title: d.title })}
                          title={d.has_voice ? "" : "Chưa có giọng đọc trên máy — mở ở trang Lồng tiếng, Xuất lại video"}>
                    <span className="cc-item__radio" />
                    <span className="cc-item__title">{d.title}</span>
                    <span className="cc-item__meta">
                      {fmtDur(d.duration)} · {d.lines} câu{d.width ? ` · ${d.width}×${d.height}` : ""} · {fmtWhen(d.started_at)}
                      {!d.has_voice && " · chưa có giọng trên máy"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )
      ) : tab === "clip" ? (
        clips.length === 0 ? <p className="qt-card__hint">Chưa có clip nào ghép xong (Bước 5 · Ghép video).</p> : (
          <>
            <p className="qt-card__hint">Video cuối của clip. Whisper nghe lời để biết lúc nào nói chữ gì — nếu video đã in phụ đề, chọn “Không phụ đề” ở bước ③.</p>
            <ul className="cc-list">
              {clips.map((c) => {
                const on = source?.kind === "clip" && source.id === String(c.id);
                return (
                  <li key={c.id}>
                    <button type="button" className={`cc-item${on ? " cc-item--on" : ""}`}
                            onClick={() => onPick({ kind: "clip", id: String(c.id), title: c.title })}>
                      <span className="cc-item__radio" />
                      <span className="cc-item__title">{c.title}</span>
                      <span className="cc-item__meta">Clip #{c.id}{c.capcut ? ` · đang dùng bản CapCut “${c.capcut.project}”` : ""}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        )
      ) : (
        <>
          <form className="cc-link" onSubmit={(e) => { e.preventDefault(); if (link.trim()) onLink(link.trim()); }}>
            <input value={link} disabled={uploading} placeholder="Dán link TikTok / Douyin / YouTube / Facebook… (dán cả đoạn chia sẻ cũng được)"
                   onChange={(e) => setLink(e.target.value)} />
            <button type="submit" className="qt-btn" disabled={uploading || !link.trim()}>⬇ Lấy video</button>
          </form>
          <label className={`cc-drop${drag ? " cc-drop--over" : ""}`}
                 onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                 onDragLeave={() => setDrag(false)}
                 onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) onUpload(f); }}>
            <input type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv" disabled={uploading}
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ""; }} />
            {uploading ? <><span className="qt-spinner" /> Đang lấy video…</> : (
              <><strong>…hoặc kéo thả file video vào đây</strong><span>bấm để chọn (mp4 / mov / webm, ≤ 2 GB) — chỉ nằm trên máy này</span></>
            )}
          </label>
          {uploaded && (
            <button type="button" className={`cc-item${source?.kind === "upload" && source.id === uploaded.media_id ? " cc-item--on" : ""}`}
                    onClick={() => onPick({ kind: "upload", id: uploaded.media_id, title: uploaded.name })}>
              <span className="cc-item__radio" />
              <span className="cc-item__title">{uploaded.name}</span>
              <span className="cc-item__meta">{fmtDur(uploaded.duration)} · {uploaded.width}×{uploaded.height}</span>
            </button>
          )}
        </>
      )}
    </section>
  );
}

// ── ③ options ────────────────────────────────────────────────────────────

const SUB_OPTIONS: { key: CapcutSubtitles; label: string; hint: string }[] = [
  { key: "tiktok", label: "Kiểu TikTok", hint: "≤ 4 chữ một dòng, đổi dòng theo nhịp nói" },
  { key: "line", label: "Cả câu", hint: "mỗi câu một dòng (câu dài tách đôi)" },
  { key: "off", label: "Không phụ đề", hint: "video đã có phụ đề in sẵn" },
];

function OptionsCard({ source, opts, setOpts, canCreate, why, creating, onCreate, dubbing, subtitleOff, emphasisOff }: {
  source: Source | null;
  opts: CapcutJobOptions;
  setOpts: (o: CapcutJobOptions) => void;
  canCreate: boolean;
  why: string | null;
  creating: boolean;
  onCreate: () => void;
  dubbing: boolean;
  subtitleOff: boolean;
  emphasisOff: boolean;
}) {
  const set = (patch: Partial<CapcutJobOptions>) => setOpts({ ...opts, ...patch });
  return (
    <section className="qt-card">
      <span className="qt-card__eyebrow">{source?.kind === "upload" ? "Bước ④" : "Bước ③"} · Kiểu dựng</span>
      <h2 className="qt-card__title">Tool làm sẵn những gì?</h2>
      <label className="qt-field">
        <span>Tên dự án trong CapCut</span>
        <input value={opts.name ?? ""} maxLength={60} placeholder={source?.title || "Tên dự án"}
               onChange={(e) => set({ name: e.target.value })} />
      </label>
      <div className="cc-field">
        <span>Phụ đề{subtitleOff && <small className="cc-off"> — kiểu chữ phụ đề đang để “Không dùng” ở bước ①, sẽ không có phụ đề</small>}</span>
        <div className={`cc-radios${subtitleOff ? " cc-radios--off" : ""}`}>
          {SUB_OPTIONS.map((o) => (
            <label key={o.key} className={`cc-radio${opts.subtitles === o.key ? " cc-radio--on" : ""}`}>
              <input type="radio" name="cc-subs" checked={opts.subtitles === o.key} onChange={() => set({ subtitles: o.key })} />
              <strong>{o.label}</strong>
              <small>{o.hint}</small>
            </label>
          ))}
        </div>
      </div>
      {opts.subtitles !== "off" && !subtitleOff && (
        <label className="cc-toggle">
          <input type="checkbox" checked={!!opts.srt_only} onChange={(e) => set({ srt_only: e.target.checked })} />
          <span>📄 <strong>Không chèn chữ phụ đề vào dự án — chỉ tạo file .srt</strong>
            <small> (trong CapCut: Captions → Import file đó → thành phụ đề thật, kéo 1 câu là cả loạt đi theo)</small></span>
        </label>
      )}
      {source?.kind === "dub" && opts.subtitles !== "off" && !opts.srt_only && (
        <label className="cc-toggle">
          <input type="checkbox" checked={opts.sub_position === "video"}
                 onChange={(e) => set({ sub_position: e.target.checked ? "video" : "style" })} />
          <span>Đặt phụ đề đúng chỗ bạn đã chỉnh ở trang Lồng tiếng <small>(bỏ tick = theo vị trí dòng “Phụ đề” mẫu trong CapCut)</small></span>
        </label>
      )}
      <label className="cc-toggle">
        <input type="checkbox" checked={opts.highlights} onChange={(e) => set({ highlights: e.target.checked })} />
        <span>✨ <strong>{emphasisOff ? "Nhấn ở chữ quan trọng" : "Chữ nhấn mạnh ở chữ quan trọng"}</strong> — AI chọn khoảng 1 chỗ mỗi 12 giây (giá, con số, lợi ích…)
          {emphasisOff && <small> · chữ nhấn mạnh đang để “Không dùng” ở bước ① — chỉ zoom + âm thanh</small>}</span>
      </label>
      {opts.highlights && (
        <div className="cc-sub">
          <label className="cc-toggle">
            <input type="checkbox" checked={opts.zoom} onChange={(e) => set({ zoom: e.target.checked })} />
            <span>🔍 Zoom vào nhẹ (1,12–1,18 lần) đúng lúc đó</span>
          </label>
          <label className="cc-toggle">
            <input type="checkbox" checked={opts.sfx} onChange={(e) => set({ sfx: e.target.checked })} />
            <span>🔊 Một tiếng hiệu ứng nhỏ (lấy lần lượt trong CapCut của bạn)</span>
          </label>
        </div>
      )}
      {source && source.kind !== "dub" && !dubbing && (
        <label className="cc-toggle">
          <input type="checkbox" checked={opts.cut_silence} onChange={(e) => set({ cut_silence: e.target.checked })} />
          <span>✂ <strong>Cắt khoảng lặng</strong> — bỏ các đoạn ngừng dài hơn 0,45 s (hợp với video bạn tự quay)</span>
        </label>
      )}
      <div className="cc-go">
        <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={!canCreate || creating} onClick={onCreate}>
          {creating ? "Đang làm…" : dubbing ? "🎙 Lồng tiếng rồi tạo dự án CapCut" : "✂️ Tạo dự án CapCut"}
        </button>
        {why && <span className="cc-why">{why}</span>}
        {!why && dubbing && <span className="cc-note">Lồng tiếng chạy như menu “Lồng tiếng video” (vài phút), xong tự tạo dự án. Đóng CapCut trước khi xong.</span>}
      </div>
    </section>
  );
}

// ── ③ dub first (optional) ───────────────────────────────────────────────

function DubCard({ st, on, setOn, voice, setVoice, keepBgm, setKeepBgm }: {
  st: CapcutStatus;
  on: boolean;
  setOn: (v: boolean) => void;
  voice: string;
  setVoice: (v: string) => void;
  keepBgm: boolean;
  setKeepBgm: (v: boolean) => void;
}) {
  return (
    <section className={`qt-card cc-dub${on ? " cc-dub--on" : ""}`}>
      <span className="qt-card__eyebrow">Bước ③ · Không bắt buộc</span>
      <label className="cc-toggle cc-dub__switch">
        <input type="checkbox" checked={on} disabled={!st.dub} onChange={(e) => setOn(e.target.checked)} />
        <span>
          <strong>🎙 Lồng tiếng sang tiếng Việt trước</strong> — y như menu “Lồng tiếng video”: nghe lời gốc, dịch, đọc giọng Việt, bỏ tiếng gốc.
          Phần chỉnh sửa làm trong CapCut: giọng, nhạc nền, phụ đề là các track riêng.
          {!st.dub && <small className="cc-off"> Máy này chưa lồng tiếng được: {st.dub_reason}</small>}
        </span>
      </label>
      {!on && <p className="qt-card__hint">Không tick: video vào CapCut như cũ (có thể không cần phụ đề — chọn “Không phụ đề” ở bước dưới).</p>}
      {on && (
        <div className="cc-dub__opts">
          <VoiceField value={voice} onChange={setVoice} sampleText="Các bạn ơi, hôm nay mình sẽ cho các bạn xem một thứ cực kỳ thú vị." />
          <label className="cc-toggle">
            <input type="checkbox" checked={keepBgm && st.dub_separate} disabled={!st.dub_separate} onChange={(e) => setKeepBgm(e.target.checked)} />
            <span>Giữ nhạc nền gốc (tách giọng nói ra){!st.dub_separate && <small> — máy chưa có bộ tách nhạc</small>}</span>
          </label>
        </div>
      )}
    </section>
  );
}

// ── job progress / result ───────────────────────────────────────────────

function JobCard({ job, onOpenClip }: { job: CapcutJob; onOpenClip: (id: number) => void }) {
  const running = job.status === "queued" || job.status === "running";
  const r = job.result;
  return (
    <section className={`qt-card cc-job cc-job--${job.status}`}>
      {running ? (
        <>
          <strong className="cc-job__phase"><span className="qt-spinner" /> {job.phase}</strong>
          <div className="cc-bar"><span style={{ width: `${Math.max(4, job.progress)}%` }} /></div>
        </>
      ) : job.status === "error" ? (
        <>
          <strong className="cc-job__phase">✕ Không tạo được dự án</strong>
          <p className="qt-card__hint">{job.error}</p>
        </>
      ) : r && (
        <>
          <strong className="cc-job__phase">✓ Đã tạo dự án “{r.name}”</strong>
          <p className="qt-card__hint">
            Mở <strong>CapCut</strong> — dự án nằm đầu danh sách. Dài {fmtDur(r.duration_s)} · {r.subtitles} dòng phụ đề ·
            {" "}{r.counts.zoom} zoom · {r.counts.sfx} tiếng hiệu ứng{r.counts.audio ? ` · ${r.counts.audio} track giọng / nhạc` : ""}.
          </p>
          {r.points.length > 0 && (
            <div className="cc-points">
              <span>Chữ nhấn mạnh:</span>
              {r.points.map((p) => <span key={p.at} className="qt-chip">{fmtDur(p.at)} · {p.words}</span>)}
            </div>
          )}
          <div className="cc-job__acts">
            {(r.srt_lines ?? 0) > 0 && (
              <a className="qt-btn qt-btn--small" href={capcutSrtUrl(r.project_id)} download>⬇ Phụ đề .srt ({r.srt_lines} dòng)</a>
            )}
            {r.board_id && (
              <button type="button" className="qt-link" onClick={() => onOpenClip(r.board_id!)}>Mở clip #{r.board_id} →</button>
            )}
          </div>
          {(r.srt_lines ?? 0) > 0 && (
            <p className="qt-card__hint">
              Muốn kéo 1 câu mà cả loạt đi theo: trong CapCut xoá track chữ phụ đề (nếu có), vào <strong>Captions → Import</strong> chọn file .srt này —
              CapCut biến nó thành phụ đề thật.
            </p>
          )}
        </>
      )}
      {job.warnings.length > 0 && (
        <ul className="cc-warn">{job.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}
    </section>
  );
}

// ── ④ projects ───────────────────────────────────────────────────────────

function ProjectsCard({ projects, onReturn, returning, onForget, onOpenClip }: {
  projects: CapcutProject[] | null;
  onReturn: (p: CapcutProject, f: File) => void;
  returning: string | null;
  onForget: (p: CapcutProject, removeFolder: boolean) => void;
  onOpenClip: (id: number) => void;
}) {
  const [asking, setAsking] = useState<string | null>(null);
  const [dragOn, setDragOn] = useState<string | null>(null);
  return (
    <section className="qt-card">
      <span className="qt-card__eyebrow">Bước ④ · Sau khi xuất trong CapCut</span>
      <h2 className="qt-card__title">Dự án đã tạo</h2>
      <p className="qt-card__hint">
        Xuất video trong CapCut xong, <strong>thả file đó vào đúng dự án</strong> bên dưới: clip dùng bản này để tải về, lên lịch, đăng Facebook
        (bản cũ vẫn được giữ lại).
      </p>
      {!projects ? <PageLoading compact text="Đang tải…" /> : projects.length === 0 ? (
        <p className="qt-card__hint">Chưa có dự án nào.</p>
      ) : (
        <ul className="cc-projects">
          {projects.map((p) => (
            <li key={p.id} className={`cc-project${dragOn === p.id ? " cc-project--over" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setDragOn(p.id); }}
                onDragLeave={() => setDragOn(null)}
                onDrop={(e) => { e.preventDefault(); setDragOn(null); const f = e.dataTransfer.files?.[0]; if (f) onReturn(p, f); }}>
              <div className="cc-project__main">
                <strong>{p.name}</strong>
                <span className="cc-item__meta">
                  {p.source?.kind === "dub" ? "🎙 Lồng tiếng" : p.source?.kind === "clip" ? "🎬 Clip" : "⬆ Video của bạn"}
                  {p.source?.title && p.source.title !== p.name ? ` · ${p.source.title}` : ""} · {fmtDur(p.duration_s)} ·
                  {" "}{p.subtitles ?? 0} phụ đề · {p.points ?? 0} chữ nhấn mạnh · {fmtWhen(p.created_at)}
                  {!p.exists && " · đã xoá khỏi CapCut"}
                </span>
                {p.returned && (
                  <span className="cc-returned">✓ Đã đưa bản CapCut về clip lúc {fmtWhen(p.returned.at)} ({fmtDur(p.returned.duration_s)})</span>
                )}
              </div>
              <div className="cc-project__acts">
                {((p.subtitles ?? 0) > 0 || (p.srt_lines ?? 0) > 0) && (
                  <a className="qt-btn qt-btn--small qt-btn--ghost" href={capcutSrtUrl(p.id)} download
                     title="Phụ đề của dự án (lấy từ CapCut, có cả chữ bạn đã sửa) — CapCut: Captions → Import">⬇ .srt</a>
                )}
                {p.board_id && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => onOpenClip(p.board_id!)}>Mở clip</button>
                )}
                <label className={`qt-btn qt-btn--small${p.returned ? " qt-btn--ghost" : ""}`}>
                  {returning === p.id ? "Đang nhận…" : p.returned ? "⬆ Thay bản khác" : "⬆ Đưa video đã xuất về"}
                  <input type="file" hidden accept="video/mp4,video/quicktime,.mp4,.mov" disabled={returning !== null}
                         onChange={(e) => { const f = e.target.files?.[0]; if (f) onReturn(p, f); e.target.value = ""; }} />
                </label>
                {asking === p.id ? (
                  <span className="cc-ask">
                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => { setAsking(null); onForget(p, false); }}>
                      Bỏ khỏi danh sách
                    </button>
                    {p.exists && (
                      <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => { setAsking(null); onForget(p, true); }}>
                        Xoá cả dự án trong CapCut
                      </button>
                    )}
                    <button type="button" className="qt-link" onClick={() => setAsking(null)}>Huỷ</button>
                  </span>
                ) : (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Xoá" onClick={() => setAsking(p.id)}>🗑</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── the page ─────────────────────────────────────────────────────────────

const DEFAULT_OPTS: CapcutJobOptions = {
  name: "", subtitles: "tiktok", highlights: true, zoom: true, sfx: true, cut_silence: false, sub_position: "video",
};

export function CapcutPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [st, setSt] = useState<CapcutStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [sources, setSources] = useState<CapcutSources | null>(null);
  const [projects, setProjects] = useState<CapcutProject[] | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [uploaded, setUploaded] = useState<CapcutUpload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [opts, setOpts] = useState<CapcutJobOptions>(DEFAULT_OPTS);
  const [dubOn, setDubOn] = useState(false);
  // the dubbing voice picked last (same default as the dub page — account pref)
  const voice = useSettingsStore((s) => s.dubVoice) || DEFAULT_VOICE;
  const setVoice = useSettingsStore((s) => s.setDubVoice);
  const [keepBgm, setKeepBgm] = useState(true);
  const [learning, setLearning] = useState(false);
  const [job, setJob] = useState<CapcutJob | null>(null);
  const [returning, setReturning] = useState<string | null>(null);
  const jobId = params.get("job");
  const announced = useRef<string | null>(null);

  useEffect(() => {
    const prev = document.title;
    document.title = "Edit auto CapCut · DFlow";
    return () => { document.title = prev; };
  }, []);

  const refreshStatus = useCallback(async (manual = false) => {
    if (manual) setChecking(true);
    try {
      setSt(await getCapcutStatus());
    } catch (e) {
      if (manual) toast.error(`Không kiểm tra được: ${e instanceof Error ? e.message : e}`);
    } finally {
      if (manual) setChecking(false);
    }
  }, []);
  const refreshLists = useCallback(() => {
    getCapcutSources().then(setSources).catch(() => setSources({ dubs: [], clips: [] }));
    listCapcutProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    void refreshStatus();
    refreshLists();
    const t = window.setInterval(() => { if (!document.hidden) void refreshStatus(); }, 8000);
    return () => window.clearInterval(t);
  }, [refreshStatus, refreshLists]);

  // a job (this page started it, or the "đang chạy" badge linked here)
  useEffect(() => {
    if (!jobId) return;
    let live = true;
    let timer = 0;
    const tick = async () => {
      try {
        const j = await getCapcutJob(jobId);
        if (!live) return;
        setJob(j);
        if (j.status === "queued" || j.status === "running") {
          timer = window.setTimeout(tick, 1200);
        } else if (announced.current !== j.id) {
          announced.current = j.id;
          if (j.status === "done") toast.success(`Đã tạo dự án “${j.result?.name}” — mở CapCut để xem`);
          refreshLists();
        }
      } catch {
        if (live) setJob(null);
      }
    };
    void tick();
    return () => { live = false; window.clearTimeout(timer); };
  }, [jobId, refreshLists]);

  const pick = (s: Source) => {
    if (s.kind !== "upload") setDubOn(false);
    setSource(s);
    setOpts((o) => ({ ...o, name: s.title, cut_silence: s.kind === "upload" ? true : s.kind === "dub" ? false : o.cut_silence }));
  };

  const learn = async () => {
    setLearning(true);
    try {
      const styles = await learnCapcut();
      toast.success(`Đã học ${styles.texts.length} kiểu chữ và ${styles.sounds.length} hiệu ứng âm thanh`);
      await refreshStatus();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLearning(false);
    }
  };

  const choose = async (role: "subtitle" | "emphasis" | "title", id: string) => {
    try {
      const styles = await chooseCapcutStyles({ [role]: id });
      setSt((s) => (s ? { ...s, styles } : s));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const upload = async (f: File) => {
    setUploading(true);
    try {
      const up = await uploadCapcutVideo(f);
      setUploaded(up);
      pick({ kind: "upload", id: up.media_id, title: up.name });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  const fromLink = async (url: string) => {
    setUploading(true);
    try {
      const up = await fetchCapcutLink(url);
      setUploaded(up);
      pick({ kind: "upload", id: up.media_id, title: up.name });
      toast.success(`Đã lấy video “${up.name}” (${fmtDur(up.duration)})`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  const running = job?.status === "queued" || job?.status === "running";
  const dubbing = dubOn && source?.kind === "upload";
  const why = useMemo(() => {
    if (!st) return "Đang kiểm tra máy…";
    if (!st.windows) return "Chỉ chạy trên Windows.";
    if (!st.capcut_installed) return "Chưa thấy CapCut bản máy tính.";
    if (!st.styles || st.styles.texts.length === 0) return "Làm bước ① trước: Học từ CapCut.";
    if (!st.styles.has_video) return "Kéo một video vào một dự án CapCut rồi học lại (tool cần mẫu video của CapCut bạn).";
    if (!source) return "Chọn một video ở bước ②.";
    if (dubbing && !st.dub) return st.dub_reason || "Máy này chưa lồng tiếng được.";
    if (st.capcut_running && !dubbing) return "Đóng hẳn CapCut trước khi tạo.";
    if (running) return "Đang tạo dự án…";
    return null;
  }, [st, source, running, dubbing]);

  const create = async () => {
    if (!source) return;
    try {
      const options = { ...opts, name: (opts.name || source.title || "").trim() || undefined };
      const j = dubbing
        ? await startCapcutJob({ kind: "dub_new", id: "", title: source.title, media_id: source.id },
                               { ...options, cut_silence: false }, { source_media_id: source.id, voice, keep_bgm: keepBgm })
        : await startCapcutJob({ kind: source.kind, id: source.id, title: source.title }, options);
      setJob(j);
      announced.current = null;
      setParams({ job: j.id }, { replace: true });
      announceRunning();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const giveBack = async (p: CapcutProject, f: File) => {
    setReturning(p.id);
    try {
      const res = await returnCapcutVideo(p.id, f);
      toast.success(`Clip #${res.board_id} giờ dùng bản CapCut “${p.name}”`);
      refreshLists();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setReturning(null);
    }
  };

  const forget = async (p: CapcutProject, removeFolder: boolean) => {
    try {
      await forgetCapcutProject(p.id, removeFolder);
      toast.success(removeFolder ? `Đã xoá dự án “${p.name}” khỏi CapCut` : `Đã bỏ “${p.name}” khỏi danh sách`);
      refreshLists();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const openClip = (id: number) => navigate(`/clips/${id}/export`);

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">✂️ Edit auto CapCut</span>
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate("/clips")}>← Clip của tôi</button>
      </header>
      <div className="qt-home cc-page">
        <p className="cc-lead">
          Biến video làm ở DFlow (hoặc video bạn tự quay) thành <strong>một dự án CapCut</strong>: phụ đề theo kiểu chữ của bạn,
          chữ nhấn mạnh + zoom + âm thanh ở chữ quan trọng — mở CapCut là chỉnh tiếp, xuất xong đưa về clip để đăng.
        </p>
        {!st ? <PageLoading text="Đang kiểm tra máy…" /> : (
          <div className="cc-grid">
            <div className="cc-col">
              <StylesCard styles={st.styles} canLearn={st.capcut_installed && !st.capcut_running} learning={learning}
                          onLearn={() => void learn()} onChoose={(r, id) => void choose(r, id)} />
              <SourceCard sources={sources} source={source} onPick={pick} uploaded={uploaded}
                          onUpload={(f) => void upload(f)} uploading={uploading} onLink={(u) => void fromLink(u)} />
              {source?.kind === "upload" && (
                <DubCard st={st} on={dubOn} setOn={setDubOn} voice={voice} setVoice={setVoice} keepBgm={keepBgm} setKeepBgm={setKeepBgm} />
              )}
              <OptionsCard source={source} opts={opts} setOpts={setOpts} canCreate={!why} why={why}
                           creating={running} onCreate={() => void create()} dubbing={dubbing}
                           subtitleOff={st.styles?.aliases.subtitle === ""} emphasisOff={st.styles?.aliases.emphasis === ""} />
              {job && <JobCard job={job} onOpenClip={openClip} />}
              <ProjectsCard projects={projects} onReturn={(p, f) => void giveBack(p, f)} returning={returning}
                            onForget={(p, rm) => void forget(p, rm)} onOpenClip={openClip} />
            </div>
            <aside className="cc-col cc-col--side">
              <Requirements st={st} onRefresh={() => void refreshStatus(true)} refreshing={checking} />
              <Guide firstTime={!st.styles || st.styles.texts.length === 0} />
            </aside>
          </div>
        )}
      </div>
    </>
  );
}
