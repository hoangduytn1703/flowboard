import { useState } from "react";
import { VOICE_GROUPS, patchNode, refinePromptApi } from "../../api/client";
import { PromptLibraryButtons } from "../PromptLibraryButtons";
import { useBoardStore, type FlowNode } from "../../store/board";
import { useQuicktoolStore } from "../../store/quicktool";
import type { ClipRoles } from "../roles";

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
        {VOICE_GROUPS.map((g) => (
          <optgroup key={g.id} label={g.id === "edge" ? "Edge" : "Gemini"}>
            {g.voices.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </optgroup>
        ))}
      </select>
    </span>
  );
}

/** Step 2 — the script: one row per scene with its image prompt, motion
 * prompt and Vietnamese voice line, all editable in place. */
export function StepScript({ roles }: { roles: ClipRoles }) {
  const writeNarrations = useQuicktoolStore((s) => s.writeNarrations);
  const [writing, setWriting] = useState(false);
  const [refining, setRefining] = useState<string | null>(null);
  // Live word count per voice line (keyed by node id) while the user types;
  // the textarea itself is uncontrolled.
  const [voiceWords, setVoiceWords] = useState<Record<string, number>>({});

  function voiceCount(n: FlowNode): number {
    return voiceWords[n.id] ?? wordCount(typeof n.data.narration === "string" ? n.data.narration : "");
  }

  async function writeAll() {
    const existing = roles.scenes.filter(
      (s) => s.video && typeof s.video.data.narration === "string" && s.video.data.narration.trim(),
    ).length;
    if (existing > 0 && !window.confirm(`Ghi đè ${existing} lời thoại đang có?`)) return;
    setWriting(true);
    await writeNarrations();
    setVoiceWords({});
    setWriting(false);
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
          <button
            type="button"
            className="qt-btn"
            disabled={writing || roles.scenes.length === 0}
            onClick={writeAll}
            title="AI viết một câu thoại tiếng Việt cho từng cảnh theo kịch bản và sản phẩm (hỏi trước khi ghi đè lời thoại đang có)"
          >
            {writing ? "Đang viết…" : "✨ AI viết lời thoại cho cả clip"}
          </button>
        </div>
        <p className="qt-card__hint">
          Mô tả ảnh và chuyển động viết bằng tiếng Anh (Flow hiểu tiếng Anh tốt hơn) — gõ tiếng Việt rồi bấm
          "Viết lại" cũng được. Lời thoại tiếng Việt, ≤ 24 từ để vừa 8 giây.
        </p>
        <div className="qt-scenes">
          {roles.scenes.map((s) => (
            <div key={s.image.id} className="qt-scene-row">
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
                    <PromptLibraryButtons kind="image"
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
                                onClick={() => refine(s.video!, "static")}>
                          {refining === s.video.id ? "đang viết…" : "✨ Viết lại chuẩn"}
                        </button>
                        <PromptLibraryButtons kind="video"
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
                    <label className={`qt-field${voiceCount(s.video) > MAX_VOICE_WORDS ? " qt-field--voice-over" : ""}`}
                           htmlFor={`qt-nar-${s.video.id}`}>
                      <span>
                        🎙 Lời thoại
                        <small className="qt-voice-count">{voiceCount(s.video)}/{MAX_VOICE_WORDS} từ</small>
                        <VoicePick node={s.video} />
                        <PromptLibraryButtons kind="narration"
                          getText={() => (useBoardStore.getState().nodes.find((n) => n.id === s.video!.id)?.data.narration as string) ?? ""}
                          onApply={(t) => { saveField(s.video!, "narration", t); setVoiceWords((p) => ({ ...p, [s.video!.id]: wordCount(t) })); }} />
                      </span>
                      <textarea
                        id={`qt-nar-${s.video.id}`}
                        className="qt-textarea"
                        rows={2}
                        maxLength={400}
                        key={`n-${s.video.id}-${s.video.data.narration}`}
                        defaultValue={(s.video.data.narration as string) ?? ""}
                        placeholder="Mọi người ơi, hôm nay mình…"
                        onChange={(e) => setVoiceWords((p) => ({ ...p, [s.video!.id]: wordCount(e.target.value) }))}
                        onBlur={(e) => saveField(s.video!, "narration", e.target.value.trim())}
                      />
                    </label>
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
          ))}
          {roles.scenes.length === 0 && <div className="qt-empty">Board chưa có cảnh nào.</div>}
        </div>
        {roles.scenes.length > 0 && (
          <p className="qt-card__hint">
            Hội thoại: gõ <code>[A]</code> … <code>[B]</code> … trong một lời thoại rồi chọn giọng cho A/B ở bước 5.
          </p>
        )}
      </section>
    </div>
  );
}
