// Muse (Meta) as the fallback for scene clips when Flow is slow or drops them.
//
// Muse has no API: it is a chat assistant ("Sunday") on muse.ai. So the
// bridge is manual, and built to be one round trip per clip: one message for
// every scene that needs a clip (Muse makes up to 6 videos per message), the
// scene stills attached in the same order, and the clips it sends back
// dropped onto step 4 in one go. Measured by the seller (26/10): image-to-
// video works, each clip is ~10 s (fixed), a free weekly quota.

export const MUSE_URL = "https://muse.ai";
/** Muse makes at most this many videos per message. */
export const MUSE_MAX_VIDEOS = 6;
/** A Flow clip still running after this long is "slow": the tile offers Muse.
 * Kept clips finish in ~35–120 s (measured 26/10). */
export const FLOW_SLOW_AFTER_S = 150;

export interface MuseScene {
  /** The scene number in the clip (Cảnh n). */
  index: number;
  title: string;
  /** The scene's English motion prompt (the one Flow would get). */
  prompt: string;
}

/** The motion prompt as Muse should read it: one paragraph, no runaway length. */
export function cleanMotionPrompt(prompt: string): string {
  const text = prompt.replace(/\s+/g, " ").trim();
  return text.length > 900 ? `${text.slice(0, 897).trimEnd()}…` : text;
}

/** Scenes split into messages of at most {@link MUSE_MAX_VIDEOS}. */
export function museBatches<T>(scenes: T[]): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < scenes.length; i += MUSE_MAX_VIDEOS) out.push(scenes.slice(i, i + MUSE_MAX_VIDEOS));
  return out;
}

/** File name of the still for the n-th video of a message: the order Muse
 * reads attachments in is the order the seller picks them, and the name says
 * both positions ("ảnh 2 = cảnh 4") so nothing has to be remembered. */
export function stillFileName(slug: string, position: number, sceneIndex: number, ext: string): string {
  return `${slug ? `${slug}-` : ""}anh-${position}-canh-${sceneIndex}.${ext}`;
}

/** The chat message (Vietnamese — Sunday answers in Vietnamese; the motion
 * prompts stay English like every prompt the app sends). */
export function museMessage(product: string, scenes: MuseScene[], part = 1, parts = 1): string {
  const n = scenes.length;
  const name = product.trim() || "sản phẩm";
  const head = [
    `Tạo giúp mình ${n} video dọc 9:16 cho clip bán hàng "${name}"${parts > 1 ? ` (phần ${part}/${parts})` : ""}.`,
    `Mình đính kèm ${n} ảnh theo đúng thứ tự — mỗi ảnh làm 1 video: ${scenes.map((_, i) => `ảnh ${i + 1} → Video ${i + 1}`).join(", ")}.`,
    "",
    "Áp dụng cho mọi video:",
    "- Làm video từ chính ảnh đính kèm (ảnh → video), giữ nguyên sản phẩm: màu, chất liệu, kiểu dáng, chi tiết y như trong ảnh.",
    "- Khung dọc 9:16, chuyển động tự nhiên ở tốc độ thật, máy quay ổn định, không tua nhanh / quay chậm.",
    "- Không chữ, không phụ đề, không logo, không watermark trên hình.",
    "- Không ai nói, không lời thoại, không nhạc — mình lồng tiếng sau.",
    `- Gửi lại đủ ${n} video và ghi rõ "Video 1"${n > 1 ? `, "Video 2"` : ""}… đúng thứ tự.`,
  ];
  const body = scenes.map((s, i) =>
    `Video ${i + 1} (ảnh ${i + 1} · cảnh ${s.index}${s.title ? ` — ${s.title}` : ""}):\n${cleanMotionPrompt(s.prompt) || "Gentle natural motion around the product, camera slowly pushes in."}`);
  return `${head.join("\n")}\n\n${body.join("\n\n")}`;
}

/** Natural order ("video 2" before "video 10"), then download time — the
 * order the seller saved Muse's clips in, which is the order Muse sent them. */
export function orderMuseFiles<T extends { name: string; lastModified: number }>(files: T[]): T[] {
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  return [...files].sort((a, b) => collator.compare(a.name, b.name) || a.lastModified - b.lastModified);
}

/** "1:05" for the tile ("Flow đã chạy 1:05"). */
export function clockOf(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** A clip that is not portrait 9:16 gets cropped or letterboxed when joined. */
export function isPortrait916(width: number, height: number): boolean {
  if (!width || !height) return true;
  return Math.abs(width / height - 9 / 16) / (9 / 16) <= 0.08;
}

export function slugOf(text: string): string {
  return text
    .normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/gi, "d")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}
