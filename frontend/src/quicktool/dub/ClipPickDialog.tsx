import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { clipThumbUrl, listBoardSummaries, type BoardSummary } from "../../api/client";
import { PageEmpty, PageLoading } from "../PageState";

/** ``title``: a grabbed video's caption in its own language — the dub translates it into the clip's name. */
export interface PickedClip { board_id: number; name: string; media_id: string; title?: string }

/**
 * "🎬 Chọn từ Clip của tôi": finished clips (a video to dub) — the videos cut on "✂️ Cắt video" first, newest first.
 * Up to ``max`` at once (the dubbing queue's room).
 */
export function ClipPickDialog({ max, initial, onPick, onClose }: {
  max: number;
  initial: PickedClip[];
  onPick: (clips: PickedClip[]) => void;
  onClose: () => void;
}) {
  const [boards, setBoards] = useState<BoardSummary[] | null>(null);
  const [query, setQuery] = useState("");
  const [onlyCut, setOnlyCut] = useState(true);
  const [picked, setPicked] = useState<Map<number, PickedClip>>(() => new Map(initial.map((c) => [c.board_id, c])));
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void listBoardSummaries().then((bs) => setBoards(bs.filter((b) => b.summary.export_media))).catch(() => setBoards([]));
    search.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isCut = (b: BoardSummary) => (b.data as { quicktool?: { template_id?: string } } | undefined)?.quicktool?.template_id === "cut_part";
  const cutCount = (boards ?? []).filter(isCut).length;
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (boards ?? [])
      .filter((b) => (!onlyCut || !cutCount || isCut(b)) && (!q || b.name.toLowerCase().includes(q)))
      .sort((a, b) => b.id - a.id)
      .slice(0, 120);
  }, [boards, query, onlyCut, cutCount]);

  function toggle(b: BoardSummary) {
    setPicked((cur) => {
      const next = new Map(cur);
      if (next.has(b.id)) next.delete(b.id);
      else if (next.size < max) next.set(b.id, { board_id: b.id, name: b.name, media_id: String(b.summary.export_media).replace(/^media\//, "") });
      return next;
    });
  }

  return createPortal(
    <div className="project-modal-backdrop" onClick={onClose}>
      <div className="project-modal qt-dubjobs qt-clippick" role="dialog" aria-modal="true" aria-label="Chọn video từ Clip của tôi" onClick={(e) => e.stopPropagation()}>
        <div className="qt-dubjobs__head">
          <div>
            <h3 className="project-modal__title">🎬 Chọn video từ Clip của tôi</h3>
            <small className="qt-card__hint">Clip đã có video · chọn tối đa {max} video một lần · mỗi video thành một video lồng tiếng</small>
          </div>
          <button type="button" className="qt-dubjobs__close" aria-label="Đóng" onClick={onClose}>×</button>
        </div>
        <div className="qt-dubjobs__tools">
          <input ref={search} className="qt-dubjobs__search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Tìm theo tên clip…" />
          {cutCount > 0 && (
            <label className="qt-check"><input type="checkbox" checked={onlyCut} onChange={(e) => setOnlyCut(e.target.checked)} /> Chỉ video đã cắt ({cutCount})</label>
          )}
        </div>
        <div className="qt-dubjobs__body qt-clippick__body">
          {boards === null ? <PageLoading compact text="Đang tải clip…" /> : !shown.length ? (
            <PageEmpty icon="🎬" title="Chưa có clip nào có video" compact>Cắt video ở “✂️ Cắt video” hoặc ghép xong một clip rồi quay lại.</PageEmpty>
          ) : (
            <div className="qt-clippick__grid">
              {shown.map((b) => {
                const on = picked.has(b.id);
                const thumb = clipThumbUrl(b.summary);
                return (
                  <button key={b.id} type="button" className={`qt-clippick__item${on ? " is-on" : ""}`} onClick={() => toggle(b)}
                          disabled={!on && picked.size >= max} title={b.name}>
                    <span className="qt-clippick__thumb">{thumb ? <img src={thumb} alt="" loading="lazy" /> : "🎬"}</span>
                    <span className="qt-clippick__name">{b.name}</span>
                    {on && <span className="qt-clippick__tick">✓</span>}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <div className="qt-dubjobs__bar">
          <span>{picked.size ? `Đã chọn ${picked.size} video` : "Bấm vào video để chọn"}</span>
          <div className="qt-dubjobs__barbtns">
            <button type="button" className="qt-btn qt-btn--ghost" onClick={onClose}>Huỷ</button>
            <button type="button" className="qt-btn qt-btn--accent" disabled={!picked.size} onClick={() => onPick([...picked.values()])}>Dùng {picked.size || ""} video</button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
