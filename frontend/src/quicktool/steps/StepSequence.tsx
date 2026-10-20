import { useRef, useState } from "react";
import { mediaUrl } from "../../api/client";
import { useGenerationStore } from "../../store/generation";
import { useQuicktoolStore } from "../../store/quicktool";
import { hasMedia, isBusy, type ClipRoles } from "../roles";

/**
 * Step 4 of a drama clip — the play order. Beat stills come from step 3;
 * the user splices their own footage (an interview, a screen recording)
 * after any item, moves items up and down, and drops what should not play.
 */
export function StepSequence({ roles }: { roles: ClipRoles }) {
  const sequenceItems = useQuicktoolStore((s) => s.sequenceItems);
  const moveSequenceItem = useQuicktoolStore((s) => s.moveSequenceItem);
  const removeSequenceItem = useQuicktoolStore((s) => s.removeSequenceItem);
  const setSequenceKeepAudio = useQuicktoolStore((s) => s.setSequenceKeepAudio);
  const insertClip = useQuicktoolStore((s) => s.insertClip);
  const restoreSequence = useQuicktoolStore((s) => s.restoreSequence);
  const items = sequenceItems();
  const [inserting, setInserting] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const afterRef = useRef<number>(-1);
  const stillsMissing = roles.scenes.filter((s) => !hasMedia(s.image)).length;
  const notListed = roles.scenes.filter((s) => !items.some((it) => it.node.id === s.image.id)).length;

  function pickInsert(afterIndex: number) {
    afterRef.current = afterIndex;
    fileRef.current?.click();
  }

  return (
    <div className="qt-step">
      <section className="qt-card">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Bước 4</div>
            <h3 className="qt-card__title">Sắp xếp & chèn clip</h3>
          </div>
          <button type="button" className="qt-btn qt-btn--accent" onClick={() => pickInsert(items.length - 1)} disabled={inserting !== null}>
            {inserting !== null ? "Đang tải clip…" : "➕ Chèn clip vào cuối"}
          </button>
        </div>
        <p className="qt-card__hint">
          Thứ tự dưới đây là thứ tự phát. Mỗi ảnh được dựng thành đoạn dài bằng lời kể (chuyển cảnh mờ dần, zoom nhẹ).
          Có video thật (phỏng vấn, màn hình chat…) thì bấm "Chèn clip sau" ở đúng chỗ; clip chèn giữ tiếng gốc trừ khi bạn tắt.
        </p>
        {stillsMissing > 0 && (
          <div className="qt-banner">Còn {stillsMissing} ảnh chưa tạo — quay lại bước 3 tạo đủ trước khi ghép.</div>
        )}
        <ol className="qt-seq">
          {items.map((it, i) => (
            <li key={it.node.id} className={`qt-seq__item${it.kind === "video" ? " qt-seq__item--clip" : ""}`}>
              <span className="qt-seq__num">{i + 1}</span>
              <div className="qt-seq__thumb" onClick={() => hasMedia(it.node) && useGenerationStore.getState().openResultViewer(it.node.id)}>
                {hasMedia(it.node) ? (
                  it.kind === "video"
                    ? <video src={mediaUrl(it.node.data.mediaId as string)} muted preload="metadata" />
                    : <img src={mediaUrl(it.node.data.mediaId as string)} alt="" />
                ) : (
                  <span className="qt-seq__empty">{isBusy(it.node) ? "⏳" : "chưa có ảnh"}</span>
                )}
              </div>
              <div className="qt-seq__body">
                <div className="qt-seq__title">
                  {it.kind === "video" ? "🎞️ " : ""}{it.node.data.title}
                  {it.kind === "image" && typeof it.node.data.caption === "string" && it.node.data.caption && (
                    <small> · {it.node.data.caption}</small>
                  )}
                </div>
                <div className="qt-seq__line">
                  {typeof it.node.data.narration === "string" && it.node.data.narration
                    ? `🎙 ${it.node.data.narration}`
                    : it.kind === "video" ? "Không đọc lời — phát tiếng gốc" : <em>chưa có lời kể (bước 2)</em>}
                </div>
                {it.kind === "video" && (
                  <label className="qt-check">
                    <input type="checkbox" checked={it.keepAudio} onChange={(e) => setSequenceKeepAudio(i, e.target.checked)} />
                    Giữ tiếng gốc của clip này
                  </label>
                )}
              </div>
              <div className="qt-seq__actions">
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={i === 0} onClick={() => moveSequenceItem(i, -1)} title="Lên">↑</button>
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={i === items.length - 1} onClick={() => moveSequenceItem(i, 1)} title="Xuống">↓</button>
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => pickInsert(i)} disabled={inserting !== null} title="Chèn clip của bạn ngay sau mục này">
                  ➕ Chèn clip sau
                </button>
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost qt-btn--danger" onClick={() => removeSequenceItem(i)} title={it.kind === "video" ? "Bỏ clip chèn (xoá khỏi board)" : "Bỏ ảnh này khỏi clip (ảnh vẫn còn ở bước 3)"}>
                  ✕
                </button>
              </div>
            </li>
          ))}
          {items.length === 0 && <li className="qt-empty">Chưa có mục nào.</li>}
        </ol>
        {notListed > 0 && (
          <button type="button" className="qt-btn qt-btn--ghost" onClick={restoreSequence}>
            Đưa {notListed} ảnh đã bỏ trở lại cuối danh sách
          </button>
        )}
        <input
          ref={fileRef}
          type="file"
          accept="video/mp4,video/quicktime,video/webm"
          hidden
          onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            setInserting(afterRef.current);
            await insertClip(f, afterRef.current);
            setInserting(null);
          }}
        />
      </section>
    </div>
  );
}
