import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import {
  getDefaultLook, listLookPresets, type DecorPreset,
  deleteDubJobs, getDubJob, getDubStatus, identifyVideo, isTextFile, linksIn, listDubBatch, listDubJobsBrief, listDubLinks, startDub, stopDub,
  uploadDubVideo, type DubJob, type DubStatus, type IdentifyResult,
} from "../../api/dub";
import { editPath } from "../../api/edit";
import { DubJobsDialog, jobTitle } from "../dub/DubJobsDialog";
import { DubLinksDialog } from "../dub/DubLinksDialog";
import { ClipPickDialog, type PickedClip } from "../dub/ClipPickDialog";
import { clipVideos } from "../../api/cut";
import { grabMedia } from "../../api/grab";
import { VOICES } from "../../api/client";
import { SUB_LANGS, subLangName, type DubEngine, type DubMode, type DubTranslator, type SubLang } from "../../api/dub";
import { toast } from "../../store/toast";
import { useSettingsStore } from "../../store/settings";
import { ChannelPicker } from "../channels/ChannelPicker";
import { PageEmpty, PageLoading } from "../PageState";
import { VoiceField } from "../VoiceField";
import "../dub.css";
import { ProgressRing } from "../dub/ProgressRing";
import { StopButton } from "../../components/StopButton";
import { DubAddonCard } from "../dub/DubAddonCard";
import { RemotionAddonCard } from "../dub/RemotionAddonCard";
import { ModePicker } from "../dub/ModePicker";
import { takeHandoff } from "../sources/handoff";
import { VideoToolsTabs } from "../VideoToolsTabs";

const POLL_MS = 2000;
const DEFAULT_VOICE = "vi-VN-HoaiMyNeural";
const MAX_LINKS = 5;
/** videos already on this machine (from "📡 Cào video kênh" or "Clip của tôi") — no download, so more at once */
const MAX_PICKED = 10;
const RECENT_SHOWN = 5;
const WORKING = ["queued", "running", "rendering"];
const isWorking = (j: DubJob) => WORKING.includes(j.status);
/** a job the editor can open: it has lines, and is not mid-transcription */
const canEdit = (j: DubJob) => (j.segments.length > 0 || (j.kind === "cut" && !!j.media_id)) && (["review", "done", "error"].includes(j.status) || !!j.media_id);

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * "Lồng tiếng video" — the VieDub flow in one screen: paste a link (or a
 * file), pick a voice, get the video back with the original speech
 * replaced by Vietnamese voice-over and yellow-box subtitles. The result is
 * a clip, so it can belong to a channel and get a Facebook post.
 */
export function DubPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState<DubStatus | null>(null);
  // One input per link (paste several at once → one row each); every link becomes one job of the same batch.
  const [links, setLinks] = useState<string[]>([""]);
  const linkInputs = useRef<(HTMLInputElement | null)[]>([]);
  const [file, setFile] = useState<File | null>(null);
  // "🎬 Chọn từ Clip của tôi": finished clips to dub (the videos cut on "✂️ Cắt video"); /tools/dub?clips=<ids> picks them
  const [clips, setClips] = useState<PickedClip[]>([]);
  const [pickOpen, setPickOpen] = useState(false);
  const [name, setName] = useState("");
  // the voice picked last is the default next time (account pref — both machines; also set from the link library)
  const voice = useSettingsStore((s) => s.dubVoice) || DEFAULT_VOICE;
  const setVoice = useSettingsStore((s) => s.setDubVoice);
  const [style, setStyle] = useState("box_yellow");
  const [engine, setEngine] = useState<DubEngine>("ass");
  // "★ Template": a saved look for the new video (the default one is pre-picked); its style / engine win
  const [looks, setLooks] = useState<DecorPreset[]>([]);
  const [lookId, setLookId] = useState<number | null>(null);
  useEffect(() => {
    void listLookPresets().then(setLooks).catch(() => setLooks([]));
    void getDefaultLook().then((d) => setLookId(d.id)).catch(() => undefined);
  }, []);
  const [keepBgm, setKeepBgm] = useState(true);
  const [review, setReview] = useState(false);
  // "dub" = Vietnamese voice-over; "sub" = only subtitles, the video keeps its sound (no voice read — much faster).
  // Always opens on the voice-over (the person's ask, 1/11) — subtitles only is picked per video, not remembered.
  const [mode, setMode] = useState<DubMode>("dub");
  const subOnly = mode === "sub";
  // subtitles only: their language — Vietnamese, the video's own words, or another (remembered per browser)
  const [subLang, setSubLangState] = useState<SubLang>(() => {
    try {
      const v = localStorage.getItem("flowboard.dub.subLang");
      return SUB_LANGS.some((l) => l.key === v) ? (v as SubLang) : "vi";
    } catch { return "vi"; }
  });
  const setSubLang = (l: SubLang) => {
    setSubLangState(l);
    try { localStorage.setItem("flowboard.dub.subLang", l); } catch { /* private window */ }
  };
  const lang: SubLang = subOnly ? subLang : "vi";
  // who translates — free Google like VieDub (default) or the AI of Settings (spends its quota); remembered per browser
  const [translator, setTranslatorState] = useState<DubTranslator>(() => {
    try { return localStorage.getItem("flowboard.dub.translator") === "ai" ? "ai" : "google"; } catch { return "google"; }
  });
  const setTranslator = (t: DubTranslator) => {
    setTranslatorState(t);
    try { localStorage.setItem("flowboard.dub.translator", t); } catch { /* private window */ }
  };
  const [channelId, setChannelId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<DubJob | null>(null);
  // several links started together: their jobs side by side; the editor opens once all of them are done
  const [batch, setBatch] = useState<{ id: string; jobs: DubJob[] } | null>(null);
  /** a finished clip opened in the editor while the rest of its batch still works */
  const [peek, setPeek] = useState(false);
  // every saved job, brief (no lines), newest first: the card shows RECENT_SHOWN, "Xem tất cả" the rest in a dialog
  const [recent, setRecent] = useState<DubJob[]>([]);
  const [allOpen, setAllOpen] = useState(false);
  // "📚 Thư viện link": links read out of .txt / .md files, each one dubbed or not yet; queued from the dialog
  const [linksOpen, setLinksOpen] = useState(false);
  const [linkFiles, setLinkFiles] = useState<File[] | null>(null);
  const [linksTodo, setLinksTodo] = useState(0);
  const refreshLinkCount = () => void listDubLinks().then((l) => setLinksTodo(l.counts.new ?? 0)).catch(() => undefined);
  const fileInput = useRef<HTMLInputElement>(null);
  // 📂 reopen a video this tool made: drop it on the page or pick it in the box
  const reopenInput = useRef<HTMLInputElement>(null);
  const [reopening, setReopening] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // a file picked for a NEW dub that turns out to be one of ours: offer to open its project instead
  const [fileMatch, setFileMatch] = useState<IdentifyResult | null>(null);
  const refreshRecent = () => void listDubJobsBrief().then(setRecent).catch(() => undefined);

  const loadStatus = useCallback(() => {
    void getDubStatus().then((s) => { setStatus(s); if (!s.separate) setKeepBgm(false); })
      .catch((e) => { toast.error(errMessage(e)); setStatus({ available: false, reason: errMessage(e), root: "", ytdlp: false, whisper: false, separate: false, styles: [], max_minutes: 30, remotion: false }); });
  }, []);
  useEffect(() => {
    document.title = "Lồng tiếng video · DFlow";
    loadStatus();
  }, [loadStatus]);
  useEffect(() => { refreshRecent(); refreshLinkCount(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // sent over from "📥 Thêm video": the links, or the videos already here (files / clips), and dub vs subtitles only
  useEffect(() => {
    const h = takeHandoff("dub");
    if (!h) return;
    if (h.mode) setMode(h.mode);
    if (h.videos.length) {
      setClips(h.videos.slice(0, MAX_PICKED).map((v, k) => ({ board_id: v.board_id ?? -(k + 1), name: v.name, media_id: v.media_id })));
      setLinks([""]);
      setFile(null);
    } else if (h.links.length) {
      setLinks(h.links.slice(0, MAX_LINKS));
    }
  }, []);
  // /tools/dub?links=1 (the "đang chạy" badge for links waiting in the library) opens the library
  useEffect(() => { if (searchParams.get("links")) setLinksOpen(true); }, [searchParams]);
  function closeLinks() {
    setLinksOpen(false);
    setLinkFiles(null);
    refreshLinkCount();
    if (searchParams.get("links")) {
      const next = new URLSearchParams(searchParams);
      next.delete("links");
      setSearchParams(next, { replace: true });
    }
  }

  // Keep "Gần đây" fresh while any job there still works (the queue advances on its own).
  const anyWorking = recent.some((j) => ["queued", "running", "rendering"].includes(j.status));
  useEffect(() => {
    if (!anyWorking) return;
    const t = window.setInterval(refreshRecent, 4000);
    return () => window.clearInterval(t);
  }, [anyWorking]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll while the job works; the lines become editable when it pauses or finishes.
  useEffect(() => {
    if (batch || !job || !isWorking(job)) return;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await getDubJob(job.job_id);
        if (stopped) return;
        setJob(j);
        if (j.status === "done") { toast.success("Video lồng tiếng xong — đã lưu thành clip."); refreshRecent(); }
        if (j.status === "error") toast.error(j.error ?? "Lồng tiếng lỗi.");
      } catch (e) {
        if (!stopped) { toast.error(errMessage(e)); setJob(null); }
      }
    };
    const timer = window.setInterval(tick, POLL_MS);
    void tick();
    return () => { stopped = true; window.clearInterval(timer); };
  }, [job?.job_id, job?.status, !!batch]); // eslint-disable-line react-hooks/exhaustive-deps

  // Batch: poll the whole batch while any clip works; when every clip is finished, open the editor
  // on the first one that has lines (the select on top switches between them).
  const batchWorking = !!batch && batch.jobs.some(isWorking);
  useEffect(() => {
    if (!batch) return;
    let stopped = false;
    const tick = async () => {
      try {
        const jobs = await listDubBatch(batch.id);
        if (stopped) return;
        setBatch((b) => (b && b.id === batch.id ? { ...b, jobs } : b));
        // the clip open in the editor is only replaced when it really changed (a new object would reload the editor)
        setJob((j) => {
          const n = j ? jobs.find((x) => x.job_id === j.job_id) : undefined;
          return n && j && (n.status !== j.status || n.media_id !== j.media_id || n.progress !== j.progress) ? n : j;
        });
        if (!jobs.some(isWorking)) {
          const ok = jobs.filter((x) => x.status === "done").length;
          const bad = jobs.filter((x) => x.status === "error").length;
          if (bad) toast.warning(`Loạt ${jobs.length} video xong: ${ok} được, ${bad} lỗi — xem từng clip trong trình chỉnh sửa.`);
          else toast.success(`Cả loạt ${jobs.length} video đã lồng tiếng xong.`);
          setJob((j) => (j && canEdit(j) ? j : jobs.find(canEdit) ?? j));
          refreshRecent();
        }
      } catch (e) {
        if (!stopped) toast.error(errMessage(e));
      }
    };
    if (!batchWorking) return;
    const timer = window.setInterval(tick, 3000);
    void tick();
    return () => { stopped = true; window.clearInterval(timer); };
  }, [batch?.id, batchWorking]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── link rows ──────────────────────────────────────────────────────────
  function setLink(i: number, v: string) {
    setLinks((ls) => ls.map((x, k) => (k === i ? v : x)));
    if (v) setFile(null);
  }
  function addRow(after?: number) {
    setLinks((ls) => {
      if (ls.length >= MAX_LINKS) { toast.warning(`Tối đa ${MAX_LINKS} link một lần.`); return ls; }
      const at = after === undefined ? ls.length : after + 1;
      const next = [...ls.slice(0, at), "", ...ls.slice(at)];
      window.setTimeout(() => linkInputs.current[at]?.focus(), 0);
      return next;
    });
  }
  function removeRow(i: number) {
    setLinks((ls) => (ls.length > 1 ? ls.filter((_, k) => k !== i) : [""]));
  }
  /** Several links pasted at once (one per line, or several Douyin shares) → one row each. */
  function onPasteLinks(i: number, e: ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text");
    const found = linksIn(text);
    if (found.length < 2) return;  // one link (maybe with share text around it): keep the paste as is
    e.preventDefault();
    setLinks((ls) => {
      // the pasted links take this row's place; other filled rows stay in order; no link twice
      const merged: string[] = [];
      for (const x of [...ls.slice(0, i), ...found, ...ls.slice(i + 1)]) {
        const v = x.trim();
        if (v && !merged.includes(v)) merged.push(v);
      }
      if (merged.length > MAX_LINKS) toast.warning(`Dán ${found.length} link — chỉ giữ ${MAX_LINKS} link đầu (tối đa một lần).`);
      return merged.slice(0, MAX_LINKS);
    });
    setFile(null);
  }
  function onLinkKey(i: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); addRow(i); }
    if (e.key === "Backspace" && !links[i] && links.length > 1) { e.preventDefault(); removeRow(i); window.setTimeout(() => linkInputs.current[Math.max(0, i - 1)]?.focus(), 0); }
  }
  const linkList = links.map((l) => l.trim()).filter(Boolean);
  const wantClips = searchParams.get("clips");
  useEffect(() => {
    if (!wantClips) return;
    const ids = wantClips.split(",").map(Number).filter((n) => n > 0).slice(0, MAX_PICKED);
    void clipVideos(ids).then((cs) => {
      if (!cs.length) { toast.warning("Clip này chưa có video để lồng tiếng."); return; }
      setClips(cs);
      setLinks([""]);
      setFile(null);
      toast.info(`Đã chọn ${cs.length} video từ Clip của tôi — chọn giọng rồi bấm Lồng tiếng.`);
    }).catch((e) => toast.error(errMessage(e)));
    const next = new URLSearchParams(searchParams);
    next.delete("clips");
    setSearchParams(next, { replace: true });
  }, [wantClips]); // eslint-disable-line react-hooks/exhaustive-deps
  // /tools/dub?grab=<ids>: videos downloaded on "📡 Cào video kênh" — dubbed as files, like picked clips
  const wantGrab = searchParams.get("grab");
  useEffect(() => {
    if (!wantGrab) return;
    const ids = wantGrab.split(",").map(Number).filter((n) => n > 0).slice(0, MAX_PICKED);
    void grabMedia(ids).then((ms) => {
      if (!ms.length) { toast.warning("Các video này chưa tải về máy — tải ở trang Cào video kênh trước."); return; }
      setClips(ms.map((m) => ({ board_id: -m.id, name: m.name, media_id: m.media_id, title: m.title || m.name })));
      setLinks([""]);
      setFile(null);
      toast.info(`Đã nhận ${ms.length} video từ Cào video kênh — chọn giọng rồi bấm Lồng tiếng.`);
    }).catch((e) => toast.error(errMessage(e)));
    const next = new URLSearchParams(searchParams);
    next.delete("grab");
    setSearchParams(next, { replace: true });
  }, [wantGrab]); // eslint-disable-line react-hooks/exhaustive-deps
  const sourceCount = clips.length || (file ? 1 : linkList.length);

  async function start() {
    if (!linkList.length && !file && !clips.length) { toast.warning("Dán link video, chọn file hoặc chọn từ Clip của tôi."); return; }
    if (linkList.length > MAX_LINKS) { toast.warning(`Tối đa ${MAX_LINKS} link một lần.`); return; }
    setStarting(true);
    try {
      let sourceMediaId: string | null = null;
      if (file) {
        toast.info("Đang tải file lên…");
        sourceMediaId = (await uploadDubVideo(file)).media_id;
      }
      // a grabbed video: its caption goes as the title (translated into a Vietnamese clip name), not as the name
      const sources: { url: string | null; source_media_id: string | null; clipName?: string; title?: string }[] = clips.length
        ? clips.map((c) => (c.title ? { url: null, source_media_id: c.media_id, title: c.title }
          : { url: null, source_media_id: c.media_id, clipName: c.name }))
        : file ? [{ url: null, source_media_id: sourceMediaId }] : linkList.map((l) => ({ url: l, source_media_id: null }));
      const batchId = sources.length > 1 ? `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}` : "";
      const started: DubJob[] = [];
      for (const src of sources) {
        started.push(await startDub({
          url: src.url, source_media_id: src.source_media_id, voice, keep_bgm: keepBgm, style, engine, channel_id: channelId,
          name: (sources.length > 1 ? (src.clipName ?? "") : (name.trim() || src.clipName || "")).slice(0, 80), title: src.title,
          auto_render: !review, batch_id: batchId, look_preset_id: lookId, translator, mode, sub_lang: lang,
        }));
      }
      if (batchId) {
        setBatch({ id: batchId, jobs: started });
        setJob(null);
        toast.success(`Đã xếp ${sources.length} video vào loạt — chạy lần lượt; xong cả loạt sẽ mở trình chỉnh sửa.`);
      } else {
        setBatch(null);
        setJob(started[0]);
      }
      setLinks([""]);
      setClips([]);
      announceRunning();
      refreshRecent();
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setStarting(false);
    }
  }

  /** What a recognised video opens: its dub project here, or the wizard clip it came from. */
  function openMatch(m: IdentifyResult) {
    if (m.kind === "dub") {
      openJob(m.job);
      toast.success(`Đã mở lại “${m.job.name || m.job.title || "video lồng tiếng"}” — chỉnh tiếp rồi bấm “Xuất lại video”.`);
    } else {
      toast.success(`Video này là clip “${m.name}” — mở lại ở Bước 5 của clip.`);
      navigate(`/clips/${m.board_id}/export`);
    }
  }
  async function reopenFromFile(f: File) {
    if (!f.type.startsWith("video/") && !/\.(mp4|mov|m4v|webm|mkv)$/i.test(f.name)) { toast.warning("Chỉ nhận file video."); return; }
    setReopening(true);
    try {
      openMatch(await identifyVideo(f));
    } catch (e) {
      toast.warning(errMessage(e));
    } finally {
      setReopening(false);
    }
  }
  /** A new file for dubbing: check in the background whether the tool already made it. */
  function pickNewFile(f: File | null) {
    setFile(f);
    setFileMatch(null);
    if (!f) return;
    setLinks([""]);
    void identifyVideo(f).then((m) => setFile((cur) => { if (cur === f) setFileMatch(m); return cur; })).catch(() => undefined);
  }
  function onDropPage(e: DragEvent<HTMLDivElement>) {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    setDragOver(false);
    const files = [...(e.dataTransfer.files ?? [])];
    // .txt / .md → their links go into the library; a video → reopen its project
    const texts = files.filter(isTextFile);
    if (texts.length) { setLinkFiles(texts); setLinksOpen(true); return; }
    const f = files[0];
    if (f) void reopenFromFile(f);
  }

  /** "🗑 Xoá khỏi danh sách": the jobs leave the list; their exported videos and clips stay. */
  async function removeFromList(ids: string[]) {
    try {
      const r = await deleteDubJobs(ids);
      if (r.deleted.length) {
        toast.success(`Đã xoá ${r.deleted.length} mục khỏi danh sách — video đã xuất và clip vẫn còn.`);
        if (job && r.deleted.includes(job.job_id)) { setJob(null); setBatch(null); setSearchParams({}, { replace: true }); }
      }
      if (r.skipped.length) toast.warning(`${r.skipped.length} mục chưa xoá: ${r.skipped.map((x) => x.reason).filter((v, i, a) => a.indexOf(v) === i).join("; ")}`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      refreshRecent();
    }
  }

  /** The lists are brief (no lines): fetch the whole job before opening it. */
  function openJobById(id: string) {
    setAllOpen(false);
    void getDubJob(id).then(openJob).catch((e) => toast.error(errMessage(e)));
  }

  function openJob(j: DubJob) {
    setJob(j);
    if (j.batch_id && j.batch_id !== batch?.id) {
      void listDubBatch(j.batch_id).then((jobs) => setBatch({ id: j.batch_id!, jobs })).catch(() => undefined);
    } else if (!j.batch_id) {
      setBatch(null);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  /** A video with its lines is edited in "🎞 Chỉnh sửa video": alone, or with the other finished clips of its batch
   *  (the select "Clip n/N", "⇪ Áp cho cả loạt"). */
  function editorPath(j: DubJob): string {
    const ids = batch ? batch.jobs.filter(canEdit).map((x) => x.job_id) : [j.job_id];
    return editPath(ids.includes(j.job_id) ? ids : [j.job_id], j.job_id);
  }

  // /tools/dub?job=<id>[&batch=<id>] (the "đang chạy" badge links here) opens that job / batch.
  const wantedJob = searchParams.get("job");
  const wantedBatch = searchParams.get("batch");
  useEffect(() => {
    if (wantedJob && job?.job_id !== wantedJob) {
      void getDubJob(wantedJob).then(openJob).catch(() => toast.warning("Không thấy video lồng tiếng này nữa (agent đã khởi động lại?)."));
    } else if (!wantedJob && wantedBatch && batch?.id !== wantedBatch) {
      void listDubBatch(wantedBatch).then((jobs) => { if (jobs.length) { setBatch({ id: wantedBatch, jobs }); setJob(null); } })
        .catch(() => undefined);
    }
  }, [wantedJob, wantedBatch]); // eslint-disable-line react-hooks/exhaustive-deps
  // …and the URL follows what is on screen, so a reload or the badge lands back on it.
  useEffect(() => {
    const want: Record<string, string> = {};
    if (batch) want.batch = batch.id;
    if (job) want.job = job.job_id;
    if (!Object.keys(want).length) return;
    if (searchParams.get("job") !== (want.job ?? null) || searchParams.get("batch") !== (want.batch ?? null)) setSearchParams(want, { replace: true });
  }, [job?.job_id, batch?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // An opened video with its lines goes to the editor page; a batch waits until every clip is done (the links were
  // pasted together: one sitting) unless a finished clip was opened on purpose ("✏️ Mở").
  const editing = !!job && canEdit(job) && (!batchWorking || (peek && !isWorking(job)));
  useEffect(() => {
    if (!editing || !job) return;
    // "← Danh sách" there comes back to the batch's progress while the others still work, else to the form
    navigate(editorPath(job), { replace: true, state: { back: batchWorking && batch ? `/tools/dub?batch=${batch.id}` : "/tools/dub" } });
  }, [editing, job?.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === null) return <PageLoading text="Đang kiểm tra công cụ lồng tiếng…" />;
  const working = (!!job && isWorking(job)) || batchWorking;
  const styleOptions = engine === "remotion" ? status.remotion_styles ?? [] : status.styles;
  function pickEngine(next: DubEngine) {
    setEngine(next);
    const opts = next === "remotion" ? status?.remotion_styles ?? [] : status?.styles ?? [];
    if (!opts.some((o) => o.key === style)) setStyle(opts[0]?.key ?? (next === "remotion" ? "rm_box" : "box_yellow"));
  }
  const batchJobs = batch?.jobs ?? [];
  const batchDone = batchJobs.filter((j) => j.status === "done").length;
  // what a link queued from the library is dubbed with: this form, summed up in one line
  const lookName = looks.find((p) => p.id === lookId)?.name;
  const styleName = styleOptions.find((o) => o.key === style)?.label ?? style;
  const linkSettings = [
    subOnly ? "chỉ chèn phụ đề, giữ tiếng gốc" : (VOICES[voice] ?? voice).split(" · ").filter((x, i, a) => a.indexOf(x) === i).join(" · "),
    lang === "orig" ? "phụ đề ngôn ngữ gốc, không dịch" : lang !== "vi" ? `phụ đề ${subLangName(lang)} (Google Dịch)`
      : translator === "ai" ? "dịch bằng AI" : "dịch bằng Google",
    !subOnly && status.separate ? (keepBgm ? "giữ nhạc nền" : "bỏ nhạc nền") : "",
    lookName ? `kiểu “${lookName}”` : `phụ đề ${styleName}`,
    review ? "dừng ở bản dịch để xem lại" : "tự xuất video",
    channelId ? "gắn kênh đã chọn" : "",
  ].filter(Boolean).join(" · ");

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">🎙 Lồng tiếng video{editing && job ? ` › ${job.name || job.title || "chỉnh sửa"}` : ""}</span>
      </header>
      {!editing && <VideoToolsTabs />}
      <div className={`qt-home qt-dub${dragOver && !editing ? " is-dropping" : ""}`}
           onDragOver={(e) => { if (!editing && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragOver(true); } }}
           onDragLeave={(e) => { if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false); }}
           onDrop={(e) => { if (!editing) onDropPage(e); }}>
        {dragOver && !editing && (
          <div className="qt-dub__dropmask"><div>📂 Thả video vào để mở lại và chỉnh tiếp<small>hoặc file .txt / .md để lấy link vào thư viện</small></div></div>
        )}
        {editing ? (
          <PageLoading text="Đang mở trình chỉnh sửa…" />
        ) : !status.available && status.addon ? (
          <div className="qt-dub__addon"><DubAddonCard initial={status.addon} onReady={loadStatus} /></div>
        ) : !status.available ? (
          <PageEmpty icon="🎙" title="Chưa dùng được trên máy này">
            {status.reason ?? "Máy này chưa có bộ cài lồng tiếng."}
          </PageEmpty>
        ) : (
          <div className="qt-dub__grid">
            <div className="qt-dub__left">
              <section className="qt-card">
                <div className="qt-card__eyebrow">1 · Video gốc</div>
                <h3 className="qt-card__title">Link hoặc file</h3>
                <p className="qt-card__hint">
                  Dán link TikTok / Douyin / YouTube / Instagram / Facebook / X (tối đa {status.max_minutes} phút). AI nghe tiếng gốc
                  (Whisper), dịch sang tiếng Việt nói, đọc lại bằng giọng Việt, bỏ tiếng gốc{status.separate ? " (giữ được nhạc nền)" : ""} và in phụ đề.
                </p>
                {status.slow_reason && <p className="qt-nogpu">🐢 {status.slow_reason}</p>}
                <div className="qt-field">
                  <span>Link video <small>(mỗi ô một link, tối đa {MAX_LINKS} — dán một lúc nhiều link cũng tự tách; dán cả đoạn share Douyin cũng được)</small></span>
                  <div className="qt-dub__links">
                    {links.map((l, i) => (
                      <div key={i} className="qt-dub__linkrow">
                        <span className="qt-dub__linkno">{i + 1}</span>
                        <input ref={(el) => { linkInputs.current[i] = el; }} value={l} disabled={starting}
                               placeholder={i === 0 ? "https://v.douyin.com/… hoặc https://www.tiktok.com/@…/video/…" : "Link tiếp theo…"}
                               onChange={(e) => setLink(i, e.target.value)} onPaste={(e) => onPasteLinks(i, e)} onKeyDown={(e) => onLinkKey(i, e)} />
                        {links.length > 1 && <button type="button" className="qt-dub__linkx" title="Bỏ link này" onClick={() => removeRow(i)}>×</button>}
                      </div>
                    ))}
                    <div className="qt-dub__linktools">
                      {links.length < MAX_LINKS && (
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost qt-dub__addlink" disabled={starting} onClick={() => addRow()}>＋ Thêm link</button>
                      )}
                      <button type="button" className="qt-btn qt-btn--small qt-dub__libbtn" disabled={starting} onClick={() => setLinksOpen(true)}
                              title="Có cả danh sách link trong file .txt / .md? Nhập vào đây — tool nhớ link nào đã lồng tiếng và làm dần những link chưa làm">
                        📄 Nhập danh sách link từ file{linksTodo > 0 && <span className="qt-dub__libcount">{linksTodo} chưa làm</span>}
                      </button>
                    </div>
                  </div>
                  {linkList.length > 1 && <small className="qt-card__hint">{linkList.length} video sẽ chạy lần lượt thành một loạt; xong cả loạt mới mở trình chỉnh sửa (chọn clip ở trên, áp kiểu cho cả loạt).</small>}
                </div>
                <div className="qt-dub__or">
                  <span>hoặc</span>
                  <input ref={fileInput} type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska" hidden
                         onChange={(e) => { const f = e.target.files?.[0] ?? null; e.target.value = ""; pickNewFile(f); }} />
                  <button type="button" className="qt-btn qt-btn--small" disabled={starting} onClick={() => fileInput.current?.click()}>⬆ Chọn file video</button>
                  {file && <small>{file.name} · {(file.size / 1048576).toFixed(1)} MB <button type="button" className="qt-link" onClick={() => pickNewFile(null)}>bỏ</button></small>}
                </div>
                <div className="qt-dub__or">
                  <span>hoặc</span>
                  <button type="button" className="qt-btn qt-btn--small" disabled={starting} onClick={() => setPickOpen(true)}
                          title="Lồng tiếng video đã cắt ở ✂️ Cắt video, hoặc clip đã ghép">🎬 Chọn từ Clip của tôi</button>
                  {clips.length > 0 && <small>{clips.length} video <button type="button" className="qt-link" onClick={() => setClips([])}>bỏ</button></small>}
                </div>
                {clips.length > 0 && (
                  <ul className="qt-dub__clips">
                    {clips.map((c) => (
                      <li key={c.board_id}>
                        <span>🎬 {c.name}</span>
                        <button type="button" className="qt-dub__linkx" title="Bỏ video này" onClick={() => setClips((cs) => cs.filter((x) => x.board_id !== c.board_id))}>×</button>
                      </li>
                    ))}
                  </ul>
                )}
                {file && fileMatch && (
                  <div className="qt-dub__match">
                    <span>🎬 Video này bạn đã làm bằng tool{fileMatch.kind === "dub" ? `: “${fileMatch.job.name || fileMatch.job.title || "video lồng tiếng"}”` : ` (clip “${fileMatch.name}”)`}.</span>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => { const m = fileMatch; pickNewFile(null); openMatch(m); }}>✏️ Mở lại để chỉnh</button>
                    <small>hoặc bấm Lồng tiếng để làm lại từ đầu.</small>
                  </div>
                )}
                <label className="qt-field">
                  <span>Tên clip <small>(không bắt buộc — AI tự đặt)</small></span>
                  <input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Mẹo giảm căng bụng cho mẹ bầu" />
                </label>
              </section>

              <section className="qt-card">
                <div className="qt-card__eyebrow">2 · Giọng & phụ đề</div>
                <div className="qt-field"><span>Làm gì với video</span>
                  <ModePicker name="dub-mode" value={subOnly ? "sub" : "dub"} onChange={setMode} disabled={working} />
                </div>
                {subOnly && (
                  <label className="qt-field">
                    <span>Phụ đề bằng</span>
                    <select value={subLang} onChange={(e) => setSubLang(e.target.value as SubLang)} disabled={working}>
                      {SUB_LANGS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
                    </select>
                  </label>
                )}
                {subOnly && subLang === "orig" && <p className="qt-card__hint">Phụ đề đúng lời nói trong video (video tiếng Anh → phụ đề tiếng Anh), không dịch.</p>}
                {!subOnly && <VoiceField value={voice} onChange={setVoice} sampleText="Các mẹ bầu bị căng cứng bụng cuối thai kỳ thì nhớ đeo đai nâng bụng ngay nha." disabled={working} />}
                {looks.length > 0 && (
                  <label className="qt-field">
                    <span>Template <small className="qt-card__hint">(kiểu phụ đề, vùng mờ, khung xuất, khung, nhân vật… đã lưu từ clip trước — lưu / đặt mặc định ở nút ★ Template trong trình chỉnh sửa)</small></span>
                    <select value={lookId ?? ""} onChange={(e) => setLookId(e.target.value ? Number(e.target.value) : null)} disabled={working}>
                      <option value="">— Không dùng template, chỉnh tay —</option>
                      {looks.map((p) => <option key={p.id} value={p.id}>{p.favorite ? "★ " : ""}{p.name}{p.uses ? ` · dùng ${p.uses} lần` : ""}</option>)}
                    </select>
                  </label>
                )}
                {lookId !== null && <p className="qt-card__hint">Kiểu phụ đề lấy theo template đã chọn; ô dưới chỉ dùng khi không chọn template.</p>}
                <label className="qt-field">
                  <span>Cách vẽ phụ đề <small className="qt-card__hint">(nhanh · hoặc đẹp: font Việt, emoji màu, chữ sáng từng từ)</small></span>
                  <select value={engine} onChange={(e) => pickEngine(e.target.value as DubEngine)} disabled={working || lookId !== null}>
                    <option value="ass">Phụ đề nhanh</option>
                    <option value="remotion" disabled={!status.remotion}>
                      Phụ đề đẹp — font Việt, emoji màu{status.remotion ? "" : " (chưa cài bộ cài phụ đề đẹp)"}
                    </option>
                  </select>
                </label>
                {!status.remotion && (status.remotion_addon?.supported
                  ? <RemotionAddonCard compact initial={status.remotion_addon} onReady={loadStatus} />
                  : status.remotion_reason && <p className="qt-card__hint">Phụ đề đẹp chưa dùng được: {status.remotion_reason}</p>)}
                {lang === "vi" && (
                  <label className="qt-field">
                    <span>Dịch bằng</span>
                    <select value={translator} onChange={(e) => setTranslator(e.target.value as DubTranslator)} disabled={working}>
                      <option value="google">Google Dịch — miễn phí, không tốn lượt AI</option>
                      <option value="ai">AI theo Cài đặt (Claude / Gemini…) — câu nói tự nhiên, vừa giờ hơn, tốn lượt AI</option>
                    </select>
                  </label>
                )}
                {lang === "vi" && translator === "ai" && <p className="qt-card__hint">AI hết lượt / lỗi giữa chừng thì phần còn lại tự dịch bằng Google, video không bị dừng.</p>}
                {lang !== "vi" && lang !== "orig" && <p className="qt-card__hint">Dịch sang {subLangName(lang)} bằng Google Dịch (miễn phí).</p>}
                <label className="qt-field">
                  <span>Kiểu phụ đề</span>
                  <select value={style} onChange={(e) => setStyle(e.target.value)} disabled={working || lookId !== null}>
                    {styleOptions.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </label>
                {engine === "remotion" && <p className="qt-card__hint">Phụ đề đẹp xuất chậm hơn phụ đề nhanh (ước 1–3 phút cho clip 1 phút); lần đầu còn tải Chrome (~150 MB) và đóng gói giao diện.</p>}
                {!subOnly && (
                  <label className="qt-check" title={status.separate ? "Tách giọng nói khỏi nhạc (spleeter), giữ nhạc nền dưới giọng Việt" : "Máy này chưa có mô hình tách giọng"}>
                    <input type="checkbox" checked={keepBgm} disabled={!status.separate || working} onChange={(e) => setKeepBgm(e.target.checked)} /> Giữ nhạc nền gốc (tách giọng nói ra)
                  </label>
                )}
                <label className="qt-check" title="Dừng sau khi dịch để bạn sửa từng câu, rồi mới render">
                  <input type="checkbox" checked={review} disabled={working} onChange={(e) => setReview(e.target.checked)} /> Xem lại bản dịch trước khi render
                </label>
                <ChannelPicker value={channelId} onChange={setChannelId} label="Lưu vào kênh" disabled={working} />
                <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={starting} onClick={() => void start()}>
                  {starting ? "Đang gửi…" : sourceCount > 1 ? `${subOnly ? "💬 Chèn phụ đề" : "🎙 Lồng tiếng"} ${sourceCount} video`
                    : working ? "➕ Thêm vào hàng đợi" : subOnly ? "💬 Chèn phụ đề" : "🎙 Lồng tiếng"}
                </button>
              </section>

              {recent.length > 0 && (
                <section className="qt-card">
                  <div className="qt-card__head">
                    <h3 className="qt-card__title">Gần đây</h3>
                    <button type="button" className="qt-link" onClick={() => setAllOpen(true)}>Xem tất cả ({recent.length})</button>
                  </div>
                  <ul className="qt-dub__recent">
                    {recent.slice(0, RECENT_SHOWN).map((j) => (
                      <li key={j.job_id}>
                        <span className={`qt-dub__dot qt-dub__dot--${j.status}`} />
                        <span className="qt-today__what" title={jobTitle(j)}>{jobTitle(j)}</span>
                        <span className="qt-today__meta">{j.status === "done" ? "xong" : j.status === "error" ? "lỗi" : j.status === "review" ? "chờ sửa" : j.status === "queued" ? j.phase || "chờ đến lượt" : `${j.phase} ${j.progress}%`}</span>
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => openJobById(j.job_id)}>Mở</button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="qt-card qt-dub__reopen">
                <span className="qt-dub__reopenicon" aria-hidden="true">📂</span>
                <div className="qt-dub__reopentext">
                  <strong>Mở lại video đã lồng tiếng</strong>
                  <small>Có file video đã tải từ tool? Chọn hoặc kéo thả vào trang này — mở lại đúng chỗ đã chỉnh, kể cả hôm sau.</small>
                </div>
                <input ref={reopenInput} type="file" accept="video/*" hidden
                       onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void reopenFromFile(f); }} />
                <button type="button" className="qt-btn qt-btn--small" disabled={reopening} onClick={() => reopenInput.current?.click()}>
                  {reopening ? "Đang nhận ra…" : "Chọn video…"}
                </button>
              </section>
            </div>

            <div className="qt-dub__right">
              {batch && (batchWorking || !job) && !editing ? (
                <section className="qt-card">
                  <div className="qt-card__head">
                    <div>
                      <h3 className="qt-card__title">Loạt {batchJobs.length} video</h3>
                      <small className="qt-card__hint">{batchWorking ? `đang lồng tiếng lần lượt — ${batchDone}/${batchJobs.length} xong` : `${batchDone}/${batchJobs.length} xong`}</small>
                    </div>
                    {!batchWorking && batchJobs.some(canEdit) && (
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => setJob(batchJobs.find(canEdit) ?? null)}>✏️ Mở trình chỉnh sửa</button>
                    )}
                  </div>
                  <ol className="qt-dub__batch">
                    {batchJobs.map((j, i) => (
                      <li key={j.job_id} className={`is-${j.status}`}>
                        <span className="qt-dub__batchno">{i + 1}</span>
                        <div className="qt-dub__batchbody">
                          <div className="qt-dub__batchname">{j.name || j.title || j.url || "Video"}</div>
                          <div className="qt-dub__batchstate">
                            {j.status === "done" ? "✓ xong" : j.status === "error" ? `⚠ ${j.error ?? "lỗi"}` : j.status === "review" ? "chờ sửa bản dịch"
                              : j.status === "queued" ? (j.phase || "chờ đến lượt") : `${j.phase}… ${j.progress}%`}
                          </div>
                          {isWorking(j) && j.status !== "queued" && <div className="qt-dub__bar"><span style={{ width: `${j.progress}%` }} /></div>}
                        </div>
                        {isWorking(j) && <StopButton stopping={j.stopping} onStop={() => stopDub(j.job_id).catch((e) => { toast.error(errMessage(e)); throw e; })} />}
                        {batchWorking && !isWorking(j) && canEdit(j) && (
                          <button type="button" className="qt-btn qt-btn--small" title="Mở video này để xem / chỉnh ngay — các video khác vẫn chạy tiếp"
                                  onClick={() => { setPeek(true); setJob(j); }}>✏️ Mở</button>
                        )}
                      </li>
                    ))}
                  </ol>
                  <p className="qt-card__hint">Video nào xong bấm "✏️ Mở" để xem / chỉnh ngay. Xong cả loạt sẽ mở trình chỉnh sửa: chọn clip ở ô trên cùng, chỉnh một clip rồi bấm "⇪ Áp cho cả loạt" để mọi clip cùng kiểu chữ, khung, nhân vật.</p>
                </section>
              ) : !job ? (
                <div className="qt-empty qt-dub__placeholder">Tiến độ hiện ở đây. Xong là mở trình chỉnh sửa: xem video với giọng Việt, sửa chữ ngay trên hình, kéo câu trên timeline.</div>
              ) : (
                (isWorking(job) || job.status === "error") ? (
                  <ProgressRing
                    percent={job.progress}
                    error={job.status === "error"}
                    waiting={job.status === "queued"}
                    title={job.name || job.title || "Video lồng tiếng"}
                    hint={`${job.language ? `tiếng gốc: ${job.language}` : ""}${job.duration_s ? ` · ${job.duration_s}s` : ""}${job.segments.length ? ` · ${job.segments.length} câu` : ""}`.replace(/^ · /, "")}
                    phase={job.status === "queued" ? job.phase || "Chờ đến lượt" : `${job.phase}…`}
                    message={job.error ?? undefined}
                    stopping={job.stopping}
                    onStop={isWorking(job) ? () => stopDub(job.job_id).then(setJob, (e) => { toast.error(errMessage(e)); throw e; }) : undefined}
                  />
                ) : (
                  <section className="qt-card">
                    <div className="qt-card__head">
                      <div>
                        <h3 className="qt-card__title">{job.name || job.title || "Video lồng tiếng"}</h3>
                        <small className="qt-card__hint">
                          {job.language ? `tiếng gốc: ${job.language}` : ""}{job.duration_s ? ` · ${job.duration_s}s` : ""}{job.segments.length ? ` · ${job.segments.length} câu` : ""}
                        </small>
                      </div>
                    </div>
                  </section>
                )
              )}
            </div>
          </div>
        )}
      </div>
      {allOpen && <DubJobsDialog jobs={recent} onOpen={openJobById} onClose={() => setAllOpen(false)} onDelete={removeFromList} />}
      {pickOpen && (
        <ClipPickDialog max={MAX_PICKED} initial={clips} onClose={() => setPickOpen(false)}
                        onPick={(cs) => { setClips(cs); setPickOpen(false); setLinks([""]); pickNewFile(null); }} />
      )}
      {linksOpen && (
        <DubLinksDialog
          onVoice={setVoice}
          settings={{ voice, keep_bgm: keepBgm && !!status.separate, style, engine, channel_id: channelId, auto_render: !review, look_preset_id: lookId, translator, mode, sub_lang: lang }}
          settingsLabel={linkSettings} importFiles={linkFiles}
          onOpenJob={(id) => { closeLinks(); openJobById(id); }}
          onOpenClip={(boardId) => { closeLinks(); navigate(`/clips/${boardId}/export`); }}
          onQueued={() => { announceRunning(); refreshRecent(); }}
          onClose={closeLinks}
        />
      )}
    </>
  );
}
