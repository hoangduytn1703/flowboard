import type { ChromePart, PlatformKey } from "./platforms";

const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

const NAV: Record<string, string[]> = {
  tiktok: ["⌂ Trang chủ", "👥 Bạn bè", "＋", "✉ Hộp thư", "☺ Hồ sơ"],
  reels: ["⌂", "▶", "＋", "🛍", "☺"],
  shorts: ["⌂ Trang chủ", "▶ Shorts", "＋", "▤ Kênh", "☺ Bạn"],
  fb_feed: ["facebook", "＋", "🔍", "💬"],
  ig_feed: ["Instagram", "♡", "✉"],
};

/** The app's own buttons and text over (and around) the video — a mock-up to see what they cover. */
export function DeviceChrome({ platform, parts }: { platform: PlatformKey; parts: ChromePart[] }) {
  return (
    <>
      {parts.map((p, i) => (
        <div key={i} className={`dx-dev__part dx-dev__part--${p.kind}${p.over ? " is-over" : ""}${p.kind === "nav" && p.rect.y < 0.05 ? ` dx-dev__part--topbar dx-dev__part--${platform}` : ""}`} title={p.label}
             style={{ left: pct(p.rect.x), top: pct(p.rect.y), width: pct(p.rect.w), height: pct(p.rect.h) }}>
          {p.kind === "icons" && (
            <>
              <span className="dx-dev__avatar" />
              <span>❤<small>12,3K</small></span>
              <span>💬<small>456</small></span>
              {platform === "tiktok" && <span>🔖<small>1.024</small></span>}
              <span>↗<small>Chia sẻ</small></span>
            </>
          )}
          {p.kind === "caption" && (
            <>
              <strong>@ten_kenh_cua_ban {platform === "shorts" && <em className="dx-dev__sub">Đăng ký</em>}</strong>
              <span>Mô tả video của bạn hiện ở đây, dài thì hiện 2 dòng… #xuhuong</span>
              {platform !== "shorts" && <span>♫ Âm thanh gốc</span>}
            </>
          )}
          {p.kind === "tabs" && <span><b>Đang theo dõi</b>&nbsp;&nbsp;&nbsp;<b className="is-on">Dành cho bạn</b></span>}
          {p.kind === "title" && <span>{platform === "youtube" ? "Tiêu đề video của bạn" : platform === "reels" ? "Reels" : "🔍"}</span>}
          {p.kind === "nav" && (NAV[platform] ?? []).map((n) => <span key={n}>{n}</span>)}
          {p.kind === "header" && (
            <>
              <span className="dx-dev__row"><span className="dx-dev__avatar dx-dev__avatar--sm" /><strong>Tên page của bạn</strong><small>· 2 giờ</small></span>
              {platform === "fb_feed" && <span>Nội dung bài viết đi kèm video hiện ở đây… Xem thêm</span>}
            </>
          )}
          {p.kind === "actions" && (platform === "ig_feed" ? <span>♡&nbsp;&nbsp;💬&nbsp;&nbsp;↗</span>
            : <><span>👍 Thích</span><span>💬 Bình luận</span><span>↗ Chia sẻ</span></>)}
          {p.kind === "controls" && (
            <>
              <span className="dx-dev__progress"><i /></span>
              <span className="dx-dev__row"><span>▶&nbsp;&nbsp;⏭&nbsp;&nbsp;🔊&nbsp;&nbsp;0:12 / 3:35</span><span>⚙&nbsp;&nbsp;▭&nbsp;&nbsp;⛶</span></span>
            </>
          )}
        </div>
      ))}
    </>
  );
}
