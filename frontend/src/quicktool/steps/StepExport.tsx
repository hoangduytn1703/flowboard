import { useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import {
  BGM_DEFAULT_VOLUME, BGM_VOLUMES, COVER_STYLES, MAX_MUSIC_BYTES, MAX_SPEAKERS, VOICES,
  createCover, isGeminiVoice, mediaUrl, parseSpeakers, patchNode, previewVoice, speakerTags, uploadMusic,
  type CoverStyle, patchBoardData } from "../../api/client";
import { VoiceOptions, useVoiceGroups } from "../VoiceField";
import { useBoardStore, type FlowboardNodeData } from "../../store/board";
import { useQuicktoolStore } from "../../store/quicktool";
import { hasMedia, isBusy, type ClipRoles } from "../roles";
import "../voices.css";
import { useToastOn } from "../../store/toast";
import { ClipArranger, OverlayEditor } from "./ExportEditor";
import { joinVoice, Smooth60Field, SubtitleField, subChoiceOf, subChoicePatch } from "./JoinOptions";
import { useSettingsStore } from "../../store/settings";
import { ScheduleDialog } from "../schedule/ScheduleDialog";

// ── voice preview ───────────────────────────────────────────────────────────
// Only one sample plays at a time, whichever button started it.
let playingSample: HTMLAudioElement | null = null;

function stopSample() {
  if (playingSample) {
    playingSample.pause();
    playingSample.src = "";
    playingSample = null;
  }
}

/** "▶ Nghe thử" for one voice (+ Gemini style); used by the main voice
 * picker and by each dialogue speaker row. */
function VoicePreviewButton({ voice, style }: { voice: string; style?: string }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [error, setError] = useState<string | null>(null);
  useToastOn(error, "error", () => setError(null));
  const audioRef = useRef<HTMLAudioElement | null>(null);

  function stop() {
    if (audioRef.current) {
      if (playingSample === audioRef.current) playingSample = null;
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    setState("idle");
  }

  // Stop the sample when the voice changes or the button unmounts.
  useEffect(() => stop, [voice, style]);

  async function play() {
    if (state !== "idle") {
      stop();
      return;
    }
    stopSample();
    setError(null);
    setState("loading");
    try {
      const { url } = await previewVoice(voice, isGeminiVoice(voice) ? style : undefined);
      const audio = new Audio(url);
      audioRef.current = audio;
      playingSample = audio;
      audio.onended = () => { if (audioRef.current === audio) stop(); };
      audio.onerror = () => { if (audioRef.current === audio) { stop(); setError("Không phát được file mẫu."); } };
      await audio.play();
      setState("playing");
    } catch (err) {
      stop();
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <button
        type="button"
        className={"qt-field__action" + (state === "playing" ? " qt-field__action--live" : "")}
        disabled={state === "loading"}
        title="Nghe một câu mẫu bằng giọng này"
        onClick={(e) => { e.preventDefault(); void play(); }}
      >
        {state === "loading" ? "Đang tạo…" : state === "playing" ? "■ Dừng" : "▶ Nghe thử"}
      </button>
    </>
  );
}

function SpeakerChip({ tag, tags }: { tag: string; tags: string[] }) {
  const idx = tags.indexOf(tag);
  return <span className={"qt-speaker-chip" + (idx >= 0 ? ` qt-speaker-chip--${idx % 4}` : "")}>{tag}</span>;
}

/** A voice line with its `[A]` tags rendered as coloured chips. */
function DialogueLine({ text, tags }: { text: string; tags: string[] }) {
  const segs = parseSpeakers(text);
  if (!segs.some((s) => s.tag)) return <>{text}</>;
  return (
    <>
      {segs.map((seg, i) => (
        <span key={i} className="qt-cliplist__seg">
          {seg.tag && <SpeakerChip tag={seg.tag} tags={tags} />}
          {seg.text}
        </span>
      ))}
    </>
  );
}

/** Step 5 — voice options, the clip list, the final file. */
import { useFeature } from "../../lib/features";

export function StepExport({ roles, productName = "", price = "", channelId = null, dubJobId = null, dubPart = null, cutPart = null, voiceless = false }: {
  roles: ClipRoles; productName?: string; price?: string; channelId?: number | null;
  /** "🔇 Không lời": joined with the clips' own sound — no voice, no subtitles. */
  voiceless?: boolean;
  /** a clip made by the dubbing tool: it is edited there, not joined here */
  dubJobId?: string | null;
  /** a part cut out of a dubbed video ("✂️ Cắt thành nhiều video") */
  dubPart?: { index: number; total: number } | null;
  /** a part of a long video cut on the "✂️ Cắt video" page: edited there, dubbed on the dubbing page */
  cutPart?: { job_id: string; run_id: string; index: number; total: number; board_id: number | null } | null;
}) {
  const voiceGroups = useVoiceGroups();
  const navigate = useNavigate();
  const fbOn = useFeature("facebook");
  const postsOn = useFeature("posts");
  const dubOn = useFeature("dub");
  const cutOn = useFeature("cut");
  const [scheduling, setScheduling] = useState(false);
  // "Ghép" clicked, the export not queued yet (the clips are being wired): the button greys out at once
  const [sending, setSending] = useState(false);
  const ensureExportNode = useQuicktoolStore((s) => s.ensureExportNode);
  const exportClip = useQuicktoolStore((s) => s.exportClip);
  const writeNarrations = useQuicktoolStore((s) => s.writeNarrations);
  const boardId = useBoardStore((s) => s.boardId);
  const boardName = useBoardStore((s) => s.boardName);
  const exp = roles.export;

  // The options live on the export node, so make sure there is one.
  useEffect(() => {
    if (!exp) void ensureExportNode();
  }, [exp, ensureExportNode]);

  function setOption(patch: Partial<FlowboardNodeData>) {
    if (!exp) return;
    useBoardStore.getState().updateNodeData(exp.id, patch);
    const dbId = parseInt(exp.id, 10);
    if (!isNaN(dbId)) patchNode(dbId, { data: patch }).catch(() => {});
  }

  const isDrama = useQuicktoolStore((s) => s.isDrama)();
  const sequence = useQuicktoolStore((s) => s.sequenceItems)();
  // Drama: the play order (stills + spliced clips); otherwise one clip per scene.
  const clips = isDrama
    ? sequence.filter((it) => hasMedia(it.node)).map((it, i) => ({ index: i + 1, image: it.node, video: it.node }))
    : roles.scenes.filter((s) => s.video && hasMedia(s.video));
  const voiced = clips.filter((s) => typeof s.video!.data.narration === "string" && s.video!.data.narration.trim()).length;
  const estimate = isDrama
    ? Math.round(clips.reduce((t, s) => {
        const words = String(s.video!.data.narration ?? "").split(/\s+/).filter(Boolean).length;
        return t + (s.video!.data.type === "video" ? 8 : Math.max(4, words / 2.8 + 1));
      }, 0))
    : Math.round(clips.reduce((t, s) => {
        // Step 5 picks: a left-out scene adds nothing, a cut one its window (clips are 8 s).
        if (exp?.data.clipSkip?.includes(s.video!.id)) return t;
        const cut = exp?.data.clipTrims?.[s.video!.id];
        return t + (cut ? Math.max(0.5, Math.min(cut[1] ?? 8, 8) - cut[0]) : 8);
      }, 0));
  // the clip's own voice, else the account's favourite dubbing voice (also what the export sends)
  const favouriteVoice = useSettingsStore((s) => s.dubVoice);
  const setFavouriteVoice = useSettingsStore((s) => s.setDubVoice);
  const voice = joinVoice(exp?.data, favouriteVoice);
  const voiceStyle = typeof exp?.data.voiceStyle === "string" ? exp.data.voiceStyle : "";
  const originalAudio = exp?.data.originalAudio ?? "duck";
  const busy = isBusy(exp);

  // Stop any sample when the step unmounts.
  useEffect(() => stopSample, []);

  // ── dialogue speakers ───────────────────────────────────────────────────
  // `[A] … [B] …` tags found in the voice lines, plus the ones the user
  // named by hand; each maps to a voice on the export node (`speakers`).
  const lines = clips.map((s) => (typeof s.video!.data.narration === "string" ? s.video!.data.narration : ""));
  const usedTags = speakerTags(lines);
  const speakers: Record<string, string> =
    exp?.data.speakers && typeof exp.data.speakers === "object" ? (exp.data.speakers as Record<string, string>) : {};
  const [extraTags, setExtraTags] = useState<string[]>([]);
  const allTags = [...usedTags];
  for (const t of [...Object.keys(speakers), ...extraTags]) if (!allTags.includes(t)) allTags.push(t);
  const showSpeakers = allTags.length > 0;

  function setSpeaker(tag: string, v: string) {
    const next = { ...speakers };
    if (v) next[tag] = v; else delete next[tag];
    setOption({ speakers: next });
  }

  function addSpeaker() {
    const tag = ["A", "B", "C", "D"].find((t) => !allTags.includes(t));
    if (!tag) return;
    setExtraTags((p) => [...p, tag]);
  }

  function removeSpeaker(tag: string) {
    setExtraTags((p) => p.filter((t) => t !== tag));
    if (tag in speakers) setSpeaker(tag, "");
  }

  // ── background music ────────────────────────────────────────────────────
  const bgmMediaId = typeof exp?.data.bgmMediaId === "string" && exp.data.bgmMediaId ? exp.data.bgmMediaId : null;
  const bgmName = typeof exp?.data.bgmName === "string" ? exp.data.bgmName : "";
  const bgmVolume = BGM_VOLUMES.some(([v]) => v === exp?.data.bgmVolume) ? (exp!.data.bgmVolume as number) : BGM_DEFAULT_VOLUME;
  const [bgmUploading, setBgmUploading] = useState(false);
  const [bgmError, setBgmError] = useState<string | null>(null);
  useToastOn(bgmError ? `Nhạc nền: ${bgmError}` : null, "error", () => setBgmError(null));

  async function pickMusic(file: File | undefined) {
    if (!file) return;
    setBgmError(null);
    if (file.size > MAX_MUSIC_BYTES) {
      setBgmError(`File ${Math.round(file.size / 1024 / 1024)} MB — tối đa 20 MB.`);
      return;
    }
    setBgmUploading(true);
    try {
      const res = await uploadMusic(file);
      setOption({ bgmMediaId: res.media_id, bgmName: res.name, bgmVolume });
    } catch (err) {
      setBgmError(err instanceof Error ? err.message : String(err));
    } finally {
      setBgmUploading(false);
    }
  }

  // ── cover image ─────────────────────────────────────────────────────────
  // Scenes that have an image: the candidates for the cover.
  const sceneImages = (isDrama
    ? sequence.filter((it) => it.kind === "image" && hasMedia(it.node)).map((it, i) => ({ mediaId: it.node.data.mediaId as string, title: String(it.node.data.title ?? `Ảnh ${i + 1}`) }))
    : roles.scenes.filter((s) => hasMedia(s.image)).map((s) => ({ mediaId: s.image.data.mediaId as string, title: String(s.image.data.title ?? `Cảnh ${s.index}`) })))
    // The product photos work as a cover too (handy before step 3 has run).
    .concat(roles.products.filter(hasMedia).map((p, i) => ({ mediaId: p.data.mediaId as string, title: i === 0 ? "Ảnh sản phẩm" : `Ảnh sản phẩm ${i + 1}` })));
  const [coverTitle, setCoverTitle] = useState<string | null>(null);
  const [coverSubtitle, setCoverSubtitle] = useState("");
  const [coverStyle, setCoverStyle] = useState<CoverStyle>("yellow");
  const [coverScene, setCoverScene] = useState<string | null>(null);
  const [coverBusy, setCoverBusy] = useState(false);
  const [coverError, setCoverError] = useState<string | null>(null);
  useToastOn(coverError ? `Ảnh bìa: ${coverError}` : null, "error", () => setCoverError(null));
  const title = coverTitle ?? boardName;
  const selectedScene = sceneImages.find((s) => s.mediaId === coverScene)?.mediaId ?? sceneImages[0]?.mediaId ?? null;
  const coverMediaId = typeof exp?.data.coverMediaId === "string" && exp.data.coverMediaId ? exp.data.coverMediaId : null;

  async function makeCover() {
    if (boardId === null || !selectedScene || !title.trim()) return;
    setCoverError(null);
    setCoverBusy(true);
    try {
      const res = await createCover(boardId, {
        media_id: selectedScene, title: title.trim(), subtitle: coverSubtitle.trim() || undefined, style: coverStyle,
      });
      setOption({ coverMediaId: res.media_id });
    } catch (err) {
      setCoverError(err instanceof Error ? err.message : String(err));
    } finally {
      setCoverBusy(false);
    }
  }

  return (
    <div className="qt-step qt-step--two">
      {cutPart ? (
        <section className="qt-card qt-dubclip">
          <div className="qt-card__eyebrow">Video {cutPart.index}/{cutPart.total} cắt từ video dài</div>
          <h3 className="qt-card__title">Chỉnh ở trang Cắt video</h3>
          <p className="qt-card__hint">
            Video này được <strong>cắt</strong> ra từ một video dài, giữ nguyên tiếng gốc. Chỉnh phụ đề (đúng lời trong video hoặc dịch), khung
            9:16 + nền, vùng mờ che chữ / logo, nhân vật, nhấn chữ — từng video hoặc cả loạt; xuất xong clip này tự dùng bản mới.
          </p>
          <div className="qt-dubclip__acts">
            {cutOn && <button type="button" className="qt-btn qt-btn--accent qt-btn--big"
                              onClick={() => navigate(`/tools/cut?job=${cutPart.job_id}${cutPart.run_id ? `&run=${cutPart.run_id}` : ""}`)}>✏️ Mở trình chỉnh sửa</button>}
            {dubOn && cutPart.board_id && <button type="button" className="qt-btn qt-btn--big"
                              onClick={() => navigate(`/tools/dub?clips=${cutPart.board_id}`)}>🎙 Lồng tiếng video này</button>}
          </div>
        </section>
      ) : dubJobId ? (
        <section className="qt-card qt-dubclip">
          <div className="qt-card__eyebrow">{dubPart ? `Phần ${dubPart.index}/${dubPart.total} của video lồng tiếng` : "Video lồng tiếng"}</div>
          <h3 className="qt-card__title">{dubPart ? "Chỉnh hoặc cắt lại ở trang Lồng tiếng" : "Chỉnh phụ đề, giọng đọc, bản dịch"}</h3>
          {dubPart ? (
            <p className="qt-card__hint">
              Clip này được <strong>cắt</strong> từ một video lồng tiếng. Muốn sửa phụ đề, giọng hay đổi chỗ cắt: mở trang chỉnh, sửa rồi
              "Xuất lại video", sau đó vào tab <strong>✂️ Cắt</strong> bấm cắt lại — clip này tự nhận bản mới.
            </p>
          ) : (
            <p className="qt-card__hint">
              Clip này làm từ công cụ <strong>Lồng tiếng video</strong>. Vị trí và cỡ phụ đề, kiểu chữ, vùng làm mờ chữ gốc, giọng đọc và
              từng câu dịch đều chỉnh ở đó — bấm "Áp dụng" / "Render lại" xong thì clip này tự cập nhật bản mới.
            </p>
          )}
          <ul className="qt-dubclip__list">
            <li>🎯 Kéo phụ đề, đổi cỡ chữ, kiểu hộp vàng / trắng / viền</li>
            <li>🌫 Vùng làm mờ che chữ gốc</li>
            <li>🗣 Đổi giọng đọc, sửa từng câu dịch</li>
          </ul>
          {dubOn && <a className="qt-btn qt-btn--accent qt-btn--big" href={`/tools/dub?job=${dubJobId}`}
             onClick={(e) => { e.preventDefault(); navigate(`/tools/dub?job=${dubJobId}`); }}>✏️ Mở trang chỉnh phụ đề & giọng</a>}
        </section>
      ) : (
      <section className="qt-card">
        <div className="qt-card__eyebrow">Bước 5</div>
        <h3 className="qt-card__title">{voiceless ? "Ghép clip" : "Ghép & lồng tiếng"}</h3>
        <div className="qt-stats">
          <div className="qt-stat"><strong>{clips.length}</strong><span>clip sẵn sàng</span></div>
          {voiceless
            ? <div className="qt-stat"><strong>🔇</strong><span>không lời</span></div>
            : <div className="qt-stat"><strong>{voiced}</strong><span>có lời thoại</span></div>}
          <div className="qt-stat"><strong>~{estimate}s</strong><span>thời lượng</span></div>
        </div>
        {!isDrama && clips.length > 0 ? (
          <ClipArranger clips={clips} exp={exp} busy={busy} setOption={setOption} renderLine={(s) => (
            <>
              {typeof s.video!.data.narration === "string" && s.video!.data.narration
                ? <DialogueLine text={s.video!.data.narration} tags={allTags} />
                : <em>{voiceless ? "không lời — giữ tiếng thật" : "chưa có lời thoại"}</em>}
              {typeof s.video!.data.voice === "string" && s.video!.data.voice in VOICES && (
                <small className="qt-speakers__unused"> · giọng riêng: {VOICES[s.video!.data.voice]}</small>
              )}
            </>
          )} />
        ) : (
        <ol className="qt-cliplist">
          {clips.map((s) => (
            <li key={s.video!.id}>
              <span className="qt-cliplist__num">{s.index}</span>
              <span className="qt-cliplist__title">{s.image.data.title}</span>
              <span className="qt-cliplist__line">
                {typeof s.video!.data.narration === "string" && s.video!.data.narration
                  ? <DialogueLine text={s.video!.data.narration} tags={allTags} />
                  : <em>chưa có lời thoại</em>}
                {typeof s.video!.data.voice === "string" && s.video!.data.voice in VOICES && (
                  <small className="qt-speakers__unused"> · giọng riêng: {VOICES[s.video!.data.voice]}</small>
                )}
              </span>
            </li>
          ))}
          {clips.length === 0 && <li className="qt-empty">{isDrama ? "Chưa có ảnh nào — quay lại bước 3." : "Chưa có video nào — quay lại bước 4."}</li>}
        </ol>
        )}
        {voiceless && (
          <div className="qt-voiceless">
            <strong>🔇 Clip không lời</strong>
            <small>Không giọng đọc, không phụ đề — ghép giữ tiếng động thật của từng video. Muốn có lời thì bật lại ở Bước 2.</small>
          </div>
        )}
        {clips.length > 0 && voiced < clips.length && !isDrama && !voiceless && (
          <button type="button" className="qt-btn qt-btn--ghost" onClick={() => void writeNarrations()}>
            ✨ AI viết lời thoại còn thiếu
          </button>
        )}

        <div className="qt-form">
          {!voiceless && (<>
          <label className="qt-field">
            <span>
              Giọng đọc
              <VoicePreviewButton voice={voice} style={voiceStyle} />
            </span>
            <select value={voice} disabled={busy} onChange={(e) => { stopSample(); setOption({ voice: e.target.value }); setFavouriteVoice(e.target.value); }}>
              <VoiceOptions groups={voiceGroups} />
            </select>
          </label>
          {isGeminiVoice(voice) && (
            <>
              <label className="qt-field">
                <span>Phong cách đọc (Gemini)</span>
                <input
                  type="text"
                  maxLength={160}
                  key={`vs-${exp?.id}`}
                  defaultValue={voiceStyle}
                  placeholder="ví dụ: giọng kể chuyện kịch tính, chậm rãi · vui tươi như bán hàng livestream"
                  disabled={busy}
                  onBlur={(e) => setOption({ voiceStyle: e.target.value.trim() })}
                />
              </label>
              <p className="qt-hint">Giọng Gemini dùng quota API key; phụ đề chia đều theo độ dài câu.</p>
            </>
          )}
          {showSpeakers ? (
            <div className="qt-speakers">
              <div className="qt-speakers__head">
                <span>🗣 Nhân vật lồng tiếng</span>
                <small>gõ [A] … [B] … trong lời thoại ở bước 2</small>
              </div>
              {allTags.map((tag) => {
                const picked = speakers[tag] && speakers[tag] in VOICES ? speakers[tag] : "";
                return (
                  <div key={tag} className="qt-speakers__row">
                    <SpeakerChip tag={tag} tags={allTags} />
                    <select value={picked} disabled={busy} onChange={(e) => setSpeaker(tag, e.target.value)}>
                      <option value="">giọng chung ({VOICES[voice] ?? voice})</option>
                      <VoiceOptions groups={voiceGroups} short />
                    </select>
                    <VoicePreviewButton voice={picked || voice} style={voiceStyle} />
                    {usedTags.includes(tag)
                      ? <span className="qt-speakers__unused" title="Đang dùng trong lời thoại">đang dùng</span>
                      : <button type="button" className="qt-link qt-link--danger" disabled={busy} onClick={() => removeSpeaker(tag)}>Bỏ</button>}
                  </div>
                );
              })}
              {allTags.length < MAX_SPEAKERS && (
                <button type="button" className="qt-link" disabled={busy} onClick={addSpeaker}>+ Thêm nhân vật</button>
              )}
              <p className="qt-hint">Giữa hai lượt thoại có 0,3 s nghỉ; nhân vật chưa chọn giọng sẽ đọc bằng giọng chung.</p>
            </div>
          ) : (
            <button type="button" className="qt-link" disabled={busy} onClick={addSpeaker}
                    title="Hội thoại nhiều giọng: gõ [A] … [B] … trong lời thoại ở bước 2 rồi chọn giọng cho từng nhân vật">
              + Thêm nhân vật lồng tiếng (hội thoại)
            </button>
          )}
          <label className="qt-field">
            <span>Tiếng gốc của clip</span>
            <select value={originalAudio} disabled={busy}
                    onChange={(e) => setOption({ originalAudio: e.target.value as "duck" | "keep" | "mute" })}>
              <option value="duck">Nhỏ lại dưới giọng đọc</option>
              <option value="mute">Tắt hẳn</option>
              <option value="keep">Giữ nguyên</option>
            </select>
          </label>
          </>)}
          <div className="qt-field">
            <span>Nhạc nền <small>mp3 / m4a / wav · tối đa 20 MB</small></span>
            {bgmMediaId ? (
              <div className="qt-bgm__row">
                <span className="qt-bgm__name" title={bgmName}>🎵 {bgmName || "nhạc nền"}</span>
                <select
                  value={String(bgmVolume)}
                  disabled={busy}
                  title="Âm lượng nhạc nền"
                  onChange={(e) => setOption({ bgmVolume: parseFloat(e.target.value) })}
                >
                  {BGM_VOLUMES.map(([v, label]) => <option key={v} value={String(v)}>{label}</option>)}
                </select>
                <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={busy}
                        onClick={() => setOption({ bgmMediaId: undefined, bgmName: undefined })}>
                  Bỏ nhạc
                </button>
              </div>
            ) : (
              <div className="qt-bgm__row">
                <label className="qt-btn qt-btn--ghost qt-btn--small qt-bgm__pick">
                  <input
                    type="file"
                    accept="audio/mpeg,audio/mp4,audio/x-m4a,audio/wav,.mp3,.m4a,.wav"
                    disabled={busy || bgmUploading || !exp}
                    onChange={(e) => { void pickMusic(e.target.files?.[0]); e.target.value = ""; }}
                  />
                  {bgmUploading ? "Đang tải lên…" : "🎵 Chọn nhạc nền"}
                </label>
                <small className="qt-hint">Không bắt buộc — nhạc lặp suốt clip, nhỏ dần ở cuối.</small>
              </div>
            )}
          </div>
          {!voiceless && <SubtitleField value={subChoiceOf(exp?.data)} disabled={busy} onChange={(key) => setOption(subChoicePatch(key))}
                                       reveal={exp?.data.subReveal} onReveal={(r) => setOption({ subReveal: r })} />}
          <Smooth60Field data={exp?.data} disabled={busy} onChange={setOption} />
        </div>

        <OverlayEditor exp={exp} busy={busy} setOption={setOption} productName={productName} price={price} />

        <button
          type="button"
          className="qt-btn qt-btn--accent qt-btn--big"
          disabled={busy || sending || clips.length === 0}
          onClick={() => { setSending(true); void exportClip().finally(() => setSending(false)); }}
        >
          {busy || sending ? (voiceless ? "Đang ghép…" : "Đang ghép + lồng tiếng…") : hasMedia(exp) ? "Ghép lại" : "Ghép video hoàn chỉnh"}
        </button>
        {exp?.data.error && <div className="product-form__error">{String(exp.data.error)}</div>}
      </section>
      )}

      <section className="qt-card qt-card--result">
        <div className="qt-card__eyebrow">Kết quả</div>
        <h3 className="qt-card__title">Clip hoàn chỉnh</h3>
        {exp && hasMedia(exp) ? (
          <>
            <video className="qt-result" src={mediaUrl(exp.data.mediaId as string)} controls playsInline />
            <a className="qt-btn qt-btn--accent" href={mediaUrl(exp.data.mediaId as string)}
               download={`${boardName || "clip"}.mp4`}
               onClick={() => { if (boardId !== null) patchBoardData(boardId, { quicktool: { downloaded_at: Date.now() } }).catch(() => {}); }}>
              ⬇ Tải về đăng TikTok
            </a>
            {(fbOn || postsOn) && <div className="qt-result__share">
              {fbOn && <button type="button" className="qt-btn qt-btn--schedule" onClick={() => setScheduling(true)}
                      title="Chọn giờ đăng lên kênh; kênh có Facebook Page kết nối thì tự đăng">📅 Lên lịch đăng</button>}
              {postsOn && <button type="button" className="qt-btn qt-btn--publish" disabled={boardId === null} onClick={() => navigate(`/posts?clip=${boardId}`)}
                      title="Sang trang Bài viết Facebook với video clip gắn sẵn: chọn kiểu bài, AI viết theo lời thoại clip, rồi Đăng ngay (bài viết / Reel) hoặc Lên lịch">{fbOn ? "✍️ Viết bài & đăng" : "✍️ Viết bài"}</button>}
            </div>}
            {scheduling && boardId !== null && (
              <ScheduleDialog target={{ kind: "clip", boardId, channelId, title: boardName || `Clip #${boardId}` }}
                              onClose={() => setScheduling(false)} onSaved={() => setScheduling(false)} />
            )}
          </>
        ) : (
          <div className="qt-result qt-result--empty">
            {busy ? "Đang xử lý… (giọng đọc 2–4 s/câu, ghép vài chục giây)" : "Chưa có — bấm \"Ghép video hoàn chỉnh\"."}
          </div>
        )}

        <div className="qt-cover">
          <div className="qt-cover__head">
            <h4>Ảnh bìa</h4>
            <small>1080×1920, chữ in lên ảnh cảnh</small>
          </div>
          {sceneImages.length === 0 ? (
            <p className="qt-hint">Chưa có ảnh nào để làm bìa — upload ảnh sản phẩm ở bước 1 hoặc tạo ảnh cảnh ở bước 3.</p>
          ) : (
            <>
              <label className="qt-field">
                <span>Tiêu đề trên ảnh</span>
                <input
                  type="text"
                  maxLength={200}
                  value={title}
                  placeholder="ví dụ: Áo thun cotton mát lạnh – giảm 50%"
                  onChange={(e) => setCoverTitle(e.target.value)}
                />
              </label>
              <label className="qt-field">
                <span>Dòng phụ <small>không bắt buộc</small></span>
                <input
                  type="text"
                  maxLength={120}
                  value={coverSubtitle}
                  placeholder="ví dụ: Mua ngay kẻo hết"
                  onChange={(e) => setCoverSubtitle(e.target.value)}
                />
              </label>
              <div className="qt-cover__scenes">
                {sceneImages.map((s) => (
                  <button
                    key={s.mediaId}
                    type="button"
                    className={"qt-cover__scene" + (s.mediaId === selectedScene ? " is-selected" : "")}
                    title={s.title}
                    onClick={() => setCoverScene(s.mediaId)}
                  >
                    <img src={mediaUrl(s.mediaId)} alt={s.title} loading="lazy" />
                  </button>
                ))}
              </div>
              <div className="qt-cover__actions">
                <select value={coverStyle} onChange={(e) => setCoverStyle(e.target.value as CoverStyle)}>
                  {COVER_STYLES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
                <button
                  type="button"
                  className="qt-btn qt-btn--small"
                  disabled={coverBusy || boardId === null || !selectedScene || !title.trim()}
                  onClick={() => void makeCover()}
                >
                  {coverBusy ? "Đang tạo…" : coverMediaId ? "Tạo lại ảnh bìa" : "Tạo ảnh bìa"}
                </button>
              </div>
              {coverMediaId && (
                <>
                  <img className="qt-cover__preview" src={mediaUrl(coverMediaId)} alt="Ảnh bìa" />
                  <a className="qt-btn qt-btn--small" href={mediaUrl(coverMediaId)} download={`${boardName || "clip"}-bia.png`}>
                    ⬇ Tải ảnh bìa
                  </a>
                </>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
