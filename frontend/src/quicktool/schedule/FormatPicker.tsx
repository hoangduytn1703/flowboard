import { useEffect, useState } from "react";
import { reelCheck, type FbFormat, type ReelCheck } from "../../api/schedule";

/**
 * "📲 Thêm vào tin": also put the item on the Page's Story when it goes out — its video (the first 60 s; Page
 * stories are at most a minute), its first picture, or for words only a picture of the opening drawn by the agent
 * (the API has no text stories). Only through the Page (auto / "Đăng ngay"): `enabled` false greys it out with `why`.
 * `compact` = a chip for a toolbar.
 */
export function StoryToggle({ value, onChange, enabled = true, why = "", compact = false }: {
  value: boolean;
  onChange: (v: boolean) => void;
  enabled?: boolean;
  why?: string;
  compact?: boolean;
}) {
  const on = value && enabled;
  const tip = enabled ? "Đăng thêm lên Tin của Page (hiện 24 giờ): video — 60 giây đầu —, ảnh đầu của bài, hoặc bài chỉ có chữ thì ảnh chữ trên nền màu." : why;
  if (compact) {
    return (
      <button type="button" className={`qt-chip qt-chip--sm qt-story-chip${on ? " qt-chip--on" : ""}`} aria-pressed={on}
              disabled={!enabled} title={tip} onClick={() => onChange(!value)}>
        📲 {on ? "✓ " : ""}Thêm vào tin
      </button>
    );
  }
  return (
    <label className={`qt-sched-dialog__auto qt-story${enabled ? "" : " is-off"}`} title={tip}>
      <input type="checkbox" checked={on} disabled={!enabled} onChange={(e) => onChange(e.target.checked)} />
      <span><strong>📲 Thêm vào tin</strong><small>{enabled ? "Đăng thêm lên Tin của Page, hiện 24 giờ — video (60 giây đầu), ảnh đầu, hoặc ảnh chữ nếu bài chỉ có chữ." : why}</small></span>
    </label>
  );
}

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
