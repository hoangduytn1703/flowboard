/**
 * "📱 Xem trên": how the exported video shows inside each app — the phone / player screen, where the video sits
 * (fitted, or cropped like the Facebook / Instagram feeds crop tall videos to 4:5) and the app's own buttons and
 * text drawn over it. A close approximation of each app's usual layout, for checking what gets covered; the apps
 * change their UI now and then. View only: nothing here changes the export.
 */

/** fractions of the device screen */
export interface Rect { x: number; y: number; w: number; h: number }

export type ChromeKind = "icons" | "caption" | "tabs" | "nav" | "header" | "actions" | "controls" | "title";

export interface ChromePart {
  rect: Rect;
  kind: ChromeKind;
  /** what it is, for the warnings ("nút thích / bình luận") */
  label: string;
  /** drawn over the video (the warnings check these); false = outside it (menu bar, post header) */
  over: boolean;
}

export interface PlacedZone {
  /** where the video area is on the screen */
  rect: Rect;
  /** the video inside that area: whole (contain) or cropped to fill (cover) */
  fit: "contain" | "cover";
  /** said under the device when the app crops / shrinks the video */
  note?: string;
}

export interface Platform {
  key: PlatformKey;
  label: string;
  /** device screen width / height */
  screen: number;
  zone(videoAspect: number): PlacedZone;
  chrome(zone: Rect): ChromePart[];
}

export type PlatformKey = "tiktok" | "reels" | "shorts" | "fb_feed" | "ig_feed" | "youtube";

const PHONE = 9 / 19.5;

/** Full-screen vertical players (TikTok, Reels, Shorts): the video fills the screen above the menu bar, whole. */
function fullScreenZone(navH: number, name: string) {
  return (a: number): PlacedZone => {
    const zone = { x: 0, y: 0, w: 1, h: 1 - navH };
    const zoneAspect = PHONE / (1 - navH);
    const note = a > 0.75
      ? `${name} hiện video ${a >= 1 ? "ngang" : "gần vuông"} nhỏ ở giữa màn hình, trên dưới là nền đen — video dọc 9:16 mới phủ kín. Muốn thay phần đen bằng nền riêng: chọn một kiểu ở hàng “Nền” phía trên.`
      : Math.abs(a - zoneAspect) / zoneAspect > 0.08 ? `${name} để video gần kín màn hình (còn dải đen mỏng trên / dưới).` : undefined;
    return { rect: zone, fit: "contain", note };
  };
}

/** Feeds (Facebook, Instagram): under the post header, full width; taller than 4:5 is cropped to 4:5. */
function feedZone(top: number, name: string) {
  return (a: number): PlacedZone => {
    const shown = Math.max(a, 0.8);
    const h = PHONE / shown;  // width 1 (of the screen) → height in screen fractions
    return {
      rect: { x: 0, y: top, w: 1, h },
      fit: a < 0.8 ? "cover" : "contain",
      note: a < 0.79 ? `Bảng tin ${name} cắt video dọc về 4:5 — phần trên và dưới bị che cho tới khi người xem bấm vào video.` : undefined,
    };
  };
}

export const PLATFORMS: Platform[] = [
  {
    key: "tiktok", label: "TikTok", screen: PHONE, zone: fullScreenZone(0.075, "TikTok"),
    chrome: () => [
      { rect: { x: 0.22, y: 0.035, w: 0.56, h: 0.045 }, kind: "tabs", label: "thanh \"Đang theo dõi | Dành cho bạn\"", over: true },
      { rect: { x: 0.84, y: 0.44, w: 0.14, h: 0.44 }, kind: "icons", label: "cột nút thích / bình luận / lưu / chia sẻ", over: true },
      { rect: { x: 0.03, y: 0.77, w: 0.77, h: 0.145 }, kind: "caption", label: "tên kênh + mô tả + nhạc", over: true },
      { rect: { x: 0, y: 0.925, w: 1, h: 0.075 }, kind: "nav", label: "thanh menu", over: false },
    ],
  },
  {
    key: "reels", label: "Facebook / Instagram Reels", screen: PHONE, zone: fullScreenZone(0.07, "Reels"),
    chrome: () => [
      { rect: { x: 0.04, y: 0.035, w: 0.3, h: 0.045 }, kind: "title", label: "chữ \"Reels\"", over: true },
      { rect: { x: 0.85, y: 0.5, w: 0.13, h: 0.38 }, kind: "icons", label: "cột nút thích / bình luận / chia sẻ", over: true },
      { rect: { x: 0.03, y: 0.79, w: 0.79, h: 0.13 }, kind: "caption", label: "tên page + mô tả", over: true },
      { rect: { x: 0, y: 0.93, w: 1, h: 0.07 }, kind: "nav", label: "thanh menu", over: false },
    ],
  },
  {
    key: "shorts", label: "YouTube Shorts", screen: PHONE, zone: fullScreenZone(0.07, "Shorts"),
    chrome: () => [
      { rect: { x: 0.72, y: 0.035, w: 0.25, h: 0.045 }, kind: "title", label: "nút tìm kiếm", over: true },
      { rect: { x: 0.84, y: 0.46, w: 0.14, h: 0.42 }, kind: "icons", label: "cột nút thích / bình luận / chia sẻ", over: true },
      { rect: { x: 0.03, y: 0.8, w: 0.78, h: 0.12 }, kind: "caption", label: "tên kênh + nút Đăng ký + tiêu đề", over: true },
      { rect: { x: 0, y: 0.93, w: 1, h: 0.07 }, kind: "nav", label: "thanh menu", over: false },
    ],
  },
  {
    key: "fb_feed", label: "Facebook bảng tin", screen: PHONE, zone: feedZone(0.2, "Facebook"),
    chrome: (z) => [
      { rect: { x: 0, y: 0, w: 1, h: 0.075 }, kind: "nav", label: "thanh trên của app", over: false },
      { rect: { x: 0, y: 0.08, w: 1, h: 0.115 }, kind: "header", label: "tên page + nội dung bài", over: false },
      { rect: { x: 0, y: Math.min(0.94, z.y + z.h + 0.005), w: 1, h: 0.055 }, kind: "actions", label: "Thích · Bình luận · Chia sẻ", over: false },
    ],
  },
  {
    key: "ig_feed", label: "Instagram bảng tin", screen: PHONE, zone: feedZone(0.15, "Instagram"),
    chrome: (z) => [
      { rect: { x: 0, y: 0, w: 1, h: 0.075 }, kind: "nav", label: "thanh trên của app", over: false },
      { rect: { x: 0, y: 0.08, w: 1, h: 0.065 }, kind: "header", label: "tên tài khoản", over: false },
      { rect: { x: 0, y: Math.min(0.94, z.y + z.h + 0.005), w: 1, h: 0.05 }, kind: "actions", label: "♡ 💬 ↗", over: false },
    ],
  },
  {
    key: "youtube", label: "YouTube (máy tính)", screen: 16 / 9,
    zone: (a) => ({ rect: { x: 0, y: 0, w: 1, h: 1 }, fit: "contain",
                    note: a < 1 ? "YouTube phát video dọc / vuông ở giữa khung ngang, hai bên là nền đen." : undefined }),
    chrome: () => [
      { rect: { x: 0, y: 0, w: 1, h: 0.11 }, kind: "title", label: "tiêu đề video (hiện khi dừng / rê chuột)", over: true },
      { rect: { x: 0, y: 0.875, w: 1, h: 0.125 }, kind: "controls", label: "thanh điều khiển (hiện khi rê chuột)", over: true },
    ],
  },
];

export function platformOf(key: string | null | undefined): Platform | null {
  return PLATFORMS.find((p) => p.key === key) ?? null;
}

/** ``a`` overlaps ``b`` by more than a sliver (fractions). */
export function overlaps(a: Rect, b: Rect): boolean {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0.01 && h > 0.005;
}
