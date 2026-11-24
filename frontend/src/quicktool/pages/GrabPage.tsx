import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import { askConfirm, askText } from "../../components/Dialogs";
import { StopButton } from "../../components/StopButton";
import {
  dubGrabNow, stopGrabDub, dismissGrabErrors, deleteGrabFiles, type DubNowOptions,
  addGrabChannel, agoOf, clockOf, dateOf, deleteGrabChannel, deleteGrabPrompt, downloadGrabVideos, editGrabChannel, getGrabState,
  getGrabStatus, getGrabWork, grabAvatarUrl, grabThumbUrl, listGrabChannels, listGrabMarks, listGrabPrompts, listGrabVideos, markGrabUsed,
  pickGrabVideos, saveGrabPrompt, scanAllGrabChannels, scanGrabChannel, setGrabMarks, shortCount, stopGrabDownloads, stopGrabScan,
  type GrabChannel, type GrabMarkTag, type GrabState, type GrabStatus, type GrabToolRun, type GrabVideo, type GrabWork,
} from "../../api/grab";
import { editPath, MAX_EDIT_TOGETHER } from "../../api/edit";
import { MarkMenu, mainMark, markClass, markIcon, markTone } from "../grab/MarkMenu";
import { DubNowDialog, savedDubNow } from "../grab/DubNowDialog";
import { useSettingsStore } from "../../store/settings";
import { useFeature } from "../../lib/features";
import { PageEmpty, PageLoading } from "../PageState";
import { toast } from "../../store/toast";
import "../posts.css";
import "../grab.css";

const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
/** how many videos one press sends on (the tools' own queues) */
const MAX_TO = { cut: 10, dub: 10 } as const;
/** "🎙 Lồng tiếng ngay": the agent hands them to the dubbing queue as room appears, so more at once */
const MAX_DUB_NOW = 30;
/** a dub run still on its way (downloading, waiting, working) */
const dubLive = (r: GrabToolRun | undefined) => r?.state === "running" || r?.state === "downloading";
/** seconds one video still needs, roughly (measured 15/11: a 45 s video dubbed in ~65 s, subtitles only in ~30 s) */
const dubLeft = (v: GrabVideo, r: GrabToolRun) =>
  (r.mode === "sub" ? 10 + 0.5 * (v.duration_s || 60) : 25 + 0.9 * (v.duration_s || 60)) * (1 - Math.min(99, r.progress || 0) / 100);
const TOOL_NAME = { cut: "✂️ Cắt video", dub: "🎙 Lồng tiếng" } as const;
const PAGE = 60;

type Sort = "new" | "views" | "likes" | "long" | "short";
const SORTS: { key: Sort; label: string }[] = [
  { key: "new", label: "Mới đăng nhất" },
  { key: "views", label: "Nhiều lượt xem nhất" },
  { key: "likes", label: "Nhiều tim nhất" },
  { key: "long", label: "Dài nhất" },
  { key: "short", label: "Ngắn nhất" },
];
const VIEW_STEPS = [0, 1_000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000];
const DAY_STEPS: { days: number; label: string }[] = [
  { days: 0, label: "Mọi lúc" }, { days: 7, label: "7 ngày qua" }, { days: 30, label: "30 ngày qua" },
  { days: 90, label: "3 tháng qua" }, { days: 365, label: "1 năm qua" },
];
type Len = "" | "s1" | "s3" | "s10" | "long";
const LENS: { key: Len; label: string }[] = [
  { key: "", label: "Mọi độ dài" }, { key: "s1", label: "Short / tới 1 phút" }, { key: "s3", label: "1 – 3 phút" },
  { key: "s10", label: "3 – 10 phút" }, { key: "long", label: "Trên 10 phút" },
];
type Have = "" | "fresh" | "todo" | "here" | "unused" | "failed";
const HAVES: { key: Have; label: string }[] = [
  { key: "", label: "Tất cả" }, { key: "fresh", label: "Mới từ lần quét cuối" }, { key: "todo", label: "Chưa tải về" },
  { key: "here", label: "Đã tải về" }, { key: "unused", label: "Chưa cắt / lồng tiếng" },
  { key: "failed", label: "Bị lỗi (tải / cắt / lồng tiếng)" },
];
type Tool = "dub" | "cut";
const TOOLS: Tool[] = ["dub", "cut"];
const RUN_TEXT: Record<Tool, { verb: string; done: string; review: string; icon: string }> = {
  dub: { verb: "lồng tiếng", done: "Đã lồng tiếng", review: "Lồng tiếng chờ sửa", icon: "🎙" },
  cut: { verb: "cắt", done: "Đã cắt", review: "Chờ chọn đoạn cắt", icon: "✂️" },
};
/** the tools whose last run from this video failed */
const failedTools = (w: GrabWork[string] | undefined): Tool[] => TOOLS.filter((k) => w?.[k]?.state === "error");
/** something on the card says it failed: a tool's run, or the download itself */
const hasFailure = (v: GrabVideo, w: GrabWork[string] | undefined, dl: string) => failedTools(w).length > 0 || (dl === "" && !!v.download_error);
const PRESET_LIMITS = [30, 60, 100, 200, 500, 1000];
const MAX_LIMIT = 3000;
const PRESET_MARKS = ["Đã xử lý", "Đã đăng", "Để dành", "Bỏ qua"];
/** "" every video · "__none" no label yet · "__any" has a label · otherwise that label */
type MarkFilter = string;
/** how many AI requests the account keeps (the server drops the oldest past this) */
const MAX_PROMPTS = 10;
const promptKey = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

const plain = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
function stored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}
function store(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
}

/** The grid's filters, the AI's pick and the ticked videos, kept for this app session (sessionStorage, 15/11):
 *  going to another page and back finds them as they were; "Bỏ lọc" / "Bỏ kết quả AI" or closing the app clears them. */
const VIEW_KEY = "dflow.grab.view";
interface GridView {
  chan: number | null; tag: string; q: string; minViews: number; days: number; len: Len; kind: "" | "video" | "short"; have: Have;
  aiOnly: boolean; why: [number, string][]; aiNote: string; picked: number[];
}
function savedView(): Partial<GridView> {
  try {
    const raw = window.sessionStorage.getItem(VIEW_KEY);
    return raw ? (JSON.parse(raw) as Partial<GridView>) : {};
  } catch {
    return {};
  }
}
function keepView(v: GridView) {
  try { window.sessionStorage.setItem(VIEW_KEY, JSON.stringify(v)); } catch { /* private mode / full */ }
}

/** Where a video stands: the download in flight (polled) wins over what the list last said. */
function downloadOf(v: GrabVideo, state: GrabState | null): "" | "queued" | "running" | "done" {
  const live = state?.downloads[String(v.id)];
  if (live) return live.status;
  return v.media_id ? "done" : "";
}

function Avatar({ channel, size = 40 }: { channel: GrabChannel; size?: number }) {
  const [broken, setBroken] = useState(false);
  const letter = (channel.name || channel.handle || "?").replace(/^@/, "").charAt(0).toUpperCase();
  return (
    <span className={`gb-avatar gb-avatar--${channel.platform}`} style={{ width: size, height: size, fontSize: size * 0.42 }} aria-hidden="true">
      {channel.has_avatar && !broken
        ? <img src={grabAvatarUrl(channel.id)} alt="" loading="lazy" onError={() => setBroken(true)} />
        : letter}
    </span>
  );
}

function PlatformChip({ platform, label, beta = false }: { platform: string; label: string; beta?: boolean }) {
  const icon = platform === "youtube" ? "▶" : platform === "bilibili" ? "📺" : "♪";
  return (
    <span className={`gb-plat gb-plat--${platform}`}>
      {icon} {label}{beta && <b className="gb-beta" title="Đang thử nghiệm — có thể chưa ổn định">BETA</b>}
    </span>
  );
}

/** "🎙 Lồng tiếng ngay" on a card: the step the video is at, a bar, how many wait in front of it. */
function DubProgress({ run }: { run: GrabToolRun }) {
  const waiting = run.state === "running" && typeof run.ahead === "number" && run.ahead !== null;
  const text = run.state === "downloading" ? (run.phase || "Đang tải video về")
    : waiting ? (run.ahead === 0 ? "Chờ đến lượt — tiếp theo" : run.ahead! >= 99 ? run.phase : `Chờ đến lượt — còn ${run.ahead} video trước`)
      : (run.phase || "Đang lồng tiếng");
  const moving = run.state === "running" && !waiting;
  return (
    <div className={`gb-v__run${moving ? "" : " is-waiting"}`} role="status">
      <div className="gb-v__runtext">
        {moving || run.state === "downloading" ? <span className="gb-spin" aria-hidden="true" /> : <span aria-hidden="true">⏳</span>}
        <span title={text}>{text}</span>
        {moving && <b>{Math.round(run.progress)}%</b>}
      </div>
      <div className="gb-v__runbar"><span style={{ width: `${moving ? Math.max(3, run.progress) : 0}%` }} /></div>
    </div>
  );
}

/** Where a video's dubbing / cut stands (a failure is the red strip on the card instead). */
function RunChip({ tool, run, onOpen }: { tool: Tool; run: GrabToolRun; onOpen: () => void }) {
  const t = RUN_TEXT[tool];
  const [cls, text] =
    run.state === "running" ? ["gb-st--run", `⏳ Đang ${t.verb}${run.progress ? ` ${run.progress}%` : ""}`]
      : run.state === "review" ? ["gb-st--wait", `✏️ ${t.review}`]
        : run.state === "stopped" ? ["", `⏹ ${t.icon} đã dừng`]
          : ["gb-st--ok", `✓ ${t.done}`];
  return (
    <button type="button" className={`gb-st gb-st--btn ${cls}`} onClick={onOpen} title={`${run.phase || t.done} — bấm để mở`}>
      {run.state === "running" && <span className="gb-spin" aria-hidden="true" />}{text}
    </button>
  );
}

/** "Lấy …": the ready-made sizes, every video of the channel (up to the most one scan reads), or any number typed in. */
function LimitPicker({ limit, presets, max, onChange }: { limit: number; presets: number[]; max: number; onChange: (n: number) => void }) {
  const known = presets.includes(limit) || limit === max;
  const [typing, setTyping] = useState(!known);
  const [draft, setDraft] = useState(String(limit));
  useEffect(() => { setDraft(String(limit)); }, [limit]);
  function commit() {
    const n = Math.round(Number(draft));
    if (!Number.isFinite(n) || n <= 0) { setDraft(String(limit)); return; }
    onChange(Math.min(Math.max(n, 5), max));
  }
  return (
    <label className="gb__limit" title={`Mỗi lần quét đọc bấy nhiêu video mới nhất của kênh (YouTube: mỗi mục Video và Shorts). Nhiều nhất ${max} video một lần.`}>
      <span>Lấy</span>
      <select value={typing ? "custom" : String(limit)}
              onChange={(e) => {
                if (e.target.value === "custom") { setTyping(true); return; }
                setTyping(false);
                onChange(Number(e.target.value));
              }}>
        {presets.map((n) => <option key={n} value={n}>{n} video mới nhất</option>)}
        <option value={max}>Tất cả video (tối đa {max})</option>
        <option value="custom">Tự nhập số…</option>
      </select>
      {typing && (
        <input className="gb__limitnum" type="number" min={5} max={max} step={10} value={draft} aria-label="Số video muốn lấy"
               onChange={(e) => setDraft(e.target.value)} onBlur={commit}
               onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} />
      )}
    </label>
  );
}

/**
 * "📡 Cào video kênh": keep source channels (YouTube, TikTok), read their newest videos with views / likes / length /
 * date, filter or let the AI pick by a request, download the picks and send them on to "✂️ Cắt video" / "🎙 Lồng tiếng".
 */
export function GrabPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const canCut = useFeature("cut");
  const canDub = useFeature("dub");
  const [status, setStatus] = useState<GrabStatus | null>(null);
  const [channels, setChannels] = useState<GrabChannel[] | null>(null);
  const [videos, setVideos] = useState<GrabVideo[]>([]);
  const [state, setState] = useState<GrabState | null>(null);
  const [url, setUrl] = useState("");
  const [limit, setLimit] = useState<number>(() => stored("flowboard.grab.limit", 60));
  const [markTags, setMarkTags] = useState<GrabMarkTag[]>([]);
  const [markF, setMarkF] = useState<MarkFilter>(() => stored<MarkFilter>("flowboard.grab.markFilter", ""));
  // the 🏷 menu: the videos it labels and where its button is
  const [markMenu, setMarkMenu] = useState<{ ids: number[]; anchor: DOMRect } | null>(null);
  const [adding, setAdding] = useState(false);
  const [view0] = useState(savedView);  // what this session left here (see VIEW_KEY)
  // which channel is open (null = every channel) and the label filter of the channel list
  const [chan, setChan] = useState<number | null>(view0.chan ?? null);
  const [tag, setTag] = useState(view0.tag ?? "");
  // filters of the video grid
  const [q, setQ] = useState(view0.q ?? "");
  const [sort, setSort] = useState<Sort>(() => stored<Sort>("flowboard.grab.sort", "new"));
  const [minViews, setMinViews] = useState(view0.minViews ?? 0);
  const [days, setDays] = useState(view0.days ?? 0);
  const [len, setLen] = useState<Len>(view0.len ?? "");
  const [kind, setKind] = useState<"" | "video" | "short">(view0.kind ?? "");
  const [have, setHave] = useState<Have>(view0.have ?? "");
  const [shown, setShown] = useState(PAGE);
  const [picked, setPicked] = useState<Set<number>>(() => new Set(view0.picked ?? []));
  // the AI's pick
  const [prompt, setPrompt] = useState<string>(() => stored("flowboard.grab.prompt", ""));
  const [picking, setPicking] = useState(false);
  const [why, setWhy] = useState<Map<number, string>>(() => new Map(view0.why ?? []));
  const [aiNote, setAiNote] = useState(view0.aiNote ?? "");
  const [aiOnly, setAiOnly] = useState(view0.aiOnly ?? false);
  useEffect(() => {
    keepView({ chan, tag, q, minViews, days, len, kind, have, aiOnly, why: Array.from(why.entries()), aiNote, picked: Array.from(picked) });
  }, [chan, tag, q, minViews, days, len, kind, have, aiOnly, why, aiNote, picked]);
  // the account's saved AI requests, newest first
  const [prompts, setPrompts] = useState<string[]>([]);
  // what became of the videos sent on to "🎙 Lồng tiếng" / "✂️ Cắt video" (a failure shows on the card)
  const [work, setWork] = useState<GrabWork>({});
  // "tải xong thì chuyển sang …": the videos wanted in a tool that are still downloading
  const [after, setAfter] = useState<{ tool: "cut" | "dub"; ids: number[] } | null>(null);
  // "🎙 Lồng tiếng ngay": the videos the dialog is open for; the ones sent in this visit (the bar counts them)
  const [dubAsk, setDubAsk] = useState<GrabVideo[] | null>(null);
  const [lot, setLot] = useState<number[]>([]);
  const dubVoice = useSettingsStore((s) => s.dubVoice);
  const urlInput = useRef<HTMLInputElement>(null);
  const busyKey = useRef("");

  async function reload() {
    try {
      const [cs, vs, ms] = await Promise.all([listGrabChannels(), listGrabVideos(), listGrabMarks().catch(() => [] as GrabMarkTag[])]);
      setChannels(cs);
      setVideos(vs);
      setMarkTags(ms);
    } catch (e) {
      toast.error(errMessage(e));
      setChannels((c) => c ?? []);
    }
  }
  useEffect(() => {
    void getGrabStatus().then(setStatus).catch(() => undefined);
    void listGrabPrompts().then(setPrompts).catch(() => undefined);
    void reload();
  }, []);

  // ?channel=<id> (the "việc đang chạy" badge, the assistant)
  const wantChannel = params.get("channel");
  useEffect(() => {
    if (!wantChannel) return;
    const id = Number(wantChannel);
    if (id > 0) setChan(id);
    setParams({}, { replace: true });
  }, [wantChannel]); // eslint-disable-line react-hooks/exhaustive-deps

  // scans and downloads in flight: polled; when one ends the lists are read again
  const busy = !!state && (Object.keys(state.scans).length > 0 || Object.keys(state.downloads).length > 0);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const s = await getGrabState().catch(() => null);
      if (!alive || !s) return;
      const key = `${Object.keys(s.scans).sort().join(",")}|${Object.keys(s.downloads).sort().join(",")}`;
      if (key !== busyKey.current) {
        busyKey.current = key;
        void reload();
      }
      setState(s);
    };
    void tick();
    const t = window.setInterval(() => void tick(), busy ? 1500 : 12000);
    return () => { alive = false; window.clearInterval(t); };
  }, [busy]);

  const workBusy = Object.values(work).some((w) => dubLive(w.dub) || w.cut?.state === "running");
  useEffect(() => {
    let alive = true;
    const tick = () => void getGrabWork().then((w) => { if (alive) setWork(w); }).catch(() => undefined);
    tick();
    const t = window.setInterval(tick, workBusy ? 2500 : 30000);
    return () => { alive = false; window.clearInterval(t); };
  }, [workBusy, videos.length]);

  const byId = useMemo(() => new Map((channels ?? []).map((c) => [c.id, c])), [channels]);
  const allTags = useMemo(() => Array.from(new Set((channels ?? []).flatMap((c) => c.tags))).sort((a, b) => a.localeCompare(b, "vi")), [channels]);
  const listed = useMemo(() => (channels ?? []).filter((c) => !tag || c.tags.includes(tag)), [channels, tag]);
  useEffect(() => { if (tag && !allTags.includes(tag)) setTag(""); }, [allTags, tag]);
  useEffect(() => { if (chan !== null && channels && !byId.has(chan)) setChan(null); }, [chan, channels, byId]);

  // ── the grid ─────────────────────────────────────────────────────────────
  const scope = useMemo(() => {
    const ids = new Set(listed.map((c) => c.id));
    return videos.filter((v) => (chan !== null ? v.channel_id === chan : ids.has(v.channel_id)));
  }, [videos, chan, listed]);
  const { filtered, undated } = useMemo(() => {
    const needle = plain(q.trim());
    const since = days ? Date.now() - days * 86400000 : 0;
    let undated = 0;
    const out = scope.filter((v) => {
      if (needle && !plain(v.title).includes(needle)) return false;
      if (minViews && (v.views ?? -1) < minViews) return false;
      if (kind && v.kind !== kind) return false;
      if (len) {
        const d = v.duration_s ?? (v.kind === "short" ? 30 : null);
        if (d === null) return false;
        if (len === "s1" && d > 60) return false;
        if (len === "s3" && (d <= 60 || d > 180)) return false;
        if (len === "s10" && (d <= 180 || d > 600)) return false;
        if (len === "long" && d <= 600) return false;
      }
      const here = downloadOf(v, state) === "done";
      if (have === "fresh" && !v.fresh) return false;
      if (have === "todo" && here) return false;
      if (have === "here" && !here) return false;
      if (have === "unused" && (v.used.cut || v.used.dub)) return false;
      if (have === "failed" && !hasFailure(v, work[String(v.id)], downloadOf(v, state))) return false;
      if (markF === "__none" && v.marks.length) return false;
      if (markF === "__any" && !v.marks.length) return false;
      if (markF && !markF.startsWith("__") && !v.marks.some((m) => m.toLowerCase() === markF.toLowerCase())) return false;
      if (aiOnly && !why.has(v.id)) return false;
      if (since) {
        if (!v.published_at) { undated += 1; return false; }
        if (new Date(v.published_at).getTime() < since) return false;
      }
      return true;
    });
    const time = (v: GrabVideo) => (v.published_at ? new Date(v.published_at).getTime() : 0);
    const dur = (v: GrabVideo) => v.duration_s ?? (v.kind === "short" ? 30 : 0);
    out.sort((a, b) => {
      if (sort === "views") return (b.views ?? -1) - (a.views ?? -1);
      if (sort === "likes") return (b.likes ?? -1) - (a.likes ?? -1);
      if (sort === "long") return dur(b) - dur(a);
      if (sort === "short") return (dur(a) || 1e9) - (dur(b) || 1e9);
      return time(b) - time(a) || a.channel_id - b.channel_id || a.position - b.position;
    });
    return { filtered: out, undated };
  }, [scope, q, minViews, days, len, kind, have, markF, aiOnly, why, sort, state, work]);
  const failedList = useMemo(() => scope.filter((v) => hasFailure(v, work[String(v.id)], downloadOf(v, state))), [scope, work, state]);
  const failedCount = failedList.length;
  // "🎙 Lồng tiếng ngay": what is still on its way, how far this visit's lot is, about how long is left
  const liveDub = useMemo(() => videos.filter((v) => dubLive(work[String(v.id)]?.dub)), [videos, work]);
  const lotTotal = lot.length;
  const lotDone = lot.filter((id) => { const r = work[String(id)]?.dub; return !!r && !dubLive(r); }).length;
  const etaS = liveDub.reduce((s, v) => s + dubLeft(v, work[String(v.id)]!.dub!), 0);
  const etaText = etaS < 50 ? "dưới 1 phút" : `${Math.max(1, Math.round(etaS / 60))} phút`;
  useEffect(() => {  // the lot is over: one line saying how it went, then the bar forgets it
    if (!lot.length || liveDub.length) return;
    const runs = lot.map((id) => work[String(id)]?.dub).filter((r): r is GrabToolRun => !!r);
    if (runs.length < lot.length) return;
    const ok = runs.filter((r) => r.state === "done" || r.state === "review").length;
    const quiet = runs.filter((r) => r.state === "nospeech").length;
    const bad = runs.filter((r) => r.state === "error").length;
    const parts = [`${ok} video xong`, quiet ? `${quiet} video không có lời` : "", bad ? `${bad} video lỗi (bấm ↻ Thử lại trên thẻ)` : ""].filter(Boolean);
    (bad ? toast.warning : toast.success)(`Lồng tiếng: ${parts.join(", ")}.`);
    setLot([]);
  }, [lot, liveDub.length, work]);
  useEffect(() => { setShown(PAGE); }, [chan, tag, q, minViews, days, len, kind, have, markF, aiOnly, sort]);
  const filtersOn = !!(q.trim() || minViews || days || len || kind || have || markF || aiOnly);
  // only search + sort stay in sight; the other filters fold under "Lọc thêm" (open when one of them is on)
  const extraOn = [minViews, days, len, kind, have, markF].filter(Boolean).length;
  const [moreOpen, setMoreOpen] = useState(extraOn > 0);
  function clearFilters() { setQ(""); setMinViews(0); setDays(0); setLen(""); setKind(""); setHave(""); pickMarkFilter(""); setAiOnly(false); }
  function pickMarkFilter(f: MarkFilter) { setMarkF(f); store("flowboard.grab.markFilter", f); }

  // ── video labels ("Đã xử lý", "Đã đăng"…) ───────────────────────────────
  const presets = status?.mark_presets ?? PRESET_MARKS;
  const knownMarks = useMemo(() => {
    const seen = new Set(presets.map((p) => p.toLowerCase()));
    const own = markTags.map((m) => m.tag).filter((t) => !seen.has(t.toLowerCase()));
    return [...presets, ...own];
  }, [presets, markTags]);
  // how many videos of the current channel(s) carry each label — the filter chips
  const markCounts = useMemo(() => {
    const out = new Map<string, number>();
    let none = 0;
    for (const v of scope) {
      if (!v.marks.length) none += 1;
      for (const m of v.marks) out.set(m, (out.get(m) ?? 0) + 1);
    }
    return { per: out, none, any: scope.length - none };
  }, [scope]);
  useEffect(() => {
    if (markF && !markF.startsWith("__") && channels && !knownMarks.some((t) => t.toLowerCase() === markF.toLowerCase())) pickMarkFilter("");
  }, [knownMarks, markF, channels]); // eslint-disable-line react-hooks/exhaustive-deps
  function openMarks(ids: number[], el: HTMLElement) {
    if (!ids.length) return;
    setMarkMenu({ ids, anchor: el.getBoundingClientRect() });
  }
  async function applyMarks(ids: number[], add: string[], remove: string[]) {
    try {
      await setGrabMarks(ids, add, remove);
      const lowAdd = add.map((t) => t.toLowerCase()), lowRemove = remove.map((t) => t.toLowerCase());
      setVideos((list) => list.map((v) => {
        if (!ids.includes(v.id)) return v;
        const kept = v.marks.filter((m) => !lowRemove.includes(m.toLowerCase()) && !lowAdd.includes(m.toLowerCase()));
        return { ...v, marks: [...kept, ...add] };
      }));
      setMarkTags(await listGrabMarks().catch(() => markTags));
      if (ids.length > 1) toast.success(add.length ? `Đã gắn “${add.join(", ")}” cho ${ids.length} video.` : `Đã gỡ “${remove.join(", ")}” khỏi ${ids.length} video.`);
    } catch (e) {
      toast.error(errMessage(e));
    }
  }

  const pickedList = useMemo(() => videos.filter((v) => picked.has(v.id)), [videos, picked]);
  const pickedTodo = pickedList.filter((v) => downloadOf(v, state) === "");
  const pickedHere = pickedList.filter((v) => downloadOf(v, state) === "done" && v.media_id);
  // the picked videos already dubbed / subtitled here: "✏️ Chỉnh N video" opens them side by side in the editor
  // (the select "Video n/N"; edit one, "⇪ Áp cho cả loạt" gives every other one the same look)
  const pickedEditable = pickedList.map((v) => work[String(v.id)]?.dub)
    .filter((r): r is GrabToolRun => !!r && !!r.id && (r.state === "done" || r.state === "review"));
  function editPicked() {
    const ids = pickedEditable.map((r) => r.id);
    if (!ids.length) return;
    if (ids.length > MAX_EDIT_TOGETHER) toast.warning(`Mở ${MAX_EDIT_TOGETHER} video đầu — trình chỉnh sửa nhận tối đa ${MAX_EDIT_TOGETHER} video một lượt.`);
    navigate(editPath(ids), { state: { back: "/tools/grab" } });
  }
  function toggle(id: number) {
    setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }

  // ── channels ─────────────────────────────────────────────────────────────
  async function add() {
    const text = url.trim();
    if (!text || adding) return;
    setAdding(true);
    try {
      const ch = await addGrabChannel(text, limit);
      setUrl("");
      setChan(ch.id);
      setTag("");
      announceRunning();
      toast.success(`Đang đọc danh sách video của “${ch.name}”…`);
      await reload();
      setState((s) => ({ scans: { ...(s?.scans ?? {}), [String(ch.id)]: ch.scan ?? { status: "running", phase: "Bắt đầu", found: 0, added: 0, error: "", stopping: false } }, downloads: s?.downloads ?? {} }));
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setAdding(false);
    }
  }
  async function rescan(c: GrabChannel) {
    try {
      const ch = await scanGrabChannel(c.id, limit);
      announceRunning();
      setState((s) => ({ scans: { ...(s?.scans ?? {}), [String(c.id)]: ch.scan ?? { status: "running", phase: "Bắt đầu", found: 0, added: 0, error: "", stopping: false } }, downloads: s?.downloads ?? {} }));
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  async function rescanAll() {
    try {
      const r = await scanAllGrabChannels(limit);
      announceRunning();
      toast.info(`Đang quét lại ${r.channels} kênh — video mới sẽ có nhãn MỚI.`);
      setState(await getGrabState());
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  async function editTags(c: GrabChannel) {
    const text = await askText(`Nhãn của kênh “${c.name}” — cách nhau bằng dấu phẩy (VD: vũ trụ, đối thủ, hài)`, c.tags.join(", "), { ok: "Lưu nhãn", placeholder: "vũ trụ, khoa học" });
    if (text === null) return;
    try {
      await editGrabChannel(c.id, { tags: text.split(",").map((t) => t.trim()).filter(Boolean) });
      await reload();
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  async function remove(c: GrabChannel) {
    if (!(await askConfirm(`Bỏ kênh “${c.name}” khỏi danh sách?\n\nDanh sách ${c.videos} video của kênh sẽ mất. ${c.downloaded ? `${c.downloaded} video đã tải về vẫn còn trên máy — clip đã cắt / lồng tiếng từ chúng không ảnh hưởng. ` : ""}${c.marked ? `Nhãn bạn gắn cho ${c.marked} video vẫn được nhớ — thêm lại kênh là thấy lại.` : ""}`,
                           { ok: "Bỏ kênh", danger: true }))) return;
    try {
      await deleteGrabChannel(c.id);
      toast.success(`Đã bỏ kênh “${c.name}”.`);
      await reload();
    } catch (e) {
      toast.error(errMessage(e));
    }
  }

  // ── downloads and what comes after ───────────────────────────────────────
  async function download(ids: number[], quiet = false) {
    if (!ids.length) return;
    try {
      const r = await downloadGrabVideos(ids);
      announceRunning();
      setState(await getGrabState());
      if (!quiet) toast.info(r.queued ? `Đang tải ${r.queued} video về (hai video một lúc) — cứ làm việc khác, xong tool sẽ báo.` : "Các video này đã có trên máy rồi.");
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  /** "× Bỏ lỗi": the failures stop showing (the red strip, "⚠ Tải lỗi"); trying again later is still possible */
  async function dismiss(ids: number[]) {
    if (!ids.length) return;
    try {
      await dismissGrabErrors(ids);
      setVideos((list) => list.map((v) => (ids.includes(v.id) ? { ...v, download_error: "" } : v)));
      setWork(await getGrabWork());
      setState(await getGrabState());
      if (ids.length > 1) toast.success(`Đã bỏ lỗi của ${ids.length} video.`);
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  /** "🗑 Xoá file đã tải": "✓ Đã tải" goes; a video still used by a clip / a dub / a cut is kept and the toast says so */
  async function removeFiles(list: GrabVideo[]) {
    if (!list.length) return;
    if (!(await askConfirm(`Xoá file của ${list.length} video đã tải khỏi máy này (và bản trên cloud)?\n\n`
      + "Danh sách video, nhãn của bạn vẫn còn — cần dùng lại thì bấm tải lại. Video còn clip trong “Clip của tôi” "
      + "hoặc còn trong danh sách Lồng tiếng / Cắt video thì tool giữ lại (cần file để xuất lại).", { ok: "Xoá file", danger: true }))) return;
    try {
      const r = await deleteGrabFiles(list.map((v) => v.id));
      await reload();
      setState(await getGrabState());
      const kept = r.kept.length ? ` Giữ lại ${r.kept.length} video: ${Array.from(new Set(r.kept.map((k) => k.why))).join("; ")}.` : "";
      (r.deleted ? toast.success : toast.warning)(`${r.deleted ? `Đã xoá file của ${r.deleted} video.` : "Không xoá file nào."}${kept}`);
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  async function go(tool: "cut" | "dub", ids: number[]) {
    setAfter(null);
    try { await markGrabUsed(ids, tool); } catch { /* the mark is a nicety */ }
    navigate(`/tools/${tool}?grab=${ids.join(",")}`);
  }
  /** "🎙 Lồng tiếng ngay": the agent downloads what is missing and dubs — this page only watches. */
  function askDub(list: GrabVideo[]) {
    if (!list.length) return;
    if (list.length > MAX_DUB_NOW) {
      toast.warning(`Lồng tiếng tối đa ${MAX_DUB_NOW} video một lượt — bỏ chọn bớt ${list.length - MAX_DUB_NOW} video (gửi tiếp ở lượt sau).`);
      return;
    }
    setDubAsk(list);
  }
  async function startDub(list: GrabVideo[], o: DubNowOptions, quiet = false) {
    try {
      const r = await dubGrabNow(list.map((v) => v.id), o);
      setLot((l) => Array.from(new Set([...l.filter((id) => dubLive(work[String(id)]?.dub)), ...list.map((v) => v.id)])));
      setDubAsk(null);
      if (!quiet) setPicked(new Set());  // sent: the cards show the rest
      announceRunning();
      setWork(await getGrabWork());
      setState(await getGrabState());
      if (!quiet) {
        toast.success(r.queued ? `Đã gửi ${r.queued} video đi ${o.mode === "sub" ? "chèn phụ đề" : "lồng tiếng"} — theo dõi ngay trên từng thẻ.`
          : "Các video này đang được xử lý rồi.");
      }
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  const retryDub = (v: GrabVideo) => startDub([v], savedDubNow(dubVoice), true);

  async function send(tool: "cut" | "dub", list: GrabVideo[]) {
    if (!list.length) return;
    if (list.length > MAX_TO[tool]) {
      toast.warning(`${TOOL_NAME[tool]} nhận tối đa ${MAX_TO[tool]} video một lượt — bỏ chọn bớt ${list.length - MAX_TO[tool]} video (gửi tiếp ở lượt sau).`);
      return;
    }
    const ids = list.map((v) => v.id);
    const missing = list.filter((v) => downloadOf(v, state) !== "done");
    if (!missing.length) { await go(tool, ids); return; }
    await download(missing.filter((v) => downloadOf(v, state) === "").map((v) => v.id), true);
    setAfter({ tool, ids });
    toast.info(`Đang tải ${missing.length} video về trước — tải xong tool tự chuyển sang ${TOOL_NAME[tool]}.`);
  }
  // the downloads a tool is waiting for: all here → go on; one failed → stay and say so
  useEffect(() => {
    if (!after || !state) return;
    const list = after.ids.map((id) => videos.find((v) => v.id === id)).filter((v): v is GrabVideo => !!v);
    if (list.length !== after.ids.length) { setAfter(null); return; }
    if (list.some((v) => state.downloads[String(v.id)])) return;       // still on their way
    if (list.every((v) => v.media_id)) { void go(after.tool, after.ids); return; }
    const failed = list.filter((v) => !v.media_id);
    if (failed.some((v) => v.download_error)) {
      setAfter(null);
      toast.error(`${failed.length} video không tải được nên chưa chuyển sang ${TOOL_NAME[after.tool]} — bỏ chọn video lỗi rồi bấm lại.`);
      return;
    }
    // nothing on its way and not all here: the list may be a moment old (a download that ended between two polls) —
    // read it once more; still missing then = stopped, so the wait ends
    let alive = true;
    const t = window.setTimeout(() => {
      void listGrabVideos().then((fresh) => {
        if (!alive) return;
        setVideos(fresh);
        if (!after.ids.every((id) => fresh.find((v) => v.id === id)?.media_id)) {
          setAfter(null);
          toast.warning(`Chưa tải đủ video nên chưa chuyển sang ${TOOL_NAME[after.tool]}.`);
        }
      }).catch(() => undefined);
    }, 2500);
    return () => { alive = false; window.clearTimeout(t); };
  }, [after, videos, state]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── the AI's pick ────────────────────────────────────────────────────────
  async function aiPick() {
    const text = prompt.trim();
    if (!text) { toast.warning("Gõ yêu cầu cho AI trước, ví dụ: 10 video nhiều view nhất về vũ trụ."); return; }
    const pool = aiOnly ? scope : filtered;
    const max = status?.pick_max ?? 300;
    if (!pool.length) { toast.warning("Chưa có video nào trong danh sách để AI chọn."); return; }
    if (pool.length > max) { toast.warning(`AI xem tối đa ${max} video một lần — lọc bớt (lượt xem, ngày đăng, kênh…) rồi bấm lại. Đang có ${pool.length}.`); return; }
    setPicking(true);
    store("flowboard.grab.prompt", text);
    try {
      const r = await pickGrabVideos(pool.map((v) => v.id), text);
      if (r.prompts) setPrompts(r.prompts);
      setWhy(new Map(r.picks.map((p) => [p.id, p.why])));
      setAiNote(r.note);
      setPicked(new Set(r.picks.map((p) => p.id)));
      setAiOnly(r.picks.length > 0);
      if (r.picks.length) toast.success(`AI chọn ${r.picks.length} video — đã tick sẵn, xem lại rồi tải về.`);
      else toast.warning(r.note || "AI không thấy video nào hợp yêu cầu.");
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setPicking(false);
    }
  }
  function clearAi() { setWhy(new Map()); setAiNote(""); setAiOnly(false); }
  const promptSaved = prompts.some((p) => promptKey(p) === promptKey(prompt));
  async function keepPrompt() {
    const text = prompt.trim();
    if (!text) return;
    const full = !promptSaved && prompts.length >= MAX_PROMPTS;
    try {
      setPrompts(await saveGrabPrompt(text));
      toast.success(full ? `Đã lưu yêu cầu — đã bỏ yêu cầu cũ nhất (giữ tối đa ${MAX_PROMPTS}).` : "Đã lưu yêu cầu.");
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  async function dropPrompt(text: string) {
    try { setPrompts(await deleteGrabPrompt(text)); } catch (e) { toast.error(errMessage(e)); }
  }

  if (channels === null) return <><header className="qt-header"><span className="qt-header__crumb">📡 Cào video kênh</span></header><PageLoading /></>;

  const open = chan !== null ? byId.get(chan) ?? null : null;
  const downloading = state ? Object.keys(state.downloads).length : 0;
  const scanning = state ? Object.keys(state.scans).length : 0;
  const view = filtered.slice(0, shown);

  return (
    <>
      <header className="qt-header"><span className="qt-header__crumb">📡 Cào video kênh</span></header>
      <div className="qt-home gb">
        <section className="qt-card gb__add">
          <div className="gb__addrow">
            <input ref={urlInput} className="gb__input" value={url} placeholder="Dán link kênh YouTube, TikTok, Douyin hoặc Bilibili — vd. https://www.youtube.com/@tenkenh"
                   aria-label="Link kênh" onChange={(e) => setUrl(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void add(); } }} />
            <LimitPicker limit={limit} presets={status?.limits ?? PRESET_LIMITS} max={status?.max_limit ?? MAX_LIMIT}
                         onChange={(n) => { setLimit(n); store("flowboard.grab.limit", n); }} />
            <button type="button" className="qt-btn qt-btn--accent" disabled={!url.trim() || adding} onClick={() => void add()}>
              {adding ? "Đang thêm…" : "＋ Thêm kênh & quét"}
            </button>
          </div>
          <p className="qt-card__hint">
            Tool đọc danh sách video của kênh (lượt xem, tim, độ dài, ngày đăng) — <strong>chưa tải gì về</strong>. Lọc hoặc nhờ AI chọn rồi mới tải video muốn làm.
          </p>
          <details className="gb__help">
            <summary>Đọc được kênh nào? Douyin, Bilibili cần gì?</summary>
            <p className="qt-card__hint">
              Đọc được: <PlatformChip platform="youtube" label="YouTube (kênh, Shorts, playlist)" /> <PlatformChip platform="tiktok" label="TikTok" />
              {" "}<PlatformChip platform="douyin" label="Douyin" /> <PlatformChip platform="bilibili" label="Bilibili (bilibili.com)" beta />
              {" "}· Facebook, Instagram không cho đọc danh sách kênh — dán từng link video vào “Xử lý video”.
            </p>
            <p className="qt-card__hint">
              <strong>Douyin và Bilibili</strong> được đọc qua Chrome của bạn: lúc quét, extension DFlow mở trang kênh trong một cửa sổ Chrome, cuộn lấy
              danh sách rồi tự đóng (đừng đóng tay). Douyin cần bạn <strong>đã đăng nhập douyin.com</strong> trong Chrome đó; trang hỏi mã xác minh thì làm
              ngay trong cửa sổ ấy. Douyin không công bố lượt xem — tool hiện lượt tim.
            </p>
            <p className="gb__bili">
              <b className="gb-beta">BETA</b> <strong>Bilibili:</strong> chỉ đọc được <strong>bilibili.com</strong> — bản Trung Quốc, link kênh dạng
              <code>space.bilibili.com/123456</code> (cả dạng có <code>/en/</code> khi vào từ Việt Nam). <strong>Chưa</strong> đọc được <strong>bilibili.tv</strong> (bản quốc
              tế, link <code>bilibili.tv/vi/space/…</code>). Chưa đăng nhập thì chỉ đọc được vài chục video mới nhất và hay bị Bilibili chặn tạm khi quét
              nhiều kênh liền nhau.
            </p>
          </details>
          {limit > 200 && (
            <p className="gb__note">
              Lấy {limit === (status?.max_limit ?? MAX_LIMIT) ? "tất cả" : limit} video thì quét lâu hơn: YouTube / TikTok khoảng 1 phút mỗi 1000 video; Douyin / Bilibili cửa sổ Chrome
              cuộn khoảng 1 phút mỗi 300 video (giữ cửa sổ đó mở). AI chọn tối đa {status?.pick_max ?? 300} video một lần — lọc bớt trước khi nhờ AI.
            </p>
          )}
          {status && !status.ytdlp && <p className="gb__warn">Máy này chưa có công cụ đọc kênh (yt-dlp) — tool sẽ tự tải ở lần quét đầu, cần có mạng.</p>}
        </section>

        {channels.length === 0 ? (
          <PageEmpty icon="📡" title="Chưa có kênh nào"
                     actions={<button type="button" className="qt-btn qt-btn--accent" onClick={() => urlInput.current?.focus()}>Dán link kênh đầu tiên</button>}>
            Dán link một kênh bạn hay lấy video (kênh nước ngoài cùng ngành, kênh đối thủ…). Tool liệt kê video kèm lượt xem và ngày đăng để bạn chọn
            video đáng làm lại, tải về rồi đem cắt / lồng tiếng — khỏi mở từng video để dò.
          </PageEmpty>
        ) : (
          <div className="gb__grid">
            <aside className="gb__side">
              <div className="gb__sidehead">
                <strong>Kênh nguồn <small>{channels.length}</small></strong>
                <button type="button" className="qt-btn qt-btn--small" disabled={scanning > 0} onClick={() => void rescanAll()}
                        title="Đọc lại video mới của mọi kênh — video chưa thấy lần trước được gắn nhãn MỚI">⟳ Quét tất cả</button>
              </div>
              {allTags.length > 0 && (
                <div className="gb__tags" role="group" aria-label="Lọc kênh theo nhãn">
                  <button type="button" className={`qt-chip qt-chip--sm${tag === "" ? " qt-chip--on" : ""}`} onClick={() => setTag("")}>Tất cả</button>
                  {allTags.map((t) => (
                    <button key={t} type="button" className={`qt-chip qt-chip--sm${tag === t ? " qt-chip--on" : ""}`} onClick={() => { setTag(t); setChan(null); }}>#{t}</button>
                  ))}
                </div>
              )}
              <button type="button" className={`gb-ch gb-ch--all${chan === null ? " is-on" : ""}`} onClick={() => setChan(null)}>
                <span className="gb-avatar gb-avatar--all" style={{ width: 40, height: 40, fontSize: 18 }} aria-hidden="true">▦</span>
                <span className="gb-ch__body">
                  <strong>{tag ? `Mọi kênh #${tag}` : "Tất cả kênh"}</strong>
                  <small>{listed.reduce((n, c) => n + c.videos, 0)} video · {listed.length} kênh</small>
                </span>
              </button>
              {listed.map((c) => {
                const scan = state?.scans[String(c.id)];
                return (
                  <div key={c.id} className={`gb-ch${chan === c.id ? " is-on" : ""}`}>
                    <button type="button" className="gb-ch__main" onClick={() => setChan(c.id)} title={c.description || c.url}>
                      <Avatar channel={c} />
                      <span className="gb-ch__body">
                        <strong>{c.name}</strong>
                        <small>
                          <PlatformChip platform={c.platform} label={c.platform_label} beta={c.platform === "bilibili"} />
                          {c.followers !== null && <span>{shortCount(c.followers)} theo dõi</span>}
                        </small>
                        <small>
                          {c.videos} video{c.fresh > 0 && <b className="gb-new"> · {c.fresh} mới</b>}{c.downloaded > 0 && <span> · {c.downloaded} đã tải</span>}
                          {c.marked > 0 && <span title="Video bạn đã gắn nhãn (Đã xử lý, Đã đăng…)"> · 🏷 {c.marked}</span>}
                          {c.scanned_at && <span title={`Quét lần cuối ${new Date(c.scanned_at).toLocaleString("vi-VN")}`}> · quét {agoOf(c.scanned_at)}</span>}
                        </small>
                        {c.tags.length > 0 && <span className="gb-ch__tags">{c.tags.map((t) => <i key={t}>#{t}</i>)}</span>}
                      </span>
                    </button>
                    {scan ? (
                      <div className="gb-ch__scan" role="status">
                        <span className="gb-spin" aria-hidden="true" /> <span>{scan.phase}{scan.found ? ` · ${scan.found} video` : ""}</span>
                        <StopButton stopping={scan.stopping} onStop={() => stopGrabScan(c.id)} />
                      </div>
                    ) : (
                      <div className="gb-ch__acts">
                        {c.scan_error && <span className="gb-ch__err" title={c.scan_error}>⚠ Lần quét cuối lỗi</span>}
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void rescan(c)} title={`Đọc lại ${limit} video mới nhất của kênh`}>⟳ Quét lại</button>
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void editTags(c)} title="Gắn nhãn để gom kênh theo chủ đề">🏷 Nhãn</button>
                        <a className="qt-btn qt-btn--small qt-btn--ghost" href={c.url} target="_blank" rel="noreferrer" title="Mở kênh">↗</a>
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void remove(c)} title="Bỏ kênh khỏi danh sách">🗑</button>
                      </div>
                    )}
                  </div>
                );
              })}
            </aside>

            <div className="gb__main">
              <section className="qt-card gb__tools">
                <div className="gb__title">
                  <h3>{open ? open.name : tag ? `Mọi kênh #${tag}` : "Tất cả kênh"}</h3>
                  <small>{filtered.length === scope.length ? `${scope.length} video` : `${filtered.length} / ${scope.length} video`}</small>
                  {filtersOn && <button type="button" className="qt-link" onClick={clearFilters}>Bỏ lọc</button>}
                </div>
                {open?.scan_error && !state?.scans[String(open.id)] && <p className="gb__warn">⚠ Lần quét cuối lỗi: {open.scan_error}</p>}
                <div className="gb__filters">
                  <label className="qt-field gb__search"><span>Tìm theo tiêu đề</span>
                    <input value={q} placeholder="gõ vài chữ…" onChange={(e) => setQ(e.target.value)} />
                  </label>
                  <label className="qt-field"><span>Sắp xếp</span>
                    <select value={sort} onChange={(e) => { const s = e.target.value as Sort; setSort(s); store("flowboard.grab.sort", s); }}>
                      {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                    </select>
                  </label>
                  <button type="button" className={`qt-btn qt-btn--small gb__more${moreOpen ? " qt-btn--on" : ""}`} aria-expanded={moreOpen}
                          onClick={() => setMoreOpen((o) => !o)}>
                    {moreOpen ? "▴ Thu gọn bộ lọc" : `▾ Lọc thêm${extraOn ? ` (${extraOn} đang bật)` : ""}`}
                  </button>
                </div>
                {moreOpen && (<>
                <div className="gb__filters gb__filters--more">
                  <label className="qt-field"><span>Lượt xem</span>
                    <select value={minViews} onChange={(e) => setMinViews(Number(e.target.value))}>
                      {VIEW_STEPS.map((n) => <option key={n} value={n}>{n ? `Từ ${shortCount(n)} trở lên` : "Tất cả"}</option>)}
                    </select>
                  </label>
                  <label className="qt-field"><span>Ngày đăng</span>
                    <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                      {DAY_STEPS.map((d) => <option key={d.days} value={d.days}>{d.label}</option>)}
                    </select>
                  </label>
                  <label className="qt-field"><span>Độ dài</span>
                    <select value={len} onChange={(e) => setLen(e.target.value as Len)}>
                      {LENS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
                    </select>
                  </label>
                  <label className="qt-field"><span>Loại</span>
                    <select value={kind} onChange={(e) => setKind(e.target.value as "" | "video" | "short")}>
                      <option value="">Video & Shorts</option><option value="video">Chỉ video</option><option value="short">Chỉ YouTube Shorts</option>
                    </select>
                  </label>
                  <label className="qt-field"><span>Trạng thái</span>
                    <select value={have} onChange={(e) => setHave(e.target.value as Have)}>
                      {HAVES.map((h) => <option key={h.key} value={h.key}>{h.label}{h.key === "failed" && failedCount ? ` (${failedCount})` : ""}</option>)}
                    </select>
                  </label>
                </div>
                <div className="gb__marks" role="group" aria-label="Lọc theo nhãn video">
                  <span className="gb__markslabel">🏷 Nhãn video:</span>
                  <button type="button" className={`qt-chip qt-chip--sm${markF === "" ? " qt-chip--on" : ""}`} onClick={() => pickMarkFilter("")}>Tất cả</button>
                  <button type="button" className={`qt-chip qt-chip--sm${markF === "__none" ? " qt-chip--on" : ""}`} onClick={() => pickMarkFilter("__none")}
                          title="Video chưa gắn nhãn nào — ẩn video đã xử lý / đã đăng để khỏi làm lại">Chưa gắn nhãn <small>{markCounts.none}</small></button>
                  <button type="button" className={`qt-chip qt-chip--sm${markF === "__any" ? " qt-chip--on" : ""}`} onClick={() => pickMarkFilter("__any")}>Đã gắn nhãn <small>{markCounts.any}</small></button>
                  {knownMarks.map((t) => {
                    const count = markCounts.per.get(t) ?? 0;
                    if (!count && !presets.includes(t) && markF !== t) return null;
                    return (
                      <button key={t} type="button" className={`qt-chip qt-chip--sm gb__markchip${markF === t ? " qt-chip--on" : ""}`} onClick={() => pickMarkFilter(markF === t ? "" : t)}>
                        <span className={markClass(t, presets)}>{t}</span> <small>{count}</small>
                      </button>
                    );
                  })}
                </div>
                </>)}
                {days > 0 && undated > 0 && (
                  <p className="gb__note">{undated} video không rõ ngày đăng (YouTube không ghi ngày cho Shorts trong danh sách) nên đang ẩn — chọn “Mọi lúc” để thấy.</p>
                )}

                <details className="gb__ai" open={why.size > 0 || undefined}>
                  <summary>✨ Nhờ AI chọn theo yêu cầu <small>AI đọc tiêu đề + lượt xem + ngày đăng của {aiOnly ? scope.length : filtered.length} video đang hiện</small></summary>
                  <textarea className="qt-textarea" value={prompt} rows={2} maxLength={1500} disabled={picking}
                            placeholder="VD: 10 video nhiều lượt xem nhất về vũ trụ, dưới 3 phút, đăng trong 3 tháng gần đây"
                            onChange={(e) => setPrompt(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void aiPick(); } }} />
                  <div className="gb__airow">
                    <button type="button" className="qt-btn qt-btn--accent qt-btn--small" disabled={picking || !prompt.trim()} onClick={() => void aiPick()}>
                      {picking ? "AI đang chọn…" : "✨ AI chọn video"}
                    </button>
                    <button type="button" className="qt-btn qt-btn--small" disabled={picking || !prompt.trim() || promptSaved} onClick={() => void keepPrompt()}
                            title={`Lưu yêu cầu này để lần sau bấm là dùng lại (giữ ${MAX_PROMPTS} yêu cầu mới nhất)`}>
                      {promptSaved && prompt.trim() ? "✓ Đã lưu" : "💾 Lưu yêu cầu"}
                    </button>
                    {why.size > 0 && (
                      <>
                        <label className="qt-check"><input type="checkbox" checked={aiOnly} onChange={(e) => setAiOnly(e.target.checked)} /> Chỉ hiện {why.size} video AI chọn</label>
                        <button type="button" className="qt-link" onClick={clearAi}>Bỏ kết quả AI</button>
                      </>
                    )}
                  </div>
                  {aiNote && <p className="gb__note">✨ {aiNote}</p>}
                  <div className="gb__saved">
                    <span className="gb__savedhead">
                      📌 Yêu cầu đã lưu <small>{prompts.length}/{MAX_PROMPTS} · bấm “AI chọn video” là tự lưu · quá {MAX_PROMPTS} thì bỏ cái cũ nhất</small>
                    </span>
                    {prompts.length === 0 ? (
                      <span className="gb__savedempty">Chưa có — gõ yêu cầu rồi bấm “✨ AI chọn video” hoặc “💾 Lưu yêu cầu”.</span>
                    ) : (
                      <ul className="gb__savedlist">
                        {prompts.map((p) => (
                          <li key={p} className={promptKey(p) === promptKey(prompt) ? "is-on" : ""}>
                            <button type="button" className="gb__savedtext" disabled={picking} onClick={() => setPrompt(p)} title={`${p}\n\nBấm để dùng lại yêu cầu này`}>{p}</button>
                            <button type="button" className="gb__savedx" disabled={picking} onClick={() => void dropPrompt(p)} title="Xoá yêu cầu này" aria-label="Xoá yêu cầu này">×</button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <p className="gb__note">AI chỉ biết tiêu đề và con số — không xem nội dung video. Xem lại các video được tick trước khi tải.</p>
                </details>
              </section>

              <div className={`gb__bar${picked.size ? " is-on" : ""}`} role="region" aria-label="Video đã chọn">
                <span className="gb__barcount">{picked.size ? <>Đã chọn <strong>{picked.size}</strong> video</> : "Tick vào ảnh video để chọn"}</span>
                <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!filtered.length} onClick={() => setPicked(new Set(filtered.map((v) => v.id)))}
                        title="Chọn mọi video đang hiện theo bộ lọc (cả những video ở dưới nút Xem thêm)">
                  Chọn cả {filtered.length}
                </button>
                {picked.size > 0 && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setPicked(new Set())}>Bỏ chọn</button>}
                <span className="gb__barspace" />
                <button type="button" className="qt-btn qt-btn--small" disabled={!picked.size} onClick={(e) => openMarks(pickedList.map((v) => v.id), e.currentTarget)}
                        title="Gắn / gỡ nhãn (Đã xử lý, Đã đăng…) cho các video đã chọn">🏷 Nhãn {picked.size || ""}</button>
                <button type="button" className="qt-btn qt-btn--small" disabled={!pickedTodo.length} onClick={() => void download(pickedTodo.map((v) => v.id))}
                        title="Tải các video đã chọn về máy (video đã có thì bỏ qua)">⬇ Tải {pickedTodo.length || ""} video về</button>
                {pickedHere.length > 0 && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => void removeFiles(pickedHere)}
                          title="Xoá file video đã tải khỏi máy (nhãn “✓ Đã tải” mất; video còn dùng cho clip / lồng tiếng / cắt thì giữ lại)">
                    🗑 Xoá {pickedHere.length} file đã tải
                  </button>
                )}
                {canCut && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!picked.size || !!after} onClick={() => void send("cut", pickedList)}
                          title={`Đem video đã chọn đi cắt thành nhiều video ngắn (tối đa ${MAX_TO.cut} video một lượt; video chưa tải thì tool tải trước)`}>✂️ Cắt {picked.size || ""} video</button>
                )}
                {canDub && pickedEditable.length > 0 && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={editPicked}
                          title="Mở trình chỉnh sửa với các video đã lồng tiếng / chèn phụ đề trong số đã chọn: chỉnh một video rồi bấm “⇪ Áp cho cả loạt” để mọi video cùng kiểu (khung, nền, phụ đề, chữ, nhân vật)">
                    ✏️ Chỉnh {pickedEditable.length} video đã lồng
                  </button>
                )}
                {canDub && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!picked.size} onClick={() => askDub(pickedList)}
                          title={`Lồng tiếng / chèn phụ đề các video đã chọn ngay tại đây (tối đa ${MAX_DUB_NOW} video một lượt; video chưa tải thì tool tự tải)`}>🎙 Lồng tiếng {picked.size || ""} video</button>
                )}
              </div>

              {downloading > 0 && (
                <div className="gb__strip" role="status">
                  <span className="gb-spin" aria-hidden="true" />
                  <span>Đang tải {downloading} video về máy (hai video một lúc){after ? ` — xong sẽ chuyển sang ${TOOL_NAME[after.tool]}` : ""}</span>
                  {after && <button type="button" className="qt-link" onClick={() => setAfter(null)}>Không chuyển nữa</button>}
                  <StopButton label="Dừng tải" onStop={async () => { setAfter(null); await stopGrabDownloads(); }} />
                </div>
              )}

              {liveDub.length > 0 && (
                <div className="gb__dubbar" role="status">
                  <span className="gb-spin" aria-hidden="true" />
                  <span>
                    🎙 Đang lồng tiếng{lotTotal > 0 ? <> <strong>{lotDone}/{lotTotal}</strong> video xong</> : <> <strong>{liveDub.length}</strong> video</>}
                    {" · "}còn khoảng <strong>{etaText}</strong>
                  </span>
                  <span className="gb__dubbartrack"><span style={{ width: `${lotTotal ? Math.round((lotDone / lotTotal) * 100) : 0}%` }} /></span>
                  <StopButton label="Dừng tất cả" onStop={async () => { await stopGrabDub(); setWork(await getGrabWork()); }} />
                </div>
              )}

              {failedCount > 0 && have !== "failed" && (
                <div className="gb__failbar" role="status">
                  <span>⚠ <strong>{failedCount}</strong> video tải / cắt / lồng tiếng bị lỗi — thẻ của chúng có dải đỏ, bấm vào để xem lỗi.</span>
                  <button type="button" className="qt-btn qt-btn--small" onClick={() => setHave("failed")}>Chỉ xem video bị lỗi</button>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void dismiss(failedList.map((v) => v.id))}
                          title="Thôi hiện các lỗi này (video vẫn còn trong danh sách, thử lại được bất cứ lúc nào)">× Bỏ hết lỗi</button>
                </div>
              )}
              {filtered.length === 0 ? (
                <PageEmpty compact icon="🔎" title={scope.length ? "Không video nào khớp bộ lọc" : scanning ? "Đang đọc danh sách video…" : "Kênh này chưa có video nào trong danh sách"}
                           actions={scope.length ? <button type="button" className="qt-btn" onClick={clearFilters}>Bỏ lọc</button>
                             : open && !scanning ? <button type="button" className="qt-btn" onClick={() => void rescan(open)}>⟳ Quét lại</button> : undefined}>
                  {scope.length ? "Nới bộ lọc lượt xem / ngày đăng / độ dài, hoặc bỏ lọc." : scanning ? "Thường mất vài giây mỗi kênh." : "Bấm Quét lại để đọc video của kênh."}
                </PageEmpty>
              ) : (
                <>
                  <div className="gb__vids">
                    {view.map((v) => {
                      const dl = downloadOf(v, state);
                      const ch = byId.get(v.channel_id);
                      const on = picked.has(v.id);
                      const tall = v.kind === "short" || ch?.platform === "tiktok" || ch?.platform === "douyin";
                      const reason = why.get(v.id);
                      const tone = markTone(v.marks, presets);
                      const runs = work[String(v.id)];
                      const fails = failedTools(runs);
                      const dubRun = runs?.dub;
                      return (
                        <article key={v.id} className={`gb-v${on ? " is-on" : ""}${tone ? ` gb-v--marked gb-v--${tone}` : ""}${fails.length ? " gb-v--failed" : ""}`}>
                          <label className="gb-v__thumb" title={on ? "Bỏ chọn" : "Chọn video này"}>
                            <input type="checkbox" checked={on} onChange={() => toggle(v.id)} aria-label={`Chọn “${v.title || "video"}”`} />
                            <img className={tall ? "is-tall" : ""} src={grabThumbUrl(v.id)} alt="" loading="lazy"
                                 onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }} />
                            <span className="gb-v__tick" aria-hidden="true">{on ? "✓" : ""}</span>
                            {v.fresh && <span className="gb-v__new">MỚI</span>}
                            <span className="gb-v__dur">{clockOf(v.duration_s) || (v.kind === "short" ? "Short" : "")}</span>
                            {tone && (
                              <span className={`gb-v__ribbon gb-v__ribbon--${tone}`} title={v.marks.join(" · ")}>
                                {markIcon(mainMark(v.marks, presets), presets)} {mainMark(v.marks, presets)}{v.marks.length > 1 && <b> +{v.marks.length - 1}</b>}
                              </span>
                            )}
                          </label>
                          <div className="gb-v__body">
                            <a className="gb-v__title" href={v.url} target="_blank" rel="noreferrer" title={`${v.title}\n\nBấm để mở video gốc`}>{v.title || "(không có tiêu đề)"}</a>
                            <div className="gb-v__meta">
                              {(v.views !== null || v.likes === null) && <span title="Lượt xem">👁 {shortCount(v.views)}</span>}
                              {v.likes !== null && <span title="Lượt tim">❤ {shortCount(v.likes)}</span>}
                              {v.comments !== null && <span title="Bình luận">💬 {shortCount(v.comments)}</span>}
                              {v.published_at && <span title={`Đăng khoảng ${dateOf(v.published_at)}`}>{agoOf(v.published_at)}</span>}
                            </div>
                            {fails.map((k) => {
                              const run = runs![k]!;
                              return (
                                <div key={k} className="gb-v__failwrap">
                                  <a className="gb-v__fail" href={run.link || "#"} title={run.link ? `${run.error}\n\nBấm để mở và xem` : run.error}
                                     onClick={(e) => { e.preventDefault(); if (run.link) navigate(run.link); }}>
                                    <strong>⚠ {RUN_TEXT[k].icon} {k === "dub" ? "Lồng tiếng" : "Cắt video"} bị lỗi</strong> {run.link && <span>Xem ›</span>}
                                    {run.error && <small>{run.error}</small>}
                                  </a>
                                  <span className="gb-v__failacts">
                                    {k === "dub" && canDub && (
                                      <button type="button" className="qt-btn qt-btn--small" onClick={() => void retryDub(v)}
                                              title="Lồng tiếng lại video này với lựa chọn lần trước">↻ Thử lại</button>
                                    )}
                                    <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void dismiss([v.id])}
                                            title="Thôi hiện lỗi này trên thẻ (thử lại vẫn được)">× Bỏ lỗi</button>
                                  </span>
                                </div>
                              );
                            })}
                            {chan === null && ch && <div className="gb-v__chan"><PlatformChip platform={ch.platform} label={ch.name} /></div>}
                            {reason !== undefined && <div className="gb-v__why">✨ {reason || "AI chọn"}</div>}
                            {v.marks.length > 0 && (
                              <div className="gb-v__marks">
                                {v.marks.map((m) => <span key={m} className={markClass(m, presets)}>{markIcon(m, presets)} {m}</span>)}
                              </div>
                            )}
                            {dubRun && dubLive(dubRun) && <DubProgress run={dubRun} />}
                            {dubRun?.state === "nospeech" && (
                              <div className="gb-v__quiet" title="Tool không nghe thấy lời nói nào trong video (chỉ có nhạc / tiếng động) nên không có gì để dịch">
                                🔇 Không có lời để lồng tiếng <small>video chỉ có nhạc — dùng nguyên video</small>
                              </div>
                            )}
                            {dubRun?.state === "done" && dubRun.link && (
                              <div className="gb-v__ready">
                                <span title={dubRun.name || ""}>✓ {dubRun.mode === "sub" ? "Đã chèn phụ đề" : "Đã lồng tiếng"}{dubRun.name ? ` · ${dubRun.name}` : ""}</span>
                                <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => navigate(editPath([dubRun.id]), { state: { back: "/tools/grab" } })}>✏️ Mở chỉnh</button>
                                {dubRun.media_id && <a className="qt-btn qt-btn--small" href={`/media/${dubRun.media_id}`} target="_blank" rel="noreferrer" title="Xem video đã lồng tiếng">▶ Xem</a>}
                              </div>
                            )}
                            <div className="gb-v__foot">
                              {dl === "done" && <span className="gb-st gb-st--ok">✓ Đã tải</span>}
                              {dl === "running" && <span className="gb-st gb-st--run"><span className="gb-spin" aria-hidden="true" /> Đang tải…</span>}
                              {dl === "queued" && <span className="gb-st">Chờ tải</span>}
                              {dl === "" && v.download_error && <span className="gb-st gb-st--err" title={v.download_error}>⚠ Tải lỗi</span>}
                              {dl === "" && !v.download_error && v.elsewhere && <span className="gb-st" title="Video này đã tải ở máy khác — tải lại để dùng trên máy này">Tải ở máy khác</span>}
                              {TOOLS.map((k) => {
                                const run = runs?.[k];
                                const sent = v.used[k];
                                // the dub's progress / result has its own block above
                                if (k === "dub" && run && (dubLive(run) || run.state === "nospeech" || (run.state === "done" && run.link))) return null;
                                if (run && run.state !== "error") return <RunChip key={k} tool={k} run={run} onOpen={() => navigate(run.link)} />;
                                if (!run && sent) {
                                  return <span key={k} className="gb-st" title={`Có clip ${k === "dub" ? "lồng tiếng" : "cắt"} từ video này trong “Clip của tôi” (${dateOf(sent)}) — xoá clip đó thì nhãn này mất`}>
                                    {RUN_TEXT[k].icon} đã {k === "dub" ? "lồng" : "cắt"}</span>;
                                }
                                return null;
                              })}
                              <span className="gb-v__acts">
                                {on && picked.size > 1 ? (
                                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={(e) => openMarks(pickedList.map((x) => x.id), e.currentTarget)}
                                          title={`Gắn / gỡ nhãn cho cả ${picked.size} video đang chọn (nhớ theo video, quét lại vẫn còn)`}>🏷 {picked.size}</button>
                                ) : (
                                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={(e) => openMarks([v.id], e.currentTarget)}
                                          title="Gắn nhãn: Đã xử lý, Đã đăng… (nhớ theo video, quét lại vẫn còn)">🏷</button>
                                )}
                                {dl === "" && <button type="button" className="qt-btn qt-btn--small" onClick={() => void download([v.id])} title="Tải video này về máy">⬇</button>}
                                {(dl === "running" || dl === "queued") && <StopButton label="×" busyLabel="…" title="Dừng tải video này" onStop={() => stopGrabDownloads([v.id])} />}
                                {dl === "done" && v.media_id && (
                                  <>
                                    <a className="qt-btn qt-btn--small" href={`/media/${v.media_id}`} target="_blank" rel="noreferrer" title="Xem video đã tải">▶</a>
                                    {canCut && <button type="button" className="qt-btn qt-btn--small" onClick={() => void send("cut", [v])} title="Đem video này đi cắt">✂️</button>}
                                  </>
                                )}
                                {canDub && !dubLive(dubRun) && (
                                  <button type="button" className="qt-btn qt-btn--small" onClick={() => askDub([v])}
                                          title="Lồng tiếng / chèn phụ đề video này ngay (chưa tải thì tool tự tải)">🎙</button>
                                )}
                              </span>
                            </div>
                            {dl === "" && v.download_error && (
                              <p className="gb-v__err">
                                <span>{v.download_error}</span>
                                <button type="button" className="qt-link" onClick={() => void dismiss([v.id])} title="Thôi hiện lỗi tải này (bấm ⬇ để tải lại)">× Bỏ lỗi</button>
                              </p>
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                  {filtered.length > shown && (
                    <button type="button" className="qt-btn gb__more" onClick={() => setShown((n) => n + PAGE)}>
                      Xem thêm {Math.min(PAGE, filtered.length - shown)} video (còn {filtered.length - shown})
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
      {markMenu && (
        <MarkMenu anchor={markMenu.anchor} known={knownMarks} presets={presets}
                  marks={markMenu.ids.map((id) => videos.find((v) => v.id === id)?.marks ?? [])}
                  onApply={(add, remove) => applyMarks(markMenu.ids, add, remove)} onClose={() => setMarkMenu(null)} />
      )}
      {dubAsk && (
        <DubNowDialog count={dubAsk.length} missing={dubAsk.filter((v) => downloadOf(v, state) !== "done").length}
                      onStart={(o) => startDub(dubAsk, o)} onClose={() => setDubAsk(null)}
                      onOpenPage={dubAsk.length <= MAX_TO.dub ? () => { const l = dubAsk; setDubAsk(null); void send("dub", l); } : undefined} />
      )}
    </>
  );
}
