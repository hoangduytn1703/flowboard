import { useEffect } from "react";
import { DEFAULT_VOICE, VOICES, mediaUrl, patchNode } from "../../api/client";
import { useBoardStore, type FlowboardNodeData } from "../../store/board";
import { useQuicktoolStore } from "../../store/quicktool";
import { hasMedia, isBusy, type ClipRoles } from "../roles";

/** Step 5 — voice options, the clip list, the final file. */
export function StepExport({ roles }: { roles: ClipRoles }) {
  const ensureExportNode = useQuicktoolStore((s) => s.ensureExportNode);
  const exportClip = useQuicktoolStore((s) => s.exportClip);
  const writeNarrations = useQuicktoolStore((s) => s.writeNarrations);
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

  const clips = roles.scenes.filter((s) => s.video && hasMedia(s.video));
  const voiced = clips.filter((s) => typeof s.video!.data.narration === "string" && s.video!.data.narration.trim()).length;
  const voice = exp && typeof exp.data.voice === "string" && exp.data.voice in VOICES ? exp.data.voice : DEFAULT_VOICE;
  const subtitles = exp ? exp.data.subtitles !== false : true;
  const originalAudio = exp?.data.originalAudio ?? "duck";
  const smooth60 = exp?.data.smooth60 === true;
  const busy = isBusy(exp);

  return (
    <div className="qt-step qt-step--two">
      <section className="qt-card">
        <div className="qt-card__eyebrow">Bước 5</div>
        <h3 className="qt-card__title">Ghép & lồng tiếng</h3>
        <div className="qt-stats">
          <div className="qt-stat"><strong>{clips.length}</strong><span>clip sẵn sàng</span></div>
          <div className="qt-stat"><strong>{voiced}</strong><span>có lời thoại</span></div>
          <div className="qt-stat"><strong>~{clips.length * 8}s</strong><span>thời lượng</span></div>
        </div>
        <ol className="qt-cliplist">
          {clips.map((s) => (
            <li key={s.video!.id}>
              <span className="qt-cliplist__num">{s.index}</span>
              <span className="qt-cliplist__title">{s.image.data.title}</span>
              <span className="qt-cliplist__line">
                {typeof s.video!.data.narration === "string" && s.video!.data.narration
                  ? s.video!.data.narration
                  : <em>chưa có lời thoại</em>}
              </span>
            </li>
          ))}
          {clips.length === 0 && <li className="qt-empty">Chưa có video nào — quay lại bước 4.</li>}
        </ol>
        {clips.length > 0 && voiced < clips.length && (
          <button type="button" className="qt-btn qt-btn--ghost" onClick={() => void writeNarrations()}>
            ✨ AI viết lời thoại còn thiếu
          </button>
        )}

        <div className="qt-form">
          <label className="qt-field">
            <span>Giọng đọc</span>
            <select value={voice} disabled={busy} onChange={(e) => setOption({ voice: e.target.value })}>
              {Object.entries(VOICES).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <label className="qt-field">
            <span>Tiếng gốc của clip</span>
            <select value={originalAudio} disabled={busy}
                    onChange={(e) => setOption({ originalAudio: e.target.value as "duck" | "keep" | "mute" })}>
              <option value="duck">Nhỏ lại dưới giọng đọc</option>
              <option value="mute">Tắt hẳn</option>
              <option value="keep">Giữ nguyên</option>
            </select>
          </label>
          <label className="qt-check">
            <input type="checkbox" checked={subtitles} disabled={busy} onChange={(e) => setOption({ subtitles: e.target.checked })} />
            Phụ đề tiếng Việt theo lời thoại
          </label>
          <label className="qt-check">
            <input type="checkbox" checked={smooth60} disabled={busy} onChange={(e) => setOption({ smooth60: e.target.checked })} />
            Mượt 60 fps (chậm, ~15 s xử lý cho mỗi giây video)
          </label>
        </div>

        <button
          type="button"
          className="qt-btn qt-btn--accent qt-btn--big"
          disabled={busy || clips.length === 0}
          onClick={() => void exportClip()}
        >
          {busy ? "Đang ghép + lồng tiếng…" : hasMedia(exp) ? "Ghép lại" : "Ghép video hoàn chỉnh"}
        </button>
        {exp?.data.error && <div className="product-form__error">{String(exp.data.error)}</div>}
      </section>

      <section className="qt-card qt-card--result">
        <div className="qt-card__eyebrow">Kết quả</div>
        <h3 className="qt-card__title">Clip hoàn chỉnh</h3>
        {exp && hasMedia(exp) ? (
          <>
            <video className="qt-result" src={mediaUrl(exp.data.mediaId as string)} controls playsInline />
            <a className="qt-btn qt-btn--accent" href={mediaUrl(exp.data.mediaId as string)}
               download={`${useBoardStore.getState().boardName || "clip"}.mp4`}>
              ⬇ Tải về đăng TikTok
            </a>
          </>
        ) : (
          <div className="qt-result qt-result--empty">
            {busy ? "Đang xử lý… (giọng đọc 2–4 s/câu, ghép vài chục giây)" : "Chưa có — bấm \"Ghép video hoàn chỉnh\"."}
          </div>
        )}
      </section>
    </div>
  );
}
