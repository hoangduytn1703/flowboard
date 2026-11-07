import { useState } from "react";
import { patchNode, refinePromptApi, tailorBoardApi } from "../../api/client";
import { VoiceOptions, useVoiceGroups } from "../VoiceField";
import { toast } from "../../store/toast";
import { PromptLibraryButtons } from "../PromptLibraryButtons";
import { sceneTagOf } from "../promptTags";
import { clipHooks, type HookVariant } from "../../api/posts";
import { useBoardStore, type FlowNode } from "../../store/board";
import { useQuicktoolStore } from "../../store/quicktool";
import type { ClipRoles } from "../roles";
import { askConfirm } from "../../components/Dialogs";

/** A voice line that fits the 8-second clip. */
const MAX_VOICE_WORDS = 24;

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function saveField(n: FlowNode, key: "prompt" | "narration" | "caption", value: string) {
  const current = typeof n.data[key] === "string" ? (n.data[key] as string) : "";
  if (value === current) return;
  useBoardStore.getState().updateNodeData(n.id, { [key]: value });
  const dbId = parseInt(n.id, 10);
  if (!isNaN(dbId)) patchNode(dbId, { data: { [key]: value } }).catch(() => {});
}

/** The scene's own voice ("" = the voice picked in step 5). `null` in the
 * PATCH deletes the key on the node. */
function saveVoice(n: FlowNode, voice: string) {
  const current = typeof n.data.voice === "string" ? n.data.voice : "";
  if (voice === current) return;
  useBoardStore.getState().updateNodeData(n.id, { voice: voice || undefined });
  const dbId = parseInt(n.id, 10);
  if (!isNaN(dbId)) patchNode(dbId, { data: { voice: voice || null } }).catch(() => {});
}

/** Compact "Giọng: mặc định / Hoài My / …" picker next to a voice line. */
function VoicePick({ node }: { node: FlowNode }) {
  const value = typeof node.data.voice === "string" ? node.data.voice : "";
  return (
    <span className="qt-voice-pick" title="Giọng đọc riêng cho cảnh này (mặc định = giọng chọn ở bước 5)">
      Giọng:
      <select value={value} onChange={(e) => saveVoice(node, e.target.value)}>
        <option value="">mặc định (bước 5)</option>
        <VoiceOptions groups={useVoiceGroups()} short />
      </select>
    </span>
  );
}

/** Step 2 — the script: one row per scene with its image prompt, motion
 * prompt and Vietnamese voice line, all editable in place. `category` (the
 * product's industry) picks which saved prompts "📚 Chọn prompt" offers first. */
export function StepScript({ roles, category, productId = null, boardId = null, voiceless = false }: {
  roles: ClipRoles; category: string | null; productId?: number | null; boardId?: number | null;
  /** "🔇 Không lời": no voice lines, no subtitles — the clip keeps its real sounds. */
  voiceless?: boolean;
}) {
  const writeNarrations = useQuicktoolStore((s) => s.writeNarrations);
  const setVoiceless = useQuicktoolStore((s) => s.setVoiceless);
  const [switching, setSwitching] = useState(false);
  async function switchVoice(on: boolean) {
    const lines = roles.scenes.filter((s) => typeof s.video?.data.narration === "string" && s.video.data.narration.trim()).length;
    if (on && lines > 0 && !await askConfirm(`Chuyển thành clip không lời: bỏ ${lines} lời thoại đang có, khi ghép giữ tiếng động thật của từng video. Tiếp tục?`)) return;
    setSwitching(true);
    await setVoiceless(on);
    setVoiceWords({});
    setRev((r) => r + 1);
    setSwitching(false);
    toast.success(on ? "Đã chuyển thành clip không lời." : "Đã bật lại lời thoại — AI viết lời cho các cảnh còn trống.");
  }
  const [writing, setWriting] = useState(false);
  // "Viết lại kịch bản theo sản phẩm": the box is open / the wish typed / busy.
  const [tailorOpen, setTailorOpen] = useState(false);
  const [tailorWish, setTailorWish] = useState("");
  const [tailoring, setTailoring] = useState(false);
  // Bumped after a rewrite so the uncontrolled fields remount with the new text.
  const [rev, setRev] = useState(0);
  const [refining, setRefining] = useState<string | null>(null);
  // Live word count per voice line (keyed by node id) while the user types;
  // the textarea itself is uncontrolled.
  const [voiceWords, setVoiceWords] = useState<Record<string, number>>({});
  // "✨ Câu mở đầu khác" for scene 1's voice line (A/B the hook).
  const [hooks, setHooks] = useState<HookVariant[] | null>(null);
  const [hooksBusy, setHooksBusy] = useState(false);
  async function loadHooks() {
    if (boardId === null) return;
    setHooksBusy(true);
    try {
      setHooks((await clipHooks(boardId, 5)).variants);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setHooksBusy(false);
    }
  }

  function voiceCount(n: FlowNode): number {
    return voiceWords[n.id] ?? wordCount(typeof n.data.narration === "string" ? n.data.narration : "");
  }

  async function writeAll() {
    const existing = roles.scenes.filter(
      (s) => s.video && typeof s.video.data.narration === "string" && s.video.data.narration.trim(),
    ).length;
    if (existing > 0 && !await askConfirm(`Ghi đè ${existing} lời thoại đang có?`)) return;
    setWriting(true);
    await writeNarrations();
    setVoiceWords({});
    setWriting(false);
  }

  async function tailorAll() {
    if (boardId === null || tailoring) return;
    const made = roles.scenes.filter((s) => s.image.data.mediaId || s.video?.data.mediaId).length;
    if (!await askConfirm(`AI viết lại mô tả ảnh, chuyển động${voiceless ? "" : " và lời thoại"} của ${roles.scenes.length} cảnh theo mô tả + điểm bán của sản phẩm.`
      + (made ? ` ${made} cảnh đã có ảnh/video sẽ cần "Tạo lại" để theo kịch bản mới.` : "")
      + " Mỗi cảnh có \"↺ Về prompt trước đó\" ở nút Tạo lại… nếu không ưng. Tiếp tục?")) return;
    setTailoring(true);
    try {
      const res = await tailorBoardApi(boardId, roles.scenes.map((s) => ({
        image_id: parseInt(s.image.id, 10), video_id: s.video ? parseInt(s.video.id, 10) : null,
      })), tailorWish);
      const board = useBoardStore.getState();
      for (const [id, patch] of Object.entries(res.nodes)) board.updateNodeData(id, patch);
      setVoiceWords({});
      setRev((r) => r + 1);
      setTailorOpen(false);
      toast.success(`Đã viết lại kịch bản ${roles.scenes.length} cảnh theo sản phẩm.` + (made ? " Ảnh/video cũ vẫn giữ — bấm \"Tạo lại\" ở bước 3/4 để làm theo kịch bản mới." : ""));
    } catch (err) {
      toast.error(`Viết lại kịch bản thất bại: ${err instanceof Error ? err.message : "lỗi"}`);
    } finally {
      setTailoring(false);
    }
  }

  async function refine(n: FlowNode, camera?: string) {
    const draft = typeof n.data.prompt === "string" ? n.data.prompt.trim() : "";
    const dbId = parseInt(n.id, 10);
    if (!draft || isNaN(dbId) || refining) return;
    setRefining(n.id);
    try {
      const res = await refinePromptApi(dbId, draft, camera ? { camera } : undefined);
      saveField(n, "prompt", res.prompt);
    } catch (err) {
      useQuicktoolStore.setState({ error: `Viết lại thất bại: ${err instanceof Error ? err.message : "lỗi"}` });
    } finally {
      setRefining(null);
    }
  }

  return (
    <div className="qt-step">
      {roles.script && (
        <section className="qt-card">
          <div className="qt-card__eyebrow">Bước 2</div>
          <h3 className="qt-card__title">Kịch bản</h3>
          <textarea
            className="qt-textarea"
            rows={6}
            defaultValue={(roles.script.data.prompt as string) ?? ""}
            onBlur={(e) => saveField(roles.script!, "prompt", e.target.value)}
          />
        </section>
      )}

      <section className="qt-card">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Bước 2</div>
            <h3 className="qt-card__title">Từng cảnh — mô tả ảnh, chuyển động, lời thoại</h3>
          </div>
          <div className="qt-row">
          {productId !== null && (
            <button type="button" className={`qt-btn${tailorOpen ? " qt-btn--on" : ""}`} disabled={tailoring || roles.scenes.length === 0}
                    onClick={() => setTailorOpen((o) => !o)}
                    title="AI viết lại mô tả ảnh, chuyển động và lời thoại của mọi cảnh theo mô tả + điểm bán của sản phẩm">
              {tailoring ? "AI đang viết…" : "✨ Viết lại kịch bản theo sản phẩm"}
            </button>
          )}
          {!voiceless && (
          <button
            type="button"
            className="qt-btn"
            disabled={writing || roles.scenes.length === 0}
            onClick={writeAll}
            title="AI viết một câu thoại tiếng Việt cho từng cảnh theo kịch bản và sản phẩm (hỏi trước khi ghi đè lời thoại đang có)"
          >
            {writing ? "Đang viết…" : "✨ AI viết lời thoại cho cả clip"}
          </button>
          )}
          </div>
        </div>
        {roles.scenes.some((s) => s.video) && (voiceless ? (
          <div className="qt-voiceless">
            <strong>🔇 Clip không lời</strong>
            <small>Không lồng tiếng, không phụ đề — khi ghép giữ tiếng động thật của từng video (tiếng vải, tiếng máy, tiếng xung quanh).</small>
            <button type="button" className="qt-btn qt-btn--small" disabled={switching} onClick={() => void switchVoice(false)}>
              {switching ? "Đang viết lời…" : "🎙 Thêm lời thoại"}
            </button>
          </div>
        ) : (
          <div className="qt-voiceless">
            <small>Muốn clip chỉ có hình mặc / dùng sản phẩm + tiếng động thật, không giọng đọc?</small>
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={switching} onClick={() => void switchVoice(true)}>
              🔇 Chuyển thành clip không lời
            </button>
          </div>
        ))}
        {tailorOpen && productId !== null && (
          <div className="qt-regen qt-tailor">
            <label className="qt-regen__label" htmlFor="tailor-wish">Muốn nhấn mạnh gì? (không bắt buộc)</label>
            <input id="tailor-wish" className="qt-textarea" value={tailorWish} maxLength={300} autoFocus
                   placeholder="VD: nhấn mạnh giòn rụm và giá, giọng trẻ trung, cảnh cuối có túi zip"
                   onChange={(e) => setTailorWish(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") void tailorAll(); if (e.key === "Escape") setTailorOpen(false); }} />
            <div className="qt-regen__actions">
              <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={tailoring} onClick={() => void tailorAll()}>
                {tailoring ? "AI đang viết… (~15 giây)" : "✨ Viết lại cả clip"}
              </button>
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={tailoring} onClick={() => setTailorOpen(false)}>Huỷ</button>
            </div>
          </div>
        )}
        <p className="qt-card__hint">
          Mô tả ảnh và chuyển động viết bằng tiếng Anh (Flow hiểu tiếng Anh tốt hơn) — gõ tiếng Việt rồi bấm
          "Viết lại" cũng được.{voiceless ? " Clip không lời: tả rõ tiếng động ở cuối mỗi chuyển động (\"Audio: …\")." : " Lời thoại tiếng Việt, ≤ 24 từ để vừa 8 giây."}
        </p>
        <div className="qt-scenes">
          {roles.scenes.map((s) => {
            const ctx = { category, scene: sceneTagOf(s.image.data.title as string | undefined, s.index, roles.scenes.length) };
            return (
            <div key={`${s.image.id}:${rev}`} className="qt-scene-row">
              <div className="qt-scene-row__num">{s.index}</div>
              <div className="qt-scene-row__fields">
                <div className="qt-scene-row__title">{s.image.data.title}</div>
                <label className="qt-field">
                  <span>
                    Mô tả ảnh
                    <button type="button" className="qt-link" disabled={refining !== null}
                            onClick={() => refine(s.image)}>
                      {refining === s.image.id ? "đang viết…" : "✨ Viết lại chuẩn"}
                    </button>
                    <PromptLibraryButtons kind="image" context={ctx}
                      getText={() => (useBoardStore.getState().nodes.find((n) => n.id === s.image.id)?.data.prompt as string) ?? ""}
                      onApply={(t) => saveField(s.image, "prompt", t)} />
                  </span>
                  <textarea
                    className="qt-textarea"
                    rows={3}
                    key={`p-${s.image.id}-${s.image.data.prompt}`}
                    defaultValue={(s.image.data.prompt as string) ?? ""}
                    placeholder="Để trống = AI tự dựng từ sản phẩm + người mẫu"
                    onBlur={(e) => saveField(s.image, "prompt", e.target.value)}
                  />
                </label>
                {s.video ? (
                  <>
                    <label className="qt-field">
                      <span>
                        Chuyển động (8 s)
                        <button type="button" className="qt-link" disabled={refining !== null}
                                onClick={() => refine(s.video!)}>
                          {refining === s.video.id ? "đang viết…" : "✨ Viết lại chuẩn"}
                        </button>
                        <PromptLibraryButtons kind="video" context={ctx}
                          getText={() => (useBoardStore.getState().nodes.find((n) => n.id === s.video!.id)?.data.prompt as string) ?? ""}
                          onApply={(t) => saveField(s.video!, "prompt", t)} />
                      </span>
                      <textarea
                        className="qt-textarea"
                        rows={2}
                        key={`m-${s.video.id}-${s.video.data.prompt}`}
                        defaultValue={(s.video.data.prompt as string) ?? ""}
                        placeholder="Để trống = AI tự dựng chuyển động từ ảnh cảnh"
                        onBlur={(e) => saveField(s.video!, "prompt", e.target.value)}
                      />
                    </label>
                    {!voiceless && (
                    <label className={`qt-field${voiceCount(s.video) > MAX_VOICE_WORDS ? " qt-field--voice-over" : ""}`}
                           htmlFor={`qt-nar-${s.video.id}`}>
                      <span>
                        🎙 Lời thoại
                        <small className="qt-voice-count">{voiceCount(s.video)}/{MAX_VOICE_WORDS} từ</small>
                        {s.index === 1 && (
                          <button type="button" className="qt-link" disabled={hooksBusy} onClick={() => void loadHooks()}
                                  title="AI viết 5 câu mở đầu khác nhau cho cảnh 1 — câu đầu quyết định người xem có ở lại không">
                            {hooksBusy ? "đang nghĩ…" : "✨ 5 câu mở đầu khác"}
                          </button>
                        )}
                        <VoicePick node={s.video} />
                        <PromptLibraryButtons kind="narration" context={ctx}
                          getText={() => (useBoardStore.getState().nodes.find((n) => n.id === s.video!.id)?.data.narration as string) ?? ""}
                          onApply={(t) => { saveField(s.video!, "narration", t); setVoiceWords((p) => ({ ...p, [s.video!.id]: wordCount(t) })); }} />
                      </span>
                      {s.index === 1 && hooks && (
                        <div className="qt-hooks qt-hooks--scene">
                          <div className="qt-hooks__head">
                            <strong>✨ Câu mở đầu cho cảnh 1</strong>
                            <small>Chọn một để thay lời thoại cảnh 1 (lời cũ ghi đè — sửa tay lại được).</small>
                            <button type="button" className="qt-link" onClick={() => setHooks(null)}>đóng</button>
                          </div>
                          <ul>
                            {hooks.map((v, i) => (
                              <li key={i}>
                                <span className="qt-hooks__label">{v.label}</span>
                                <span className="qt-hooks__line">{v.line}</span>
                                <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
                                        onClick={() => { saveField(s.video!, "narration", v.line); setVoiceWords((p) => ({ ...p, [s.video!.id]: wordCount(v.line) })); setHooks(null); toast.success("Đã thay lời thoại cảnh 1."); }}>Dùng</button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <textarea
                        id={`qt-nar-${s.video.id}`}
                        className="qt-textarea"
                        rows={2}
                        maxLength={400}
                        key={`n-${s.video.id}-${s.video.data.narration}`}
                        defaultValue={(s.video.data.narration as string) ?? ""}
                        placeholder="Nói như kể với bạn: trời nắng vậy mà mặc cái này vô là mát liền…"
                        onChange={(e) => setVoiceWords((p) => ({ ...p, [s.video!.id]: wordCount(e.target.value) }))}
                        onBlur={(e) => saveField(s.video!, "narration", e.target.value.trim())}
                      />
                    </label>
                    )}
                  </>
                ) : (
                  // No clip under this still (drama beats): the voice line and
                  // the on-screen headline live on the image itself.
                  <>
                    <label className="qt-field">
                      <span>Tiêu đề hiện trên ảnh</span>
                      <input
                        className="qt-textarea"
                        type="text"
                        maxLength={80}
                        key={`c-${s.image.id}-${s.image.data.caption}`}
                        defaultValue={(s.image.data.caption as string) ?? ""}
                        placeholder="Tiêu đề ngắn (≤ 9 từ), để trống = không hiện"
                        onBlur={(e) => saveField(s.image, "caption", e.target.value.trim())}
                      />
                    </label>
                    <label className="qt-field" htmlFor={`qt-nar-${s.image.id}`}>
                      <span>
                        🎙 Lời kể cho ảnh này
                        <VoicePick node={s.image} />
                      </span>
                      <textarea
                        id={`qt-nar-${s.image.id}`}
                        className="qt-textarea"
                        rows={3}
                        maxLength={600}
                        key={`n-${s.image.id}-${s.image.data.narration}`}
                        defaultValue={(s.image.data.narration as string) ?? ""}
                        placeholder="Theo bài viết, …"
                        onBlur={(e) => saveField(s.image, "narration", e.target.value.trim())}
                      />
                    </label>
                  </>
                )}
              </div>
            </div>
            );
          })}
          {roles.scenes.length === 0 && <div className="qt-empty">Board chưa có cảnh nào.</div>}
        </div>
        {roles.scenes.length > 0 && !voiceless && (
          <p className="qt-card__hint">
            Hội thoại: gõ <code>[A]</code> … <code>[B]</code> … trong một lời thoại rồi chọn giọng cho A/B ở bước 5.
          </p>
        )}
      </section>
    </div>
  );
}
