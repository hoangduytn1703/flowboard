import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { VOICES, isGeminiVoice, uploadImage, mediaUrl } from "../../api/client";
import {
  characterBadges,
  characterPhotoUrl,
  defaultCharacterLabel,
  defaultVoiceFor,
  voiceOf,
  type CharacterMeta,
  type SavedCharacter,
} from "../../api/characters";
import {
  CHARACTER_COUNTRIES,
  CHARACTER_GENDERS,
  CHARACTER_VIBES,
  type CountryKey,
  type GenderKey,
  type VibeKey,
} from "../../constants/character";
import { buildCharacterPrompt } from "../../lib/characterPrompt";
import { useCharactersStore } from "../../store/references";
import { useGenerationStore } from "../../store/generation";
import { VoiceField, VoicePreview } from "../VoiceField";
import { generateStandaloneImage } from "../standaloneImage";
import "../models.css";
import { toast, useToastOn } from "../../store/toast";
import { PageEmpty } from "../PageState";
import { askConfirm } from "../../components/Dialogs";

/** Longest model line: one 8-second clip holds about 24 words. */
const MAX_LINE = 200;

/** /models — the saved models (kind "character" references) as a page of
 * its own, inside the /clips layout. Models get here from step 1 of the
 * wizard ("★ Lưu người mẫu") and go back in through "Chọn từ thư viện". */
export function ModelsPage() {
  const items = useCharactersStore((s) => s.items);
  const loaded = useCharactersStore((s) => s.loaded);
  const error = useCharactersStore((s) => s.error);
  useToastOn(error ? `Không tải được thư viện người mẫu: ${error}` : null, "error");
  const load = useCharactersStore((s) => s.load);
  // null = no editor; "new" = create; a saved model = edit it.
  const [editing, setEditing] = useState<"new" | SavedCharacter | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  function openEditor(target: "new" | SavedCharacter) {
    setEditing(target);
    window.setTimeout(() => editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  useEffect(() => { void load(true); }, [load]);
  useEffect(() => {
    const prev = document.title;
    document.title = "Người mẫu đã lưu · DFlow";
    return () => { document.title = prev; };
  }, []);

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Người mẫu đã lưu</span>
      </header>
      <div className="qt-home">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Thư viện</div>
            <h2 className="qt-card__title">
              Người mẫu đã lưu{loaded && <span className="qt-models-page__count"> · {items.length}</span>}
            </h2>
          </div>
          <div className="qt-row">
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" onClick={() => void load(true)}>Tải lại</button>
            <button type="button" className="qt-btn qt-btn--accent" onClick={() => (editing === "new" ? setEditing(null) : openEditor("new"))}
                    aria-expanded={editing === "new"}>
              {editing === "new" ? "Đóng" : "+ Tạo người mẫu"}
            </button>
          </div>
        </div>

        <div ref={editorRef}>
          {editing && (
            <ModelEditor key={editing === "new" ? "new" : editing.id} item={editing === "new" ? null : editing}
                         onDone={() => setEditing(null)} />
          )}
        </div>

        <div className="qt-models-page__hint">
          <strong>Dùng lại một người mẫu cho sản phẩm khác:</strong> mở clip → <strong>Bước 1 · Người mẫu</strong> → bấm
          "👤 Chọn từ thư viện" → "Dùng người mẫu này". Ảnh người mẫu sẽ thay cho ảnh tạo mới và các cảnh lấy nó làm tham chiếu.
          <ol>
            <li>Thêm người mẫu: bấm <strong>+ Tạo người mẫu</strong> ở trên (tạo bằng AI hoặc upload ảnh người thật), hoặc ở Bước 1 của clip bấm <strong>★ Lưu người mẫu</strong>.</li>
            <li>Mỗi người mẫu có <strong>giọng đọc</strong> riêng (mặc định theo giới tính) và một <strong>câu nói</strong> tuỳ chọn. Khi dùng người mẫu cho clip, giọng này thành giọng đọc của clip, câu nói được thêm vào đầu lời thoại cảnh 1.</li>
            <li>Bấm vào thẻ người mẫu để đổi tên, ảnh, thông tin, giọng, câu nói. <strong>⧉ Nhân bản</strong> tạo một bản sao giống hệt (cùng ảnh) rồi mở form sửa bản sao — tiện để làm biến thể khác giọng / câu nói. Xoá chỉ bỏ khỏi thư viện, clip đã dùng người mẫu đó không bị ảnh hưởng.</li>
          </ol>
        </div>


        {loaded && items.length === 0 && !error && editing !== "new" && (
          <PageEmpty icon="👤" title="Chưa có người mẫu nào"
                     actions={<button type="button" className="qt-btn qt-btn--accent" onClick={() => openEditor("new")}>+ Tạo người mẫu</button>}>
            Tạo người mẫu bằng AI hoặc upload ảnh người thật, đặt giọng đọc và câu nói riêng — dùng lại cho mọi clip.
          </PageEmpty>
        )}

        <div className="qt-home__grid">
          {!loaded && Array.from({ length: 4 }, (_, i) => (
            <div key={`sk-${i}`} className="qt-model-card qt-model-card--skeleton" aria-hidden="true">
              <span className="qt-model-card__photo qt-skeleton" />
              <span className="qt-skeleton qt-skeleton--line" />
              <span className="qt-skeleton qt-skeleton--line qt-skeleton--short" />
            </div>
          ))}
          {loaded && items.map((c) => (
            <ModelCard key={c.id} item={c} active={editing !== "new" && editing?.id === c.id} onEdit={() => openEditor(c)}
                       onCloned={openEditor} />
          ))}
        </div>
      </div>
    </>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** A saved model, read-only: photo, name, form badges, voice (with a
 * preview), line. Clicking the card opens the editor; "⧉ Nhân bản" makes a
 * copy and opens the editor on the copy. */
function ModelCard({ item, active, onEdit, onCloned }: {
  item: SavedCharacter;
  active: boolean;
  onEdit: () => void;
  onCloned: (copy: SavedCharacter) => void;
}) {
  const remove = useCharactersStore((s) => s.remove);
  const clone = useCharactersStore((s) => s.clone);
  const [busy, setBusy] = useState(false);

  async function onClone() {
    setBusy(true);
    try {
      const copy = await clone(item.id);
      toast.success(`Đã nhân bản "${item.label}" — đổi tên hoặc sửa bản sao ở form bên trên nếu cần.`);
      onCloned(copy);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Không nhân bản được.");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!await askConfirm(`Xoá người mẫu "${item.label}" khỏi thư viện? Clip đã dùng người mẫu này vẫn giữ ảnh.`)) return;
    setBusy(true);
    try {
      await remove(item.id);
      toast.success(`Đã xoá người mẫu "${item.label}".`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Không xoá được.");
      setBusy(false);
    }
  }

  const badges = characterBadges(item.meta);
  const date = formatDate(item.createdAt);
  const voice = voiceOf(item);
  return (
    // The whole card opens the editor; the buttons inside keep their own click.
    <div className={`qt-model-card qt-model-card--clickable${active ? " qt-model-card--current" : ""}`}
         role="button" tabIndex={0} title="Bấm để sửa người mẫu này"
         onClick={onEdit}
         onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onEdit(); } }}>
      <img className="qt-model-card__photo" src={characterPhotoUrl(item)} alt={item.label} loading="lazy" />
      <div className="qt-model-card__name"><span title={item.label}>{item.label}</span></div>
      {badges.length > 0 && (
        <div className="qt-badges">
          {badges.map((b) => <span key={b} className="qt-badge">{b}</span>)}
        </div>
      )}
      <div className="qt-model-card__voiceline">
        <span title={VOICES[voice] ?? voice}>🎙 {VOICES[voice]?.split(" · ")[0] ?? voice}{!item.meta.voice && <small> (mặc định)</small>}</span>
        <span onClick={(e) => e.stopPropagation()}>
          <VoicePreview voice={voice} style={item.meta.voiceStyle} text={item.meta.line} />
        </span>
      </div>
      {item.meta.line && <div className="qt-model-card__line" title={item.meta.line}>💬 "{item.meta.line}"</div>}
      <div className="qt-model-card__meta">
        {date && <>Lưu ngày {date}</>}
        {item.meta.product && <>{date ? " · " : ""}từ "{item.meta.product}"</>}
      </div>
      <div className="qt-row qt-row--tight qt-model-card__actions" onClick={(e) => e.stopPropagation()}>
        {item.sourceBoardId !== null && (
          <Link className="qt-link" to={`/clips/${item.sourceBoardId}`} title="Mở clip đã tạo ra người mẫu này">Mở clip gốc ↗</Link>
        )}
        <button type="button" className="project-modal__btn qt-model-card__clone" disabled={busy}
                onClick={() => void onClone()} title="Tạo một bản sao giống hệt (ảnh, thông tin, giọng, câu nói) rồi mở form sửa bản sao">
          ⧉ Nhân bản
        </button>
        <button type="button" className="project-modal__btn project-modal__btn--danger qt-model-card__delete" disabled={busy}
                onClick={() => void onDelete()}>
          Xoá
        </button>
      </div>
    </div>
  );
}

/** An image that retries a few times: a fresh Flow render is reported done a
 * moment before its file is in the local media cache, so the first load can 404. */
function RetryImg({ src, alt }: { src: string; alt: string }) {
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { setAttempt(0); }, [src]);
  const url = attempt ? `${src}${src.includes("?") ? "&" : "?"}r=${attempt}` : src;
  return (
    <img src={url} alt={alt}
         onError={() => { if (attempt < 6) window.setTimeout(() => setAttempt((a) => a + 1), 1500); }} />
  );
}

interface Photo {
  mediaId: string;
  aspect: string | null;
  /** The prompt an AI photo was drawn from (kept in meta.prompt). */
  prompt?: string;
}

/**
 * Create a model ("+ Tạo người mẫu") or edit a saved one ("✎ Sửa"): photo
 * (AI or a real photo, both only previewed), form, name, voice, line.
 * Nothing is saved until "Lưu".
 */
function ModelEditor({ item, onDone }: { item: SavedCharacter | null; onDone: () => void }) {
  const save = useCharactersStore((s) => s.save);
  const update = useCharactersStore((s) => s.update);
  const isEdit = item !== null;
  const [gender, setGender] = useState<GenderKey>((item?.meta.gender as GenderKey) ?? "female");
  const [country, setCountry] = useState<CountryKey>((item?.meta.country as CountryKey) ?? "vn");
  const [vibe, setVibe] = useState<VibeKey>((item?.meta.vibe as VibeKey) ?? CHARACTER_VIBES[0].key);
  const [extras, setExtras] = useState(item?.meta.extras ?? "");
  const [name, setName] = useState(item?.label ?? "");
  const [voice, setVoice] = useState(item ? voiceOf(item) : defaultVoiceFor("female"));
  const [voiceTouched, setVoiceTouched] = useState(!!item?.meta.voice);
  const [voiceStyle, setVoiceStyle] = useState(item?.meta.voiceStyle ?? "");
  const [line, setLine] = useState(item?.meta.line ?? "");
  const [photo, setPhoto] = useState<Photo | null>(item ? { mediaId: item.mediaId, aspect: item.aspectRatio, prompt: item.meta.prompt } : null);
  const [busy, setBusy] = useState<"" | "ai" | "upload" | "save">("");
  const fileRef = useRef<HTMLInputElement>(null);

  // The voice follows the gender until the user picks one on purpose.
  useEffect(() => { if (!voiceTouched) setVoice(defaultVoiceFor(gender)); }, [gender, voiceTouched]);

  const meta = (): CharacterMeta => ({
    ...(item?.meta ?? {}),
    gender, country, vibe,
    extras: extras.trim() || undefined,
    voice: voiceTouched ? voice : undefined,
    voiceStyle: isGeminiVoice(voice) ? voiceStyle.trim() || undefined : undefined,
    line: line.trim() || undefined,
    prompt: photo?.prompt ?? item?.meta.prompt,
  });
  const label = () => name.trim() || defaultCharacterLabel(meta());
  const photoChanged = !!photo && photo.mediaId !== item?.mediaId;

  async function generate() {
    setBusy("ai");
    try {
      const prompt = buildCharacterPrompt(gender, country, vibe, extras);
      const mediaId = await generateStandaloneImage(prompt);
      setPhoto({ mediaId, aspect: "IMAGE_ASPECT_RATIO_PORTRAIT", prompt });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Tạo ảnh người mẫu thất bại.");
    } finally {
      setBusy("");
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy("upload");
    try {
      const projectId = await useGenerationStore.getState().ensureProjectId();
      if (!projectId) throw new Error("Chưa có Flow project — ghim một project trong Cài đặt.");
      const up = await uploadImage(file, projectId);
      setPhoto({ mediaId: up.media_id, aspect: up.aspect_ratio ?? null });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload ảnh thất bại.");
    } finally {
      setBusy("");
    }
  }

  async function submit() {
    if (!photo) {
      toast.warning("Chưa có ảnh: bấm \"✨ Tạo ảnh bằng AI\" hoặc \"⬆ Upload ảnh người thật\" trước khi lưu.");
      return;
    }
    setBusy("save");
    try {
      if (isEdit) {
        await update(item!.id, {
          label: label(),
          meta: meta(),
          ...(photoChanged ? { media_id: photo.mediaId, aspect_ratio: photo.aspect } : {}),
        });
        toast.success(`Đã lưu thay đổi cho "${label()}".`);
      } else {
        await save({ media_id: photo.mediaId, label: label(), meta: meta(), aspect_ratio: photo.aspect ?? "IMAGE_ASPECT_RATIO_PORTRAIT" });
        toast.success(`Đã lưu người mẫu "${label()}" vào thư viện.`);
      }
      onDone();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Lưu người mẫu thất bại.");
    } finally {
      setBusy("");
    }
  }

  const locked = busy !== "";
  return (
    <section className="qt-card qt-model-create">
      <div className="qt-card__eyebrow">{isEdit ? `Sửa người mẫu · ${item!.label}` : "Người mẫu mới"}</div>
      <div className="qt-model-create__body">
        <div className="qt-model-create__photo">
          {photo ? (
            <RetryImg src={mediaUrl(photo.mediaId)} alt="Ảnh người mẫu" />
          ) : (
            <div className={`qt-model-create__empty${busy === "ai" ? " qt-busy" : ""}`}>
              {busy === "ai" ? "AI đang vẽ… (~20–60 s)" : busy === "upload" ? "Đang upload…" : "Chưa có ảnh"}
            </div>
          )}
          {photoChanged && isEdit && <div className="qt-model-create__badge">Ảnh mới, chưa lưu</div>}
          <div className="qt-model-create__photo-actions">
            <button type="button" className="qt-btn qt-btn--small" disabled={locked} onClick={() => void generate()}
                    title="Vẽ một ảnh người mẫu theo thông tin bên phải (tốn 1 lượt tạo ảnh Flow)">
              {busy === "ai" ? "Đang tạo…" : photo ? "✨ Tạo lại bằng AI" : "✨ Tạo ảnh bằng AI"}
            </button>
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={locked} onClick={() => fileRef.current?.click()}>
              {busy === "upload" ? "Đang upload…" : photo ? "⬆ Đổi ảnh thật" : "⬆ Upload ảnh người thật"}
            </button>
            {photoChanged && isEdit && (
              <button type="button" className="qt-link" disabled={locked}
                      onClick={() => setPhoto({ mediaId: item!.mediaId, aspect: item!.aspectRatio, prompt: item!.meta.prompt })}>
                Giữ ảnh cũ
              </button>
            )}
          </div>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden
                 onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ""; }} />
        </div>
        <div className="qt-model-create__form">
          <label className="qt-field"><span>Giới tính</span>
            <select value={gender} disabled={locked} onChange={(e) => setGender(e.target.value as GenderKey)}>
              {CHARACTER_GENDERS.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
            </select>
          </label>
          <label className="qt-field"><span>Quốc gia</span>
            <select value={country} disabled={locked} onChange={(e) => setCountry(e.target.value as CountryKey)}>
              {CHARACTER_COUNTRIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </label>
          <label className="qt-field"><span>Phong cách</span>
            <select value={vibe} disabled={locked} onChange={(e) => setVibe(e.target.value as VibeKey)}>
              {CHARACTER_VIBES.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
            </select>
          </label>
          <label className="qt-field qt-field--wide"><span>Mô tả thêm (tiếng Anh: tóc, tuổi, nét mặt — tuỳ chọn)</span>
            <input type="text" maxLength={200} value={extras} disabled={locked} placeholder="ví dụ: early 20s, long black hair, warm smile"
                   onChange={(e) => setExtras(e.target.value)} />
          </label>
          <label className="qt-field qt-field--wide"><span>Tên (tuỳ chọn)</span>
            <input type="text" maxLength={120} value={name} disabled={locked} placeholder={defaultCharacterLabel(meta())}
                   onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="qt-field qt-field--wide"><span>Giọng đọc{!voiceTouched && <small> · mặc định theo giới tính</small>}</span>
            <VoiceField value={voice} style={voiceStyle} sampleText={line} disabled={locked}
                        onChange={(v) => { setVoice(v); setVoiceTouched(true); }} />
          </label>
          {isGeminiVoice(voice) && (
            <label className="qt-field qt-field--wide"><span>Phong cách đọc (giọng Gemini — tuỳ chọn)</span>
              <input type="text" maxLength={160} value={voiceStyle} disabled={locked} placeholder="ví dụ: vui vẻ, hào hứng, nói hơi nhanh"
                     onChange={(e) => setVoiceStyle(e.target.value)} />
            </label>
          )}
          <label className="qt-field qt-field--wide"><span>Câu nói của người mẫu (tuỳ chọn — thêm vào đầu lời thoại cảnh 1 khi dùng cho clip)</span>
            <input type="text" maxLength={MAX_LINE} value={line} disabled={locked} placeholder="ví dụ: Hello cả nhà, lại là Vy đây!"
                   onChange={(e) => setLine(e.target.value)} />
          </label>
          <div className="qt-field--wide qt-row">
            <button type="button" className="qt-btn qt-btn--accent" disabled={locked || !photo} onClick={() => void submit()}
                    title={photo ? "" : "Cần có ảnh trước"}>
              {busy === "save" ? "Đang lưu…" : isEdit ? "Lưu thay đổi" : "★ Lưu vào thư viện"}
            </button>
            <button type="button" className="qt-btn qt-btn--ghost" disabled={locked} onClick={onDone}>Huỷ</button>
          </div>
          <p className="qt-card__hint qt-field--wide">
            Ảnh (AI hay upload) chỉ để xem trước, bấm Lưu mới lưu. Tạo bằng AI tốn 1 lượt tạo ảnh Flow.
            {isEdit && " Đổi thông tin không tự vẽ lại ảnh — bấm \"✨ Tạo lại bằng AI\" nếu muốn ảnh khớp thông tin mới."}
          </p>
        </div>
      </div>
    </section>
  );
}
