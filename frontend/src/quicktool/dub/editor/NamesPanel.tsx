import type { DubName } from "../../../api/dub";

export interface NamesCtl {
  value: DubName[];
  /** a new glossary (``coalesce`` groups the keystrokes of one field into one undo step) */
  set: (names: DubName[], coalesce?: string) => void;
  /** "✨ AI rà tên riêng" over the lines as they are now */
  check: () => void;
  checking: boolean;
  /** how the AI check went when the video was translated ("" = never ran) */
  note: string;
  /** a voice-over (the reading is used); subtitles only shows no voice */
  voiced: boolean;
}

/**
 * "🔤 Tên riêng" (top of the "📜 Các câu" tab): the proper names a Vietnamese voice would misread — the
 * subtitle shows the left column, the voice reads the right one ("Einstein" → "Anh xtanh"). The AI check fixes
 * the names Google got wrong in the lines (one undo step) and fills the list; both are saved by the next export.
 */
export function NamesPanel({ ctl, readOnly }: { ctl: NamesCtl; readOnly: boolean }) {
  const { value: names } = ctl;
  const edit = (k: number, patch: Partial<DubName>, field: string) =>
    ctl.set(names.map((n, i) => (i === k ? { ...n, ...patch } : n)), `name-${k}-${field}`);
  return (
    <section className="dx-insp__sec dx-names">
      <div className="dx-names__head">
        <strong>🔤 Tên riêng</strong>
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={readOnly || ctl.checking} onClick={ctl.check}
                title="AI (Gemini) đọc cả bản dịch: sửa tên người / hành tinh / địa danh Google dịch sai, và ghi cách đọc tiếng Việt cho tên nước ngoài">
          {ctl.checking ? "AI đang rà…" : "✨ AI rà tên riêng"}
        </button>
      </div>
      <p className="dx-insp__tip">
        Google hay dịch sai tên riêng (Whisper nghe 爱因斯坦 thành 安音斯坦 → “Anyinstein”). AI sửa các câu đó và ghi cách đọc:
        phụ đề hiện chữ bên trái, {ctl.voiced ? "giọng đọc đọc chữ bên phải" : "cột “đọc là” chỉ dùng khi lồng tiếng"}.
      </p>
      {ctl.note && <p className="dx-names__note">{ctl.note}</p>}
      {names.length > 0 ? (
        <ol className="dx-names__list">
          {names.map((n, k) => (
            <li key={k}>
              <input type="text" value={n.write} maxLength={60} disabled={readOnly} aria-label="Phụ đề ghi"
                     placeholder="phụ đề ghi" onChange={(e) => edit(k, { write: e.target.value }, "w")} />
              <span aria-hidden>→</span>
              <input type="text" value={n.say} maxLength={80} disabled={readOnly} aria-label="Giọng đọc là"
                     placeholder="đọc là (âm tiết Việt)" onChange={(e) => edit(k, { say: e.target.value }, "s")} />
              <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={readOnly} title="Bỏ tên này"
                      onClick={() => ctl.set(names.filter((_, i) => i !== k))}>🗑</button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="dx-insp__empty">Chưa có tên nào — bấm “✨ AI rà tên riêng” hoặc thêm tay.</p>
      )}
      <button type="button" className="qt-link" disabled={readOnly || names.length >= 80}
              onClick={() => ctl.set([...names, { write: "", say: "" }])}>＋ Thêm tên</button>
    </section>
  );
}
