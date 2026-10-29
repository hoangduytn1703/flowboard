import { useEffect, useState } from "react";
import { reelCheck, type FbFormat, type ReelCheck } from "../../api/schedule";

export interface FormatTarget {
  kind: "post" | "clip";
  postId?: number | null;
  boardId?: number | null;
}

/**
 * "Đăng lên Facebook dạng 📰 Bài viết / 🎬 Reel" for an item with a video.
 * Asks the agent (`/api/schedule/reel-check`) whether the video can be a Reel:
 * shorter than 3 s / no file → Reel greyed out with the reason; longer than the
 * API's documented 90 s etc. → a warning only (the Facebook app takes long Reels);
 * an item with no video shows nothing (it is always a post).
 */
export function FormatPicker({ value, onChange, target, compact = false }: {
  value: FbFormat;
  onChange: (f: FbFormat) => void;
  target: FormatTarget | null;
  compact?: boolean;
}) {
  const [chk, setChk] = useState<ReelCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const kind = target?.kind;
  const postId = target?.postId ?? null;
  const boardId = target?.boardId ?? null;
  useEffect(() => {
    if (!kind || (!postId && !boardId)) { setChk(null); return; }
    let alive = true;
    setChecking(true);
    reelCheck({ kind, postId, boardId })
      .then((c) => { if (alive) setChk(c); })
      .catch(() => { if (alive) setChk(null); })
      .finally(() => { if (alive) setChecking(false); });
    return () => { alive = false; };
  }, [kind, postId, boardId]);
  const reelOff = !!chk && !chk.ok;
  useEffect(() => { if (reelOff && value === "reel") onChange("post"); }, [reelOff, value, onChange]);
  if (chk && !chk.has_video) return null;
  return (
    <div className={`qt-fbformat${compact ? " qt-fbformat--compact" : ""}`}>
      <span className="qt-fbformat__label">{compact ? "Dạng:" : "Đăng lên Facebook dạng"}</span>
      <div className="qt-fbformat__opts" role="radiogroup">
        <button type="button" role="radio" aria-checked={value === "post"} className={`qt-chip${value === "post" ? " qt-chip--on" : ""}`}
                onClick={() => onChange("post")} title="Bài đăng trên trang, kèm video">📰 Bài viết</button>
        <button type="button" role="radio" aria-checked={value === "reel"} className={`qt-chip${value === "reel" ? " qt-chip--on" : ""}`}
                disabled={reelOff || checking} onClick={() => onChange("reel")}
                title={checking ? "Đang kiểm tra video…" : reelOff ? chk?.reason ?? "" : "Reel: hiện ở mục Reels của page"}>🎬 Reel</button>
      </div>
      {reelOff && chk?.reason && <small className="qt-fbformat__why">{chk.reason}</small>}
      {!compact && !reelOff && (
        <small className="qt-fbformat__hint">{value === "reel"
          ? "Reel: video toàn màn hình ở mục Reels của page — chữ bài là chú thích ngắn (AI viết 1–3 dòng), hashtag giữ nguyên."
          : "Bài viết: bài đăng thường trên trang, video nằm dưới nội dung bài."}</small>
      )}
    </div>
  );
}
