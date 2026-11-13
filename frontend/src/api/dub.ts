// Vietnamese dubbing of a foreign short video — `/api/dub` (routes/dub.py,
// services/dub.py): link → Whisper → translation → TTS → subtitles → a clip.
import { api, extractErrorMessage } from "./client";

export interface DubStatus {
  available: boolean;
  reason?: string;
  root: string;
  ytdlp: boolean;
  whisper: boolean;
  /** spleeter models present → "giữ nhạc nền" possible */
  separate: boolean;
  styles: { key: string; label: string }[];
  max_minutes: number;
  /** an NVIDIA card on this machine (false: Whisper hears on the CPU — ``slow_reason`` says so) */
  gpu?: boolean;
  slow_reason?: string;
  default_layout?: DubLayout;
  /** second subtitle engine (Remotion: HTML/CSS subtitles, live preview) usable on this machine */
  remotion?: boolean;
  remotion_reason?: string;
  remotion_styles?: { key: string; label: string }[];
  /** present when Remotion does not run here: the "Gói Remotion" card shows it */
  remotion_addon?: RemotionAddon;
  /** sound-effect sets for the key moments: built-in, and the user's CapCut sounds when learned */
  sfx_sets?: { key: "builtin" | "capcut"; label: string; count: number }[];
  /** who translates: free Google / Microsoft (like VieDub) or the AI set in Settings */
  translators?: { key: DubTranslator; label: string }[];
  /** where the speech AI comes from: VieDub's venv, the "gói lồng tiếng" add-on, or nothing yet */
  runtime?: "viedub" | "addon" | "none";
  /** present when nothing is installed: the add-on card shows it */
  addon?: DubAddon;
}

/** The "gói lồng tiếng" (services/dub_addon.py): Whisper + spleeter + VieNeu installed next to the user's data. */
export interface DubAddon {
  supported: boolean;
  installed: boolean;
  info: { version?: number; installed_at?: string; device?: string; cuda?: boolean; cuda_error?: string; note?: string;
    gpu?: DubGpu | null };
  dir: string;
  gpu: DubGpu | null;
  download_mb: number;
  need_mb: number;
  free_mb: number;
  size_mb?: number;
  running: boolean;
  phase: string;
  progress: number;
  done_mb: number;
  total_mb: number;
  error: string;
  started_at: string | null;
  last: string;
}

/** The "Gói Remotion" (services/remotion_addon.py): Node + Remotion + Chrome Headless Shell for the second subtitle engine. */
export interface RemotionAddon {
  supported: boolean;
  installed: boolean;
  info: { version?: number; node?: string; remotion?: string; installed_at?: string };
  dir: string;
  download_mb: number;
  need_mb: number;
  free_mb: number;
  size_mb?: number;
  running: boolean;
  phase: string;
  progress: number;
  done_mb: number;
  total_mb: number;
  error: string;
  started_at: string | null;
  last: string;
}

export interface DubGpu {
  name: string;
  driver: string;
  vram_mb: number;
  old_driver: boolean;
}

/** "google" = free machine translation, no key / AI quota (the default, like VieDub); "ai" = the AI provider
 * of Settings (Claude / Gemini…: spoken style + a word budget per line, spends that AI's quota; falls back to Google) */
export type DubTranslator = "google" | "ai";

/** "ass" = ffmpeg/libass (the original), "remotion" = services/dub_remotion */
export type DubEngine = "ass" | "remotion";

/** Where the subtitle box sits: (x, y) = bottom-centre as fractions of the frame; scale = font multiplier. */
export interface DubBlur {
  /** top-left corner + size, fractions of the frame */
  x: number;
  y: number;
  w: number;
  h: number;
  /** 1 (very light) … 10 */
  amount: number;
}

/** A line's own placement ("chỉnh riêng câu này"), overriding the clip-wide layout. */
export interface SubLook {
  x?: number;
  y?: number;
  scale?: number;
  w?: number;
}

export interface DubLayout {
  x: number;
  y: number;
  scale: number;
  /** subtitle box width, fraction of the frame width (null = automatic) */
  w?: number | null;
  /** the first blur box (kept for older readers; the boxes are ``blurs``) */
  blur?: DubBlur | null;
  /** softly blurred rectangles for the whole clip — hide the original hard-coded text (several places) */
  blurs?: DubBlur[];
  /** the output format ("Khung xuất"); null = the video's own size */
  canvas?: DubCanvas | null;
  /** shrink the video onto a background (services/dub_decor) */
  frame?: DubFrame | null;
  /** a bouncing sticker (a saved model, an image or GIF) */
  mascot?: DubMascot | null;
  /** "🔤 Chữ": the title, the second title and free text on the picture */
  texts?: DubText[];
  /** brightness / contrast / saturation of the video itself (null = untouched) */
  adjust?: DubAdjust | null;
  /** "Tốc độ": the export plays this much faster / slower than the source (0.8–3, 1 = as it is) */
  speed?: number;
  /** "Âm lượng": the export's sound this much louder / quieter (0–3, 1 = as it is) */
  volume?: number;
  /** ffmpeg subtitles' lettering: bold, outline / box thickness, colours (null = the style's own) */
  subfont?: DubSubFont | null;
  /** ffmpeg subtitles: "" the whole line at once, "grow" filling in word by word as it is said, "word" one word at a time */
  reveal?: SubReveal;
}

export type SubReveal = "" | "grow" | "word";
/** mirrors services/dub.REVEALS */
export const SUB_REVEALS: { key: SubReveal; label: string }[] = [
  { key: "", label: "Cả câu hiện một lúc" },
  { key: "grow", label: "Hiện dần từng chữ (nói tới đâu hiện tới đó)" },
  { key: "word", label: "Từng chữ một" },
];
export const normReveal = (v: unknown): SubReveal => (v === "grow" || v === "word" ? v : "");

/** mirrors services/dub.normalize_subfont: ``border`` × the style's own outline width (or box padding), 0–2.5 */
export interface DubSubFont {
  bold: boolean;
  border: number;
  border_color: string | null;
  color: string | null;
}
export const SUBFONT_BORDER_MAX = 2.5;
const HEX = /^#[0-9a-fA-F]{6}$/;
export function normSubFont(raw: Partial<DubSubFont> | null | undefined): DubSubFont | null {
  if (!raw || typeof raw !== "object") return null;
  const b = typeof raw.border === "number" && Number.isFinite(raw.border) ? Math.min(SUBFONT_BORDER_MAX, Math.max(0, raw.border)) : 1;
  const out: DubSubFont = {
    bold: raw.bold !== false,
    border: Math.round(b * 100) / 100,
    border_color: typeof raw.border_color === "string" && HEX.test(raw.border_color) ? raw.border_color.toLowerCase() : null,
    color: typeof raw.color === "string" && HEX.test(raw.color) ? raw.color.toLowerCase() : null,
  };
  return out.bold && out.border === 1 && !out.border_color && !out.color ? null : out;
}
export const SPEED_MIN = 0.8, SPEED_MAX = 3;
export const SPEED_MARKS = [0.8, 1, 1.5, 2, 2.5, 3];
/** mirrors services/dub.normalize_speed */
export function normSpeed(v: unknown): number {
  const n = typeof v === "number" && Number.isFinite(v) ? Math.round(Math.min(SPEED_MAX, Math.max(SPEED_MIN, v)) * 100) / 100 : 1;
  return Math.abs(n - 1) < 0.005 ? 1 : n;
}
export const VOLUME_MAX = 3;
export const VOLUME_MARKS = [0, 1, 2, 3];
/** mirrors services/dub.normalize_volume */
export function normVolume(v: unknown): number {
  const n = typeof v === "number" && Number.isFinite(v) ? Math.round(Math.min(VOLUME_MAX, Math.max(0, v)) * 100) / 100 : 1;
  return Math.abs(n - 1) < 0.005 ? 1 : n;
}
export const volumeLabel = (v: number) => (v === 0 ? "tắt tiếng" : `${Math.round(v * 100)}%`);
export const speedLabel = (v: number) => `${String(Math.round(v * 100) / 100).replace(".", ",")}×`;

/** "title" / "subtitle" = the two lines typed when a video is cut (each clip its own words); "text" = free text. */
export type TextRole = "title" | "subtitle" | "text";
export interface DubText {
  role: TextRole;
  /** off = kept in the editor, not drawn */
  on: boolean;
  text: string;
  /** the centre of the text, fractions of the frame */
  x: number;
  y: number;
  /** × the subtitle base size, 0.5–4 */
  size: number;
  color: string;
  /** the box behind the text; "" = none (the text gets an outline) */
  bg: string;
  /** the widest a line may be, fraction of the frame width */
  w: number;
  bold: boolean;
  /** "Độ đậm" when bold is on: 0.3–2.5, 1 = the bold face as it is */
  weight: number;
  italic: boolean;
  underline: boolean;
  /** 0 = the whole clip, else only its first seconds */
  secs: number;
}
export const MAX_TEXTS = 8;
export const TEXT_ROLE_LABEL: Record<TextRole, string> = { title: "Tiêu đề", subtitle: "Tiêu đề phụ", text: "Chữ" };
export const TEXT_DEFAULTS: Record<TextRole, Pick<DubText, "x" | "y" | "size" | "color" | "bg">> = {
  title: { x: 0.5, y: 0.09, size: 1.5, color: "#ffffff", bg: "#e5322d" },
  subtitle: { x: 0.5, y: 0.17, size: 1.1, color: "#141414", bg: "#ffffff" },
  text: { x: 0.5, y: 0.5, size: 1.2, color: "#ffffff", bg: "" },
};
const r3 = (v: number) => Math.round(v * 1000) / 1000;
const within = (v: unknown, lo: number, hi: number, def: number) => {
  const n = typeof v === "number" ? v : Number.NaN;
  return Number.isFinite(n) ? r3(Math.min(hi, Math.max(lo, n))) : def;
};
const hexOr = (v: unknown, def: string) => (typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v) ? v.toLowerCase() : def);
/** One text layer in the agent's shape (services/dub._norm_text) — the words stay as typed. */
export function normText(raw: Partial<DubText> | null | undefined): DubText {
  const role: TextRole = raw?.role === "title" || raw?.role === "subtitle" ? raw.role : "text";
  const d = TEXT_DEFAULTS[role];
  return {
    role, on: raw?.on ?? true, text: String(raw?.text ?? ""),
    x: within(raw?.x, 0.02, 0.98, d.x), y: within(raw?.y, 0.03, 0.97, d.y), size: within(raw?.size, 0.5, 4, d.size),
    color: hexOr(raw?.color, d.color), bg: raw?.bg === undefined ? d.bg : raw.bg ? hexOr(raw.bg, "") : "",
    w: within(raw?.w, 0.2, 0.96, 0.86), bold: raw?.bold ?? true, weight: within(raw?.weight, 0.3, 2.5, 1), italic: raw?.italic ?? false, underline: raw?.underline ?? false,
    secs: within(raw?.secs, 0, 3600, 0),
  };
}
export function normTexts(raw: Partial<DubText>[] | null | undefined): DubText[] {
  const seen = new Set<string>();
  return (raw ?? []).map(normText).map((t) => {
    if (t.role === "text") return t;
    if (seen.has(t.role)) return { ...t, role: "text" as TextRole };
    seen.add(t.role);
    return t;
  }).slice(0, MAX_TEXTS);
}
/** The editor always lists a title and a second title (off until switched on): a clip that never had them gets
 * the two slots with the words it was cut with ("" when it has none). */
export function withTextSlots(texts: DubText[], title: string, subtitle: string): DubText[] {
  const slot = (role: TextRole, text: string) => texts.find((t) => t.role === role) ?? normText({ role, on: false, text });
  return [slot("title", title), slot("subtitle", subtitle), ...texts.filter((t) => t.role === "text")].slice(0, MAX_TEXTS);
}
/** Text layers coming from another clip (a saved look): place, size and colours are theirs; a title / second
 * title keeps THIS clip's words — mirrors services/dub.carry_texts. */
export function carryTexts(theirs: DubText[], own: DubText[], title: string, subtitle: string): DubText[] {
  const mine = (role: TextRole) => own.find((t) => t.role === role)?.text || (role === "title" ? title : subtitle);
  return theirs.map((t) => (t.role === "text" ? t : { ...t, text: mine(t.role) }));
}

export interface DubAdjust { brightness: number; contrast: number; saturation: number }
export const NO_ADJUST: DubAdjust = { brightness: 1, contrast: 1, saturation: 1 };
export const ADJUST_RANGE: Record<keyof DubAdjust, [number, number]> = { brightness: [0.4, 1.8], contrast: [0.5, 1.6], saturation: [0, 2] };
/** null when nothing is changed — mirrors services/dub.normalize_adjust */
export function normAdjust(raw: Partial<DubAdjust> | null | undefined): DubAdjust | null {
  if (!raw) return null;
  const out: DubAdjust = {
    brightness: within(raw.brightness, ...ADJUST_RANGE.brightness, 1), contrast: within(raw.contrast, ...ADJUST_RANGE.contrast, 1),
    saturation: within(raw.saturation, ...ADJUST_RANGE.saturation, 1),
  };
  return Object.values(out).every((v) => Math.abs(v - 1) < 0.005) ? null : out;
}

export interface DubFrame {
  /** size of the video inside the frame, 0.6–1 */
  scale: number;
  bg: "blur" | "color" | "image";
  /** the background picture (bg "image"): an AI artwork or the seller's own */
  bg_image?: string;
  color: string;
  /** border width as a share of the frame height, 0–0.03 */
  border: number;
  border_color: string;
}

export interface DubMascot {
  media_id: string;
  /** bottom-centre of the sticker, fractions of the frame */
  x: number;
  y: number;
  /** height as a share of the frame height, 0.08–0.6 */
  size: number;
  motion: "dance" | "bounce" | "sway" | "none";
  shape: "circle" | "plain";
}

export const DEFAULT_LAYOUT: DubLayout = { x: 0.5, y: 0.8, scale: 1, blur: null, blurs: [], canvas: null, frame: null, mascot: null };

export type CanvasAspect = "9:16" | "16:9" | "4:3" | "3:4" | "1:1" | "4:5";
/** a video of another shape goes into the format: whole over a background (a blurred copy of itself, black, a colour,
 * a grid, an uploaded picture / video) — or cropped to fill */
export type CanvasFit = "blur" | "black" | "color" | "grid" | "image" | "video" | "crop";
export interface DubCanvas {
  aspect: CanvasAspect;
  fit: CanvasFit;
  /** where "crop" cuts, or where the whole video sits along the free side, 0–1 (0.5 = centre) */
  pos: number;
  /** the whole video's size in the format, 0.5–1 (smaller = background all round) */
  scale: number;
  /** background colour (and the grid's), grid line colour, grid cell (share of the width) */
  color: string;
  line: string;
  cell: number;
  /** the uploaded picture / video of an "image" / "video" background */
  media_id: string;
  /** a background format: the video cut to this shape first ("Cắt 4:3" on a 9:16 screen); "" = the whole video */
  inner: CanvasAspect | "";
  /** where either crop cuts, 0–1 (0.5 = the middle) */
  cut: number;
}
/** mirrors services/dub.CANVAS_DEFAULT (the grid of the reference page: dark brown, lighter lines) */
export const CANVAS_DEFAULT = { color: "#211915", line: "#4a3a2e", cell: 0.11, scale: 1 };
export const CANVAS_ASPECTS: { key: CanvasAspect; w: number; h: number; hint: string }[] = [
  { key: "9:16", w: 9, h: 16, hint: "TikTok · Reels · Shorts" },
  { key: "16:9", w: 16, h: 9, hint: "YouTube · màn hình ngang" },
  { key: "4:3", w: 4, h: 3, hint: "Ngang 4:3" },
  { key: "3:4", w: 3, h: 4, hint: "Dọc 3:4" },
  { key: "1:1", w: 1, h: 1, hint: "Vuông · Facebook · Instagram" },
  { key: "4:5", w: 4, h: 5, hint: "Facebook / Instagram dọc" },
];
export const CANVAS_FITS: { key: CanvasFit; label: string; hint: string }[] = [
  { key: "blur", label: "Nền mờ", hint: "Chính video phóng to + làm mờ phía sau" },
  { key: "black", label: "Viền đen", hint: "Nền đen" },
  { key: "color", label: "Màu", hint: "Nền một màu tự chọn" },
  { key: "grid", label: "Lưới", hint: "Nền kẻ ô sọc (như các page phim hoạt hình hay dùng)" },
  { key: "image", label: "Ảnh", hint: "Ảnh nền tự tải lên" },
  { key: "video", label: "Video", hint: "Video nền tự tải lên (tự lặp, không lấy tiếng)" },
  { key: "crop", label: "Phủ kín khung", hint: "Không có nền: phóng video cho kín khung, cắt bớt phần thừa" },
];
/** A format as the agent stores it (services/dub.normalize_canvas): every key, the same order, defaults filled. */
export function normCanvas(raw: Partial<DubCanvas> | null | undefined): DubCanvas | null {
  if (!raw || !CANVAS_ASPECTS.some((a) => a.key === raw.aspect)) return null;
  const num = (v: unknown, lo: number, hi: number, d: number) =>
    typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d;
  const hex = (v: unknown, d: string) => (typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v) ? v.toLowerCase() : d);
  const fit: CanvasFit = CANVAS_FITS.some((f) => f.key === raw.fit) ? (raw.fit as CanvasFit) : "blur";
  const pos = num(raw.pos, 0, 1, 0.5);
  return {
    aspect: raw.aspect as CanvasAspect,
    fit,
    pos,
    scale: num(raw.scale, 0.5, 1, CANVAS_DEFAULT.scale),
    color: hex(raw.color, CANVAS_DEFAULT.color),
    line: hex(raw.line, CANVAS_DEFAULT.line),
    cell: num(raw.cell, 0.04, 0.3, CANVAS_DEFAULT.cell),
    media_id: String(raw.media_id ?? "").trim().slice(0, 64),
    inner: fit !== "crop" && CANVAS_ASPECTS.some((a) => a.key === raw.inner) ? (raw.inner as CanvasAspect) : "",
    // a "crop" fit saved before 31/10 kept its cut in pos
    cut: num(raw.cut, 0, 1, fit === "crop" ? pos : 0.5),
  };
}
export const MAX_BLURS = 8;

const even = (v: number) => Math.max(2, Math.round(v / 2) * 2);
/** The output picture size — mirrors services/dub.canvas_size (the long side kept, the format's shape). */
export function canvasSize(w: number, h: number, canvas: DubCanvas | null | undefined): { w: number; h: number } {
  const a = canvas ? CANVAS_ASPECTS.find((c) => c.key === canvas.aspect) : undefined;
  if (!a || w <= 0 || h <= 0) return { w, h };
  const long = Math.max(w, h);
  const [cw, ch] = a.w >= a.h ? [even(long), even((long * a.h) / a.w)] : [even((long * a.w) / a.h), even(long)];
  if (Math.abs(cw / ch - w / h) < 0.01) return { w, h };
  return { w: cw, h: ch };
}
/** Every blur box of a layout (one saved before 29/10 has a single ``blur``). */
export function layoutBlurs(l: DubLayout): DubBlur[] {
  return l.blurs ?? (l.blur ? [l.blur] : []);
}
export function withBlurs(l: DubLayout, blurs: DubBlur[]): DubLayout {
  const list = blurs.slice(0, MAX_BLURS);
  return { ...l, blurs: list, blur: list[0] ?? null };
}
/** The editor's layout in one shape (the same keys and order every time, so a doc and a job compare equal). */
export function normLayout(raw: Partial<DubLayout> | null | undefined): DubLayout {
  const r = { ...DEFAULT_LAYOUT, ...(raw ?? {}) };
  const blurs = layoutBlurs(r);
  return { x: r.x, y: r.y, scale: r.scale, w: r.w ?? null, blur: blurs[0] ?? null, blurs, canvas: normCanvas(r.canvas),
           frame: r.frame ?? null, mascot: r.mascot ?? null, texts: normTexts(r.texts), adjust: normAdjust(r.adjust), speed: normSpeed(r.speed),
           volume: normVolume(r.volume), subfont: normSubFont(r.subfont), reveal: normReveal(r.reveal) };
}

/** One key moment: the key words are said at ``at`` (line ``line`` of the translation, when known). */
export interface DubHighlightPoint {
  at: number;
  words: string;
  line?: number | null;
}

/** "✨ Nhấn chữ quan trọng": a big key word, a quick push-in and a sound at the key moments (services/key_moments). */
export interface DubHighlights {
  on: boolean;
  words: boolean;
  zoom: boolean;
  sfx: boolean;
  /** "builtin" (pop, whoosh, ding, click) | "capcut" (the sounds learned from the user's CapCut) */
  sfx_set: "builtin" | "capcut";
  /** bottom-centre y of the key word (fraction); null = above the subtitles */
  y: number | null;
  points: DubHighlightPoint[];
  /** how the points were picked: "ai" | "fallback" | "manual" | "" */
  picked: string;
}

export const DEFAULT_HIGHLIGHTS: DubHighlights = { on: false, words: true, zoom: true, sfx: true, sfx_set: "builtin", y: null, points: [], picked: "" };
export const HL_EMPHASIS_S = 1.2;
export const HL_Y_MIN = 0.1, HL_Y_MAX = 0.92;

/** The same shape the agent keeps (services/dub.normalize_highlights), so a doc and a job compare equal. */
export function normHighlights(raw: Partial<DubHighlights> | null | undefined): DubHighlights {
  const h = raw ?? {};
  const points = (h.points ?? [])
    .filter((p) => p && Number.isFinite(p.at) && String(p.words ?? "").trim())
    .map((p) => ({ at: Math.round(Math.max(0, p.at) * 1000) / 1000, words: String(p.words).replace(/\s+/g, " ").trim().slice(0, 40),
                   line: typeof p.line === "number" ? p.line : null }))
    .sort((a, b) => a.at - b.at)
    .slice(0, 40);
  const y = typeof h.y === "number" && Number.isFinite(h.y) ? Math.round(Math.min(HL_Y_MAX, Math.max(HL_Y_MIN, h.y)) * 10000) / 10000 : null;
  return { on: !!h.on, words: h.words !== false, zoom: h.zoom !== false, sfx: h.sfx !== false,
           sfx_set: h.sfx_set === "capcut" ? "capcut" : "builtin", y, points, picked: h.picked ?? "" };
}

/** Where the key word sits (bottom-centre y): its own y, else above the subtitles — mirrors services/dub.emphasis_y. */
export function emphasisY(layout: { y: number }, hl: { y: number | null }): number {
  if (hl.y !== null) return hl.y;
  return Math.round(Math.min(HL_Y_MAX, Math.max(HL_Y_MIN, layout.y - 0.2)) * 10000) / 10000;
}
export const DEFAULT_FRAME: DubFrame = { scale: 0.84, bg: "blur", color: "#111111", border: 0.006, border_color: "#ffd814" };
export const DEFAULT_MASCOT: Omit<DubMascot, "media_id"> = { x: 0.83, y: 0.9, size: 0.26, motion: "dance", shape: "circle" };

export interface DecorChatTurn { role: "user" | "assistant"; text: string }

export interface DecorChatAnswer {
  reply: string;
  /** new frame, "off", or null = unchanged */
  frame: DubFrame | "off" | null;
  /** a new background artwork to draw with Flow (English), "" = none */
  bg_prompt: string;
  mascot: DubMascot | "off" | null;
  /** a new sticker picture to draw with Flow (English), "" = none */
  image_prompt: string;
}

/** "💬 Nhờ AI": design the frame / sticker from a wish (services/decor_ai). */
export function decorChat(body: { message: string; history: DecorChatTurn[]; frame: DubFrame | null; mascot: DubMascot | null;
  orientation: "portrait" | "landscape" | "square" }): Promise<DecorChatAnswer> {
  return post<DecorChatAnswer>("/api/dub/decor/chat", body);
}

/** The sticker picture without its plain background (a new PNG media). */
export function decorCutout(mediaId: string): Promise<{ media_id: string; url: string }> {
  return post<{ media_id: string; url: string }>("/api/dub/decor/cutout", { media_id: mediaId });
}

export interface DecorPreset {
  id: number;
  kind: "frame" | "mascot" | "look";
  name: string;
  data: DubFrame | DubMascot | LookPresetData;
  thumb: string;
  uses: number;
}

/** "★ Mẫu chỉnh sửa": the clip-independent look of a dubbed video (services/dub.normalize_look_preset). */
export interface LookPresetData {
  layout: DubLayout;
  style: string;
  engine: DubEngine;
  /** settings only — the points are each clip's own */
  highlights: DubHighlights;
}

export function listLookPresets(): Promise<DecorPreset[]> {
  return api<DecorPreset[]>("/api/dub/decor/presets?kind=look");
}
export function saveLookPreset(name: string, data: LookPresetData): Promise<DecorPreset> {
  return post<DecorPreset>("/api/dub/decor/presets", { kind: "look", name, data: { ...data, highlights: { ...data.highlights, points: [], picked: "" } } });
}
/** The look new dubbing jobs start with (null = plain defaults). */
export function getDefaultLook(): Promise<{ id: number | null }> {
  return api<{ id: number | null }>("/api/dub/decor/presets/default");
}
export function setDefaultLook(id: number | null): Promise<{ id: number | null }> {
  return api<{ id: number | null }>("/api/dub/decor/presets/default", { method: "PUT", body: JSON.stringify({ id }) });
}

export function listDecorPresets(): Promise<DecorPreset[]> {
  return api<DecorPreset[]>("/api/dub/decor/presets");
}
export function saveDecorPreset(body: { kind: "frame" | "mascot"; name: string; data: DubFrame | DubMascot }): Promise<DecorPreset> {
  return post<DecorPreset>("/api/dub/decor/presets", body);
}
export function markDecorPresetUsed(id: number): Promise<DecorPreset> {
  return post<DecorPreset>(`/api/dub/decor/presets/${id}/use`, {});
}
export function deleteDecorPreset(id: number): Promise<{ ok: true }> {
  return api<{ ok: true }>(`/api/dub/decor/presets/${id}`, { method: "DELETE" });
}

/** An image / animated GIF for the dancing sticker (stays on this machine). */
export async function uploadMascot(file: File): Promise<{ media_id: string; url: string; animated: boolean }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/dub/mascot", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}
export const DEFAULT_BLUR: DubBlur = { x: 0.1, y: 0.62, w: 0.8, h: 0.07, amount: 5 };

/** A picture or a video for the output format's background (stays on this machine; a GIF counts as a video). */
export async function uploadDubBackground(file: File): Promise<{ media_id: string; url: string; kind: "image" | "video" }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/dub/background", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export interface DubSegment {
  start: number;
  end: number;
  /** original speech */
  src: string;
  /** Vietnamese line (editable) */
  text: string;
  /** this line's own placement, if any */
  look?: SubLook | null;
}

export type DubJobStatus = "queued" | "running" | "review" | "rendering" | "done" | "error";

export interface DubJob {
  job_id: string;
  /** unix seconds the job was started */
  started_at?: number;
  /** "Dừng" was pressed and the work is winding down */
  stopping?: boolean;
  /** brief lists only: how many lines (the lines themselves are left out) */
  lines?: number;
  status: DubJobStatus;
  phase: string;
  progress: number;
  url: string | null;
  source_media_id: string | null;
  voice: string;
  keep_bgm: boolean;
  style: string;
  engine: DubEngine;
  layout: DubLayout;
  /** "✨ Nhấn chữ quan trọng" (normHighlights shape) */
  highlights?: DubHighlights;
  width?: number;
  height?: number;
  /** remotion: the dubbed video without subtitles — the live preview plays it */
  nosub_url?: string;
  /** the Vietnamese voice track (editor preview plays it over the source video) */
  voice_url?: string;
  /** the kept background music (keep_bgm) */
  bgm_url?: string;
  channel_id: number | null;
  name: string;
  /** several links dubbed together: the editor lists them side by side */
  batch_id?: string;
  translator?: DubTranslator;
  /** who actually translated: "google" / "microsoft" / "ai", or "google (AI lỗi: …)" */
  translated_by?: string;
  /** "dub" = Vietnamese voice-over; "sub" = subtitles only (the video keeps its own sound) */
  mode?: DubMode;
  /** the subtitles' language (SUB_LANGS) — "vi" unless subtitles only asked for another */
  sub_lang?: SubLang;
  /** "🔤 Tên riêng": the subtitle shows `write`, the voice reads `say` */
  names?: DubName[];
  /** how the AI name check went after the translation ("" = not run) */
  names_note?: string;
  /** lines the voice could not read at the last export and left silent ("" = none) */
  voice_note?: string;
  /** "✂️ Cắt thành nhiều video": the rows being edited and the parts cut so far */
  cuts?: DubCutRow[];
  parts?: DubPart[];
  /** "cut" = one part of a video cut on the "✂️ Cắt video" page (no voice, its own sound, subtitles optional) */
  kind?: string;
  cut?: { session_id: string; run_id: string; index: number; total: number; start: number; end: number;
          source_url?: string | null; source_title?: string; subtitle?: string };
  language: string;
  title: string;
  duration_s: number;
  segments: DubSegment[];
  media_id?: string;
  media_url?: string;
  board_id?: number;
  error?: string;
}

export interface DubStart {
  url?: string | null;
  source_media_id?: string | null;
  voice: string;
  keep_bgm: boolean;
  style: string;
  engine?: DubEngine;
  channel_id?: number | null;
  name?: string;
  auto_render: boolean;
  batch_id?: string;
  /** "★ Mẫu chỉnh sửa" to start with (layout, style, engine, key-moment settings) */
  look_preset_id?: number | null;
  translator?: DubTranslator;
  mode?: DubMode;
  /** subtitles only: their language */
  sub_lang?: SubLang;
}

/** "dub" = Vietnamese voice-over; "sub" = only subtitles, the video keeps its own sound (no voice read: faster) */
export type DubMode = "dub" | "sub";

/** The subtitles' language — mirrors services/dub.SUB_LANGS: Vietnamese, the video's own words ("orig", not
 * translated: an English video gets English subtitles) or another language (Google Dịch). A voice-over reads Vietnamese. */
export type SubLang = "vi" | "orig" | "none" | "en" | "zh" | "ja" | "ko" | "th" | "id" | "es" | "fr" | "de" | "pt" | "ru";
export const SUB_LANGS: { key: SubLang; label: string }[] = [
  { key: "vi", label: "Tiếng Việt" },
  { key: "orig", label: "Ngôn ngữ gốc của video (không dịch)" },
  { key: "en", label: "Tiếng Anh" },
  { key: "zh", label: "Tiếng Trung (giản thể)" },
  { key: "ja", label: "Tiếng Nhật" },
  { key: "ko", label: "Tiếng Hàn" },
  { key: "th", label: "Tiếng Thái" },
  { key: "id", label: "Tiếng Indonesia" },
  { key: "es", label: "Tiếng Tây Ban Nha" },
  { key: "fr", label: "Tiếng Pháp" },
  { key: "de", label: "Tiếng Đức" },
  { key: "pt", label: "Tiếng Bồ Đào Nha" },
  { key: "ru", label: "Tiếng Nga" },
];
export function subLangLabel(key: string | undefined, sourceLang?: string): string {
  if (key === "orig") return `Ngôn ngữ gốc${sourceLang ? ` (${sourceLang})` : ""}`;
  // "✂️ Cắt video": a part starts with no subtitles burned (its lines are kept, ready to be switched on)
  if (key === "none") return "Không có phụ đề";
  return SUB_LANGS.find((l) => l.key === key)?.label ?? "Tiếng Việt";
}
/** The name inside a sentence: "tiếng Anh", "ngôn ngữ gốc (en)". */
export function subLangName(key: string | undefined, sourceLang?: string): string {
  const label = subLangLabel(key, sourceLang);
  return label.charAt(0).toLowerCase() + label.slice(1);
}
/** The lines are already in Vietnamese — the voice-over can read them. */
export function linesAreVietnamese(lang: string | undefined, sourceLang: string | undefined): boolean {
  const base = (sourceLang ?? "").toLowerCase().split(/[-_]/)[0];
  return (lang ?? "vi") === "vi" || base === "vi";
}

/** A proper name a Vietnamese voice would misread: the subtitle shows `write`, the voice reads `say`
 * ("Einstein" → "Anh xtanh"). Mirrors services/dub_names. */
export interface DubName { write: string; say: string }

/** Same shape / order the agent keeps (dub_names.normalize_names), so the editor can tell when it changed. */
export function normNames(raw: DubName[] | undefined): DubName[] {
  const out: DubName[] = [];
  const seen = new Set<string>();
  for (const n of raw ?? []) {
    const write = (n.write ?? "").replace(/\s+/g, " ").trim().slice(0, 60);
    const say = (n.say ?? "").replace(/-/g, " ").replace(/\s+/g, " ").trim().slice(0, 80);
    if (!write || seen.has(write.toLowerCase())) continue;
    seen.add(write.toLowerCase());
    out.push({ write, say: say || write });
  }
  return out;
}

/** "✨ AI rà tên riêng": the lines whose names Google got wrong, corrected, and the names' Vietnamese reading
 * — for the lines as the editor holds them; nothing is saved. */
export function checkDubNames(id: string, lines: string[]): Promise<{ fixes: Record<string, string>; names: DubName[] }> {
  return post(`/api/dub/jobs/${id}/names`, { lines });
}

/** Every line in another language, from the source words (the editor's "Ngôn ngữ phụ đề"; nothing is saved). */
export function dubSubtitleLines(id: string, lang: SubLang): Promise<{ lines: string[]; translated_by: string; lang: SubLang }> {
  return post(`/api/dub/jobs/${id}/subtitles`, { lang });
}

/** One part to cut out of the exported video (seconds). */
export interface DubCutRow {
  start: number;
  end: number;
  title: string;
  /** "✂️ Cắt video" → Tự cắt: a second line under the name (optional) */
  subtitle?: string;
}
/** A part cut out: its own video and clip. */
export interface DubPart extends DubCutRow {
  index: number;
  media_id: string;
  board_id: number;
  at: number;
}
export interface DubSplitState {
  status: "idle" | "running" | "done" | "error";
  phase?: string;
  progress?: number;
  done?: number;
  total?: number;
  error?: string | null;
  parts?: DubPart[];
}
/** "✨ AI gợi ý" (``ai``) / "Chia đều theo câu": rows for parts of about ``target_s`` seconds (not saved). */
export function suggestDubCuts(id: string, targetS: number, ai: boolean): Promise<{ rows: DubCutRow[]; by: "ai" | "even"; note: string }> {
  return post(`/api/dub/jobs/${id}/split/suggest`, { target_s: targetS, ai });
}
/** Keep the rows with the project. */
export async function saveDubCuts(id: string, rows: DubCutRow[]): Promise<{ cuts: DubCutRow[] }> {
  const res = await fetch(`/api/dub/jobs/${id}/cuts`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows }) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}
/** Cut the latest export into one clip per row (runs on the agent; poll ``getDubSplit``). */
export function startDubSplit(id: string, rows: DubCutRow[]): Promise<DubSplitState> {
  return post(`/api/dub/jobs/${id}/split`, { rows });
}
export function getDubSplit(id: string): Promise<DubSplitState> {
  return api<DubSplitState>(`/api/dub/jobs/${id}/split`);
}

export interface DubRender {
  lines?: string[];
  voice?: string;
  style?: string;
  engine?: DubEngine;
  keep_bgm?: boolean;
  name?: string;
  channel_id?: number | null;
  layout?: DubLayout;
  /** timeline editor: new [start, end] for every line */
  timings?: [number, number][];
  /** timeline editor: a line's own placement (null = the clip-wide layout) */
  looks?: (SubLook | null)[];
  /** "✨ Nhấn chữ quan trọng" settings + points (on with no points = the AI picks them while rendering) */
  highlights?: DubHighlights;
  /** switch between voice-over and subtitles only */
  mode?: DubMode;
  /** the language the lines are in (after "Ngôn ngữ phụ đề") */
  sub_lang?: SubLang;
  /** "🔤 Tên riêng" glossary: how the voice reads the foreign names */
  names?: DubName[];
  /** the editor split / merged / added / removed lines: the whole list (replaces lines / timings / looks) */
  cues?: { start: number; end: number; text: string; src: string; look: SubLook | null }[];
  /** the layout is another clip's ("⇪ Áp cho cả loạt"): title / second-title layers keep this clip's own words */
  carried?: boolean;
}

/** "✨ AI chọn chữ quan trọng": the key moments for the lines as the editor holds them, without rendering. */
export function pickDubHighlights(id: string, body: { lines?: string[]; timings?: [number, number][] }): Promise<{ points: DubHighlightPoint[]; picked: string }> {
  return post(`/api/dub/jobs/${id}/highlights/pick`, body);
}

/** Thumbnails across the source video, for the timeline's video track. */
export function dubFilmstripUrl(jobId: string): string {
  return `/api/dub/jobs/${jobId}/filmstrip.jpg`;
}

/** The voice track's waveform; `v` busts the cache after a re-render. */
export function dubWaveUrl(jobId: string, v: string): string {
  return `/api/dub/jobs/${jobId}/wave.png?v=${encodeURIComponent(v)}`;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export function getDubStatus(): Promise<DubStatus> {
  return api<DubStatus>("/api/dub/status");
}

export function getDubAddon(): Promise<DubAddon> {
  return api<DubAddon>("/api/dub/addon");
}

export function installDubAddon(): Promise<DubAddon> {
  return post("/api/dub/addon/install", {});
}

export function cancelDubAddon(): Promise<DubAddon> {
  return post("/api/dub/addon/cancel", {});
}

export function removeDubAddon(): Promise<DubAddon> {
  return post("/api/dub/addon/remove", {});
}

export function getRemotionAddon(): Promise<RemotionAddon> {
  return api<RemotionAddon>("/api/dub/remotion-addon");
}

export function installRemotionAddon(): Promise<RemotionAddon> {
  return post("/api/dub/remotion-addon/install", {});
}

export function cancelRemotionAddon(): Promise<RemotionAddon> {
  return post("/api/dub/remotion-addon/cancel", {});
}

export function removeRemotionAddon(): Promise<RemotionAddon> {
  return post("/api/dub/remotion-addon/remove", {});
}

export function startDub(body: DubStart): Promise<DubJob> {
  return post("/api/dub/jobs", body);
}

export function getDubJob(id: string): Promise<DubJob> {
  return api<DubJob>(`/api/dub/jobs/${id}`);
}

/** "📂 Mở lại video đã làm": which project made this downloaded video. */
export type IdentifyResult =
  | { kind: "dub"; via: "tag" | "fingerprint"; job: DubJob }
  | { kind: "clip"; board_id: number; name: string };

export async function identifyVideo(file: File): Promise<IdentifyResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/dub/identify", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** "🗑 Xoá khỏi danh sách": the jobs and their work folders; exported videos, sources and clips stay. */
export function deleteDubJobs(ids: string[]): Promise<{ deleted: string[]; skipped: { job_id: string; reason: string }[] }> {
  return post("/api/dub/jobs/delete", { ids });
}

/** Every saved job, newest first, without their lines (``lines`` = count) — "Gần đây" + "Xem tất cả". */
export function listDubJobsBrief(): Promise<DubJob[]> {
  return api<DubJob[]>("/api/dub/jobs?all=true&brief=true");
}

export function listDubJobs(): Promise<DubJob[]> {
  return api<DubJob[]>("/api/dub/jobs");
}

/** The jobs of one batch, in the order the links were pasted. */
export function listDubBatch(batchId: string): Promise<DubJob[]> {
  return api<DubJob[]>(`/api/dub/jobs?batch=${encodeURIComponent(batchId)}`);
}

/** Every http(s) link in a pasted text, in order (a Douyin share is "<title> <link>"; several shares = several links). */
export function linksIn(text: string): string[] {
  return Array.from(text.matchAll(/https?:\/\/[^\s<>"'）)]+/g), (m) => m[0].replace(/[.,;:!?]+$/, ""));
}

export function renderDub(id: string, body: DubRender): Promise<DubJob> {
  return post(`/api/dub/jobs/${id}/render`, body);
}

export function stopDub(id: string): Promise<DubJob> {
  return post(`/api/dub/jobs/${id}/stop`, {});
}

/** A local video file, registered like a reference video; returns its media id. */
export async function uploadDubVideo(file: File): Promise<{ media_id: string; duration_s: number | null }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/reference-video/upload", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export function fmtClock(s: number): string {
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}

// ── "📚 Thư viện link": links imported from .txt / .md files, queued for dubbing ──

/** new = never dubbed · waiting = in the library queue · running = its dub job works · review / done / error = that job's state ·
 * other = not a link the dub download takes (listed only) */
export type DubLinkStatus = "new" | "waiting" | "running" | "review" | "done" | "error" | "other";

export interface DubLinkJob {
  job_id: string | null;
  status: string;
  phase: string;
  progress: number;
  title: string;
  board_id: number | null;
  error: string | null;
}

export interface DubLink {
  id: number;
  url: string;
  /** markdown link text or the rest of the line (a Douyin share's title) */
  label: string;
  /** the file it came from */
  source: string;
  /** a site the dub download takes (TikTok / Douyin / YouTube / Instagram / Facebook / X); others are listed only */
  video: boolean;
  status: DubLinkStatus;
  queued: boolean;
  imported_at: string | null;
  /** the dub job / dubbed clip of this video that tells the status */
  job: DubLinkJob | null;
  /** how many times this video was dubbed */
  done_count: number;
  error: string | null;
}

export interface DubLinkLibrary {
  links: DubLink[];
  counts: Partial<Record<DubLinkStatus, number>>;
  total: number;
}

export function listDubLinks(): Promise<DubLinkLibrary> {
  return api<DubLinkLibrary>("/api/dub/links");
}

export function importDubLinks(files: { name: string; text: string }[]): Promise<{
  found: number; added: number[]; existing: number[]; files: { name: string; links: number }[];
}> {
  return post("/api/dub/links/import", { files });
}

export interface DubLinkQueue {
  ids: number[];
  mode: DubMode;
  voice: string;
  keep_bgm: boolean;
  style: string;
  engine: DubEngine;
  channel_id: number | null;
  auto_render: boolean;
  look_preset_id: number | null;
  translator: DubTranslator;
  sub_lang: SubLang;
}

export function queueDubLinks(body: DubLinkQueue): Promise<{ queued: number; skipped: { id: number; reason: string }[]; started: string | null }> {
  return post("/api/dub/links/queue", body);
}

export function unqueueDubLinks(ids: number[]): Promise<{ unqueued: number }> {
  return post("/api/dub/links/unqueue", { ids });
}

export function deleteDubLinks(ids: number[]): Promise<{ deleted: number }> {
  return post("/api/dub/links/delete", { ids });
}

/** .txt / .md (or any plain text file) — the library only reads links out of them */
export function isTextFile(f: File): boolean {
  return /\.(txt|md|markdown|text|csv)$/i.test(f.name) || f.type.startsWith("text/");
}
