import { useState } from "react";
import { patchNode, refinePromptApi } from "../../api/client";
import { useBoardStore, type FlowNode } from "../../store/board";
import { useQuicktoolStore } from "../../store/quicktool";
import type { ClipRoles } from "../roles";

function saveField(n: FlowNode, key: "prompt" | "narration", value: string) {
  const current = typeof n.data[key] === "string" ? (n.data[key] as string) : "";
  if (value === current) return;
  useBoardStore.getState().updateNodeData(n.id, { [key]: value });
  const dbId = parseInt(n.id, 10);
  if (!isNaN(dbId)) patchNode(dbId, { data: { [key]: value } }).catch(() => {});
}

/** Step 2 — the script: one row per scene with its image prompt, motion
 * prompt and Vietnamese voice line, all editable in place. */
export function StepScript({ roles }: { roles: ClipRoles }) {
  const writeNarrations = useQuicktoolStore((s) => s.writeNarrations);
  const [writing, setWriting] = useState(false);
  const [refining, setRefining] = useState<string | null>(null);

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
            onClick={async () => { setWriting(true); await writeNarrations(); setWriting(false); }}
            title="AI viết một câu thoại tiếng Việt cho từng cảnh theo kịch bản và sản phẩm"
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
                    <label className="qt-field qt-field--voice">
                      <span>🎙 Lời thoại</span>
                      <textarea
                        className="qt-textarea"
                        rows={2}
                        maxLength={400}
                        key={`n-${s.video.id}-${s.video.data.narration}`}
                        defaultValue={(s.video.data.narration as string) ?? ""}
                        placeholder="Mọi người ơi, hôm nay mình…"
                        onBlur={(e) => saveField(s.video!, "narration", e.target.value.trim())}
                      />
                    </label>
                  </>
                ) : (
                  <div className="qt-empty">Cảnh này chưa có node video — thêm trong Canvas.</div>
                )}
              </div>
            </div>
          ))}
          {roles.scenes.length === 0 && <div className="qt-empty">Board chưa có cảnh nào.</div>}
        </div>
      </section>
    </div>
  );
}
