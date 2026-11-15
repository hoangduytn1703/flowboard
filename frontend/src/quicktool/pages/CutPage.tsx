import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import { askConfirm } from "../../components/Dialogs";
import { ZipSaveButton } from "../../components/ZipSaveButton";
import {
  getDefaultLook, getDubJob, linksIn, listLookPresets, normAdjust, normSpeed, normVolume, SPEED_MARKS, SPEED_MAX, SPEED_MIN, speedLabel, VOLUME_MARKS, VOLUME_MAX, volumeLabel, subLangName, uploadDubVideo,
  type DecorPreset, type DubCutRow,
} from "../../api/dub";
import { TickRange } from "../../components/TickRange";
import { StopButton } from "../../components/StopButton";
import {
  cutAgain, cutNow, deleteCutSessions, getCutStatus, hearCut, isBusy, isHearing, LENGTHS, listCutParts, listCutSessions,
  listCutPrompts, pipeText, startCut, stopCut, suggestCut,
  type CutHow, type CutPartView, type CutPrompt, type CutSession, type CutToolStatus,
} from "../../api/cut";
import { grabMedia } from "../../api/grab";
import { ChannelPicker } from "../channels/ChannelPicker";
import { editPath, MAX_EDIT_TOGETHER } from "../../api/edit";
import { fmtClock } from "../dub/editor/CutPane";
import { PageEmpty, PageLoading } from "../PageState";
import { PromptBox } from "../cut/PromptBox";
import { newRow, PartsTable, planParts, rowsFrom, type PlanRow } from "../cut/PartsTable";
import { clockText } from "../cut/MinSec";
import { toast } from "../../store/toast";
import "../dub.css";
import { setGain } from "../../lib/audioBoost";
import "../posts.css";
import "../cut.css";

const MAX_LINKS = 10;
const FORM_KEY = "flowboard.cut.form";
const WORKING = ["queued", "running", "rendering"];
const MAX_PARTS_CHOICES = [0, 3, 5, 8, 10, 15, 20, 30];
const DEFAULT_LANGS = ["Việt", "Tây Ban Nha", "Anh"];
const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

interface FormPrefs { how: CutHow; lenKey: string; maxParts: number; review: boolean; promptId: string; titleLang: string; customMin: number }
/** "Tuỳ chỉnh": the length of one part typed in minutes (0,5–20) */
const CUSTOM = "custom";
const cleanMin = (v: unknown) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? Math.min(20, Math.max(0.5, Math.round(n * 10) / 10)) : 2; };
const minLabel = (m: number) => `${String(m).replace(".", ",")} phút`;
function copyText(text: string, ok: string) {
  void navigator.clipboard.writeText(text).then(() => toast.success(ok)).catch(() => toast.error("Không copy được — bôi đen rồi Ctrl+C."));
}

function loadForm(): FormPrefs {
  const def: FormPrefs = { how: "ai", lenKey: "30-60", maxParts: 0, review: false, promptId: "", titleLang: "", customMin: 2 };
  try {
    const raw = JSON.parse(window.localStorage.getItem(FORM_KEY) || "{}") as Partial<FormPrefs>;
    return {
      // "Chia đều" left the form (10/11): a form saved with it opens on "Tự cắt", which took its place
      how: raw.how === "prompt" || raw.how === "manual" ? raw.how : raw.how === "even" ? "manual" : "ai",
      lenKey: raw.lenKey === CUSTOM || LENGTHS.some((l) => l.key === raw.lenKey) ? raw.lenKey! : def.lenKey,
      customMin: cleanMin(raw.customMin),
      maxParts: MAX_PARTS_CHOICES.includes(Number(raw.maxParts)) ? Number(raw.maxParts) : 0,
      review: !!raw.review,
      promptId: typeof raw.promptId === "string" ? raw.promptId : "",
      titleLang: typeof raw.titleLang === "string" ? raw.titleLang.slice(0, 30) : "",
    };
  } catch {
    return def;
  }
}

interface UpFile { key: string; name: string; media_id?: string; busy: boolean; error?: string }

/** "✨ Gợi ý lại" (after the video is heard): the AI, a request, or spread evenly — "Tự cắt" is the table itself */
const SUGGEST_HOWS: { key: CutHow; icon: string; label: string }[] = [
  { key: "ai", icon: "✨", label: "AI tự chọn đoạn hay" },
  { key: "prompt", icon: "✍️", label: "Theo yêu cầu của bạn" },
  { key: "even", icon: "⇔", label: "Chia đều" },
];

function hostOf(url: string | null): string {
  if (!url) return "";
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}
function sessionName(s: CutSession): string {
  return s.title || hostOf(s.url) || "Video";
}

/**
 * "✂️ Cắt video": paste links (or pick files) → one press → many short videos, no dubbing. The AI picks the parts from
 * what is said (its own pick, or the seller's request), or the video is spread evenly. Every part is a clip in "Clip của
 * tôi" and opens in the editor (subtitles from the words heard or translated, format + background, blur, frame, key
 * moments) — one video, or all of them at once ("⇪ Áp cho cả loạt"). Dubbing is a separate step ("🎙 Lồng tiếng").
 */
export function CutPage() {
  const navigate = useNavigate();
  useEffect(() => { document.title = "Cắt video · DFlow"; }, []);
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<CutToolStatus | null>(null);
  const [sessions, setSessions] = useState<CutSession[] | null>(null);
  const [links, setLinks] = useState<string[]>([""]);
  const [files, setFiles] = useState<UpFile[]>([]);
  // saved cut prompts (with the account): each analysed video's editor picks from them
  const [prompts, setPrompts] = useState<CutPrompt[]>([]);
  const [channelId, setChannelId] = useState<number | null>(null);
  // "★ Mẫu chỉnh sửa": the saved look (9:16 frame, background, sticker, blur boxes…) every part is rendered in;
  // the default one is pre-picked, like the dubbing form
  const [looks, setLooks] = useState<DecorPreset[]>([]);
  const [lookId, setLookId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  // videos ticked on any card of the page (their editing jobs): "✏️ Chỉnh N video" opens them all side by side
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const pickParts = (ids: string[], on: boolean) => setPicked((cur) => {
    const n = new Set(cur);
    for (const id of ids) { if (on) n.add(id); else n.delete(id); }
    return n;
  });
  const fileInput = useRef<HTMLInputElement>(null);
  const linkInputs = useRef<(HTMLInputElement | null)[]>([]);
  const cardRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    void getCutStatus().then(setStatus).catch(() => setStatus({ whisper: false, whisper_reason: "", remotion: false, max_minutes: 60,
      max_links: MAX_LINKS, max_parts: 30, prompt_max: 4000, default_min: 30, default_max: 60 }));
    void listLookPresets().then(setLooks).catch(() => setLooks([]));
    void listCutPrompts().then(setPrompts).catch(() => undefined);
    void getDefaultLook().then((d) => setLookId(d.id)).catch(() => undefined);
  }, []);
  function refresh() {
    void listCutSessions().then(setSessions).catch((e) => { toast.error(errMessage(e)); setSessions((s) => s ?? []); });
  }
  const anyBusy = (sessions ?? []).some((s) => isBusy(s) || isHearing(s)) || (sessions ?? []).some((s) => s.parts.some((p) => p.status && WORKING.includes(p.status)));
  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, anyBusy ? 3000 : 15000);
    return () => window.clearInterval(t);
  }, [anyBusy]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── editing happens in "🎞 Chỉnh sửa video" ─────────────────────────────
  const BACK = { state: { back: "/tools/cut" } };
  // an old link /tools/cut?job=<part>[&run=<run>][&parts=<job ids>]: sent on to the editor with the same videos
  const wantJob = params.get("job");
  const wantRun = params.get("run");
  const wantParts = params.get("parts");
  useEffect(() => {
    if (!wantJob) return;
    let gone = false;
    void (async () => {
      try {
        let ids = wantParts ? wantParts.split(",") : [];
        if (!ids.length) {
          const run = wantRun || (await getDubJob(wantJob)).cut?.run_id || "";
          ids = run ? (await listCutParts({ run })).map((x) => x.job_id) : [wantJob];
        }
        if (!gone) navigate(editPath(ids.length ? ids : [wantJob], wantJob), { replace: true, ...BACK });
      } catch (e) {
        if (!gone) { toast.error(errMessage(e)); setParams({}, { replace: true }); }
      }
    })();
    return () => { gone = true; };
  }, [wantJob, wantRun, wantParts]); // eslint-disable-line react-hooks/exhaustive-deps

  /** "✏️ Chỉnh": this part with the other parts of its video (or only the ticked ones) in the editor. */
  function openEditor(part: { job_id: string }, s: CutSession, only?: string[]) {
    const ids = only && only.length > 1 ? only : s.parts.filter((p) => p.job_id && p.status !== "missing").map((p) => p.job_id);
    navigate(editPath(ids.includes(part.job_id) ? ids : [part.job_id, ...ids], part.job_id), BACK);
  }
  /** "✏️ Chỉnh N video" with videos ticked on several cards. */
  function openEditorMany(ids: string[]) {
    if (!ids.length) return;
    if (ids.length > MAX_EDIT_TOGETHER) toast.warning(`Mở ${MAX_EDIT_TOGETHER} video đầu — trình chỉnh sửa nhận tối đa ${MAX_EDIT_TOGETHER} video một lượt.`);
    navigate(editPath(ids), BACK);
  }

  // ── the form ─────────────────────────────────────────────────────────────
  const cleanLinks = links.map((l) => l.trim()).filter(Boolean);
  const readyFiles = files.filter((f) => f.media_id);
  const count = cleanLinks.length + readyFiles.length;
  function setLinkAt(i: number, value: string) {
    const found = linksIn(value);
    if (found.length > 1) {
      const next = [...links.slice(0, i), ...found, ...links.slice(i + 1)].filter((x, k, a) => x.trim() || k === a.length - 1);
      setLinks(next.slice(0, MAX_LINKS));
      if (links.length + found.length - 1 > MAX_LINKS) toast.warning(`Tối đa ${MAX_LINKS} link một lần.`);
      return;
    }
    setLinks(links.map((l, k) => (k === i ? value : l)));
  }
  function addLinkRow(after: number) {
    if (links.length >= MAX_LINKS) return;
    const next = [...links.slice(0, after + 1), "", ...links.slice(after + 1)];
    setLinks(next);
    window.setTimeout(() => linkInputs.current[after + 1]?.focus(), 0);
  }
  function removeLinkRow(i: number) {
    setLinks(links.length > 1 ? links.filter((_, k) => k !== i) : [""]);
  }
  async function addFiles(list: FileList | null) {
    const picked = Array.from(list ?? []).filter((f) => f.type.startsWith("video/") || /\.(mp4|mov|webm|mkv)$/i.test(f.name));
    if (!picked.length) return;
    const room = MAX_LINKS - cleanLinks.length - files.length;
    if (picked.length > room) toast.warning(`Tối đa ${MAX_LINKS} video một lần.`);
    const items = picked.slice(0, Math.max(0, room)).map((f) => ({ file: f, item: { key: `${f.name}-${f.size}-${Math.random()}`, name: f.name, busy: true } as UpFile }));
    setFiles((fs) => [...fs, ...items.map((x) => x.item)]);
    for (const { file, item } of items) {
      try {
        const r = await uploadDubVideo(file);
        setFiles((fs) => fs.map((x) => (x.key === item.key ? { ...x, busy: false, media_id: r.media_id } : x)));
      } catch (e) {
        setFiles((fs) => fs.map((x) => (x.key === item.key ? { ...x, busy: false, error: errMessage(e) } : x)));
      }
    }
  }

  // /tools/cut?grab=<ids>: videos downloaded on "📡 Cào video kênh" — they join the form as files
  const wantGrab = params.get("grab");
  useEffect(() => {
    if (!wantGrab) return;
    const ids = wantGrab.split(",").map(Number).filter((n) => n > 0).slice(0, MAX_LINKS);
    void grabMedia(ids).then((ms) => {
      if (!ms.length) { toast.warning("Các video này chưa tải về máy — tải ở trang Cào video kênh trước."); return; }
      setFiles(ms.map((m) => ({ key: `grab-${m.id}`, name: m.name, media_id: m.media_id, busy: false })));
      setLinks([""]);
      toast.info(`Đã nhận ${ms.length} video từ Cào video kênh — bấm 🔍 Phân tích để chọn đoạn cắt.`);
    }).catch((e) => toast.error(errMessage(e)));
    const next = new URLSearchParams(params);
    next.delete("grab");
    setParams(next, { replace: true });
  }, [wantGrab]); // eslint-disable-line react-hooks/exhaustive-deps

  /** "🔍 Phân tích": download + hear every video; each one then waits on its card for its parts (typed or the AI's). */
  async function start() {
    if (!count || starting) return;
    setStarting(true);
    try {
      const r = await startCut({ links: cleanLinks, media: readyFiles.map((f) => ({ media_id: f.media_id!, name: f.name })), how: "manual", prompt: "",
                                 min_s: 30, max_s: 60, max_parts: 0, review: true, channel_id: channelId, analyze: true, look_preset_id: lookId });
      toast.success(r.sessions.length > 1
        ? `Đang tải ${r.sessions.length} video — video nào tải xong trước thì chọn đoạn cắt cho video đó trước, không phải chờ nghe lời.`
        : "Đang tải video — tải xong là chọn đoạn cắt được ngay trên thẻ của nó, không phải chờ nghe lời.");
      setLinks([""]);
      setFiles([]);
      announceRunning();
      refresh();
      setParams({ run: r.run_id }, { replace: true });
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setStarting(false);
    }
  }

  // ?run= / ?session= (the badge, the assistant): bring that video into view
  const focusRun = params.get("run");
  const focusSession = params.get("session");
  useEffect(() => {
    if (wantJob || !sessions) return;
    const target = sessions.find((s) => s.id === focusSession) ?? sessions.find((s) => s.run_id === focusRun);
    if (target) cardRefs.current[target.id]?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusRun, focusSession, !!sessions]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!status || !sessions) return <PageLoading text="Đang mở công cụ cắt video…" />;
  // every cut video on the page that can open in the editor, card by card; the ticked ones among them
  const allParts = sessions.flatMap((s) => s.parts.filter((p) => p.job_id && p.status !== "missing"));
  const pickedAll = allParts.filter((p) => picked.has(p.job_id));
  const allPartsPicked = allParts.length > 0 && pickedAll.length === allParts.length;
  const pickedFrom = sessions.filter((s) => s.parts.some((p) => picked.has(p.job_id))).length;

  if (wantJob) return <PageLoading text="Đang mở trình chỉnh sửa…" />;

  return (
    <>
      <header className="qt-header"><span className="qt-header__crumb">✂️ Cắt video</span></header>
      <div className="qt-home ct">
        <div className="ct__grid">
          <div className="ct__left">
            <section className="qt-card">
              <div className="qt-card__eyebrow">1 · Video cần cắt</div>
              <h3 className="qt-card__title">Link hoặc file</h3>
              <p className="qt-card__hint">
                TikTok, Douyin, YouTube, Facebook, Instagram, X — video dài tối đa {status.max_minutes} phút. Không lồng tiếng: video giữ
                nguyên tiếng gốc. Muốn lồng tiếng thì làm sau ở bước 🎙.
              </p>
              {status.slow_reason && <p className="qt-nogpu">🐢 {status.slow_reason}</p>}
              <div className="ct__links">
                {links.map((l, i) => (
                  <div key={i} className="ct__linkrow">
                    <input ref={(el) => { linkInputs.current[i] = el; }} className="qt-input" value={l} placeholder="Dán link video (dán nhiều link một lúc cũng được)"
                           onChange={(e) => setLinkAt(i, e.target.value)}
                           onKeyDown={(e) => {
                             if (e.key === "Enter") { e.preventDefault(); addLinkRow(i); }
                             if (e.key === "Backspace" && !l && links.length > 1) { e.preventDefault(); removeLinkRow(i); window.setTimeout(() => linkInputs.current[Math.max(0, i - 1)]?.focus(), 0); }
                           }} />
                    {(links.length > 1 || l) && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Bỏ link này" onClick={() => removeLinkRow(i)}>×</button>}
                  </div>
                ))}
              </div>
              <div className="ct__row">
                <button type="button" className="qt-btn qt-btn--small" disabled={links.length + files.length >= MAX_LINKS} onClick={() => addLinkRow(links.length - 1)}>＋ Thêm link</button>
                <input ref={fileInput} type="file" accept="video/*" multiple hidden onChange={(e) => { void addFiles(e.target.files); e.target.value = ""; }} />
                <button type="button" className="qt-btn qt-btn--small" onClick={() => fileInput.current?.click()}>📁 Chọn file video…</button>
              </div>
              {files.length > 0 && (
                <ul className="ct__files">
                  {files.map((f) => (
                    <li key={f.key}>
                      <span className="ct__fname">🎬 {f.name}</span>
                      <small className={f.error ? "ct__err" : ""}>{f.busy ? "đang tải lên…" : f.error ? f.error : "sẵn sàng"}</small>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setFiles((fs) => fs.filter((x) => x.key !== f.key))}>×</button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="qt-card">
              <div className="qt-card__eyebrow">2 · Phân tích</div>
              <p className="qt-card__hint">Tool tải video về; <b>tải xong là thẻ của video đó (bên phải) hiện bảng chọn đoạn ngay</b> — tự nhập
                đoạn rồi cắt luôn được. Lời trong video được nghe ngầm phía sau (chỉ cần cho “AI chọn đoạn” và phụ đề), không chặn bạn.</p>
              {looks.length > 0 && (
                <label className="qt-field">
                  <span>Mẫu chỉnh sửa cho các video cắt ra <small className="qt-card__hint">(khung 9:16, nền, logo / nhân vật, vùng mờ… đã lưu bằng nút ★ Mẫu trong trình chỉnh sửa)</small></span>
                  <select className="qt-input" value={lookId ?? ""} onChange={(e) => setLookId(e.target.value ? Number(e.target.value) : null)}>
                    <option value="">— Không dùng mẫu, để video thô —</option>
                    {looks.map((p) => <option key={p.id} value={p.id}>★ {p.name}{p.uses ? ` · dùng ${p.uses} lần` : ""}</option>)}
                  </select>
                  {lookId !== null && <small className="qt-card__hint">Cắt xong mỗi video được áp mẫu và xuất luôn — mở ✏️ Chỉnh nếu muốn sửa thêm.</small>}
                </label>
              )}
              <ChannelPicker value={channelId} onChange={setChannelId} label="Lưu clip vào kênh" />
              <button type="button" className="qt-btn qt-btn--accent qt-btn--big ct__go"
                      disabled={!count || starting || files.some((f) => f.busy)} onClick={() => void start()}>
                {starting ? "Đang gửi…" : count ? `🔍 Phân tích ${count} video` : "🔍 Phân tích video"}
              </button>
              <ol className="ct__steps">
                <li><b>Phân tích</b> — dán một hay nhiều link, tool tải về lần lượt.</li>
                <li><b>Chọn đoạn</b> — trên thẻ từng video: tự nhập phút / giây, hoặc bấm cho AI điền rồi sửa.</li>
                <li><b>Cắt</b> — mỗi đoạn thành một clip trong <b>Clip của tôi</b>: chỉnh, tải, đăng, lồng tiếng.</li>
              </ol>
            </section>
          </div>

          <div className="ct__right">
            <div className="ct__listhead">
              <h3>Video đã cắt</h3>
              <small>{sessions.length ? `${sessions.length} video gốc` : ""}</small>
              {allParts.length > 1 && (
                <div className="ct__pickall" role="group" aria-label="Chọn video ở mọi thẻ">
                  <label className="qt-check" title="Tick mọi video đã cắt của mọi link trên trang">
                    <input type="checkbox" checked={allPartsPicked} onChange={() => pickParts(allParts.map((p) => p.job_id), !allPartsPicked)} />
                    Chọn mọi video ({allParts.length})
                  </label>
                  {pickedAll.length > 0 && (
                    <>
                      <span className="ct__pickcount">đã chọn <strong>{pickedAll.length}</strong>{pickedFrom > 1 ? ` · từ ${pickedFrom} video gốc` : ""}</span>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => openEditorMany(pickedAll.map((p) => p.job_id))}
                              title="Mở trình chỉnh sửa với mọi video đã chọn (ở mọi thẻ): chỉnh một video rồi bấm “⇪ Áp cho cả loạt”">
                        ✏️ Chỉnh {pickedAll.length} video
                      </button>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setPicked(new Set())}>Bỏ chọn</button>
                    </>
                  )}
                </div>
              )}
            </div>
            {!sessions.length ? (
              <PageEmpty icon="✂️" title="Chưa cắt video nào" compact>
                Dán link video dài bên trái rồi bấm 🔍 Phân tích — video hiện ở đây để chọn đoạn cắt.
              </PageEmpty>
            ) : sessions.map((s) => (
              <SessionCard key={s.id} s={s} picked={picked} onPick={pickParts} focused={s.id === focusSession || (!focusSession && s.run_id === focusRun)}
                           cardRef={(el) => { cardRefs.current[s.id] = el; }} onChanged={refresh}
                           prompts={prompts} onPrompts={setPrompts} langs={status.title_langs ?? DEFAULT_LANGS} promptMax={status.prompt_max}
                           canHear={status.whisper}
                           waiting={sessions.filter((x) => x.id !== s.id && x.status === "review" && !x.rows.length && !x.parts.length)}
                           onEdit={(part, only) => openEditor(part, s, only)}
                           onDub={(boardIds) => navigate(`/tools/dub?clips=${boardIds.join(",")}`)} />
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function SessionCard({ s, picked, onPick, focused, cardRef, onChanged, onEdit, onDub, prompts, onPrompts, langs, promptMax, waiting, canHear }: {
  /** the videos ticked on the page (editing job ids) — shared by every card, so a pick can span several */
  picked: Set<string>;
  onPick: (jobIds: string[], on: boolean) => void;
  /** this machine can hear the words (Whisper) */
  canHear: boolean;
  /** the other analysed videos still waiting for their parts ("AI chọn đoạn cho cả N video") */
  waiting: CutSession[];
  prompts: CutPrompt[];
  onPrompts: (list: CutPrompt[]) => void;
  langs: string[];
  promptMax: number;
  s: CutSession;
  focused: boolean;
  cardRef: (el: HTMLElement | null) => void;
  onChanged: () => void;
  onEdit: (part: CutPartView, only?: string[]) => void;
  onDub: (boardIds: number[]) => void;
}) {
  const [editingRows, setEditingRows] = useState(false);
  const busy = isBusy(s);
  const showRows = s.status === "review" || editingRows;
  const parts = s.parts;
  const pickedParts = parts.filter((p) => picked.has(p.job_id));
  const toggle = (p: CutPartView) => onPick([p.job_id], !picked.has(p.job_id));
  const allPicked = parts.length > 0 && pickedParts.length === parts.length;
  const planning = s.status === "review" && !s.rows.length && !parts.length;
  const hearing = isHearing(s);
  const howLabel = planning ? "đã tải xong — chờ chọn đoạn" : !s.prepared && s.ask ? "" : s.how === "prompt" ? `theo yêu cầu “${s.prompt.slice(0, 60)}${s.prompt.length > 60 ? "…" : ""}”`
    : s.how === "manual" ? "tự cắt" : s.how === "even" ? "chia đều" : "AI tự chọn";

  async function act(fn: () => Promise<unknown>, ok?: string) {
    try { await fn(); if (ok) toast.success(ok); } catch (e) { toast.error(errMessage(e)); } finally { onChanged(); }
  }
  async function remove() {
    if (!await askConfirm(`Xoá “${sessionName(s)}” khỏi danh sách? ${parts.length ? `${parts.length} video đã cắt vẫn còn trong Clip của tôi.` : ""}`, { ok: "Xoá", danger: true })) return;
    await act(() => deleteCutSessions([s.id]));
  }

  return (
    <section ref={cardRef} className={`qt-card ct-s${focused ? " is-focus" : ""}`}>
      <div className="ct-s__head">
        <div className="ct-s__title">
          <strong title={s.url ?? s.title}>{sessionName(s)}</strong>
          <small>
            {[s.url ? hostOf(s.url) : "file tải lên", s.duration_s ? fmtClock(s.duration_s) : "", s.language ? `tiếng ${s.language}` : "",
              s.prepared ? (s.lines ? `${s.lines} câu` : s.heard ? "không có lời" : hearing ? "đang nghe lời" : "chưa nghe lời") : "", howLabel,
              s.how === "prompt" || s.how === "manual" ? "" : s.min_s === s.max_s ? `mỗi đoạn ${minLabel(Math.round(s.min_s / 6) / 10)}` : `${s.min_s}–${s.max_s} giây`].filter(Boolean).join(" · ")}
          </small>
        </div>
        <div className="ct-s__acts">
          {busy && <StopButton stopping={s.stopping} onStop={() => stopCut(s.id).then(onChanged, (e) => { toast.error(errMessage(e)); throw e; })} />}
          {s.status === "error" && <button type="button" className="qt-btn qt-btn--small" onClick={() => void act(() => cutAgain(s.id), "Đã đưa vào hàng cắt lại.")}>↻ Làm lại</button>}
          {s.status === "done" && !editingRows && <button type="button" className="qt-btn qt-btn--small" onClick={() => setEditingRows(true)}>✂️ Sửa chỗ cắt</button>}
          {!busy && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Xoá khỏi danh sách (clip vẫn còn)" onClick={() => void remove()}>🗑</button>}
        </div>
      </div>
      {busy && (
        <div className="ct-s__progress">
          <div className="qt-dub__bar"><span style={{ width: `${s.status === "queued" ? 0 : s.progress}%` }} /></div>
          <span>{s.stopping ? "Đang dừng…" : `${s.phase}${s.status !== "queued" ? ` · ${s.progress}%` : ""}`}</span>
        </div>
      )}
      {s.status === "error" && s.error && <p className="ct__err">⚠ {s.error}</p>}
      {s.prepared && !busy && hearing && (
        <div className="ct-hear" role="status">
          <span className="ct-hear__dot" aria-hidden="true" />
          <div className="ct-hear__body">
            <strong>🎧 Đang nghe lời trong video{s.hear === "run" ? ` · ${s.hear_progress ?? 0}%` : " · chờ video trước nghe xong"}</strong>
            <small>Không cần chờ: tự nhập đoạn rồi bấm ✂️ Cắt được ngay. Nghe xong thì “AI chọn đoạn” và phụ đề mới dùng được.</small>
            <div className="qt-dub__bar"><span style={{ width: `${s.hear === "run" ? s.hear_progress ?? 0 : 0}%` }} /></div>
          </div>
          <StopButton label="Bỏ nghe lời" className="qt-btn qt-btn--small qt-btn--ghost" title="Dừng nghe lời — video vẫn cắt tay được; không có AI chọn đoạn và phụ đề"
                      onStop={() => hearCut(s.id, false).then(onChanged, (e) => { toast.error(errMessage(e)); throw e; })} />
        </div>
      )}
      {s.prepared && !busy && !hearing && !s.heard && canHear && (
        <p className="ct-hear ct-hear--idle">
          <span>{s.hear === "error" ? `⚠ Nghe lời lỗi: ${s.hear_error || "không rõ"}` : "Video này chưa được nghe lời — cần cho “AI chọn đoạn” và phụ đề (cắt tay thì không cần)."}</span>
          <button type="button" className="qt-btn qt-btn--small" onClick={() => void act(() => hearCut(s.id, true), "Đang nghe lời ở phía sau — bạn cứ làm tiếp.")}>
            🎧 {s.hear === "error" ? "Nghe lại" : "Nghe lời"}
          </button>
        </p>
      )}
      {s.note && !busy && <p className="ct-s__note">💡 {s.note}</p>}
      {s.name && !busy && !showRows && (
        <p className="ct-s__name">
          <span>🏷 Tiêu đề video: <strong>{s.name}</strong></span>
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => copyText(s.name ?? "", "Đã copy tiêu đề video.")}>📋 Copy</button>
          {parts.length > 0 && (
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Name | start_1 | end_1 | title_bottom_1 | … — một dòng, dán sang công cụ dựng clip khác"
                    onClick={() => copyText(pipeText(s.name ?? "", parts), "Đã copy Name + mốc giờ + tiêu đề từng đoạn.")}>📋 Copy cả tiêu đề các đoạn</button>
          )}
        </p>
      )}
      {showRows && s.prepared && (
        <RowsEditor s={s} prompts={prompts} onPrompts={onPrompts} langs={langs} promptMax={promptMax} waiting={waiting} onChanged={onChanged} initial={s.status === "done" && s.parts.length ? s.parts.map((p) => ({ start: p.start, end: p.end, title: p.title, ...(p.subtitle ? { subtitle: p.subtitle } : {}) })) : s.rows}
                    onCancel={s.status === "done" ? () => setEditingRows(false) : undefined}
                    onDone={() => { setEditingRows(false); onChanged(); }} />
      )}
      {parts.length > 0 && !showRows && (
        <>
          <div className="ct-s__bar">
            <label className="qt-check"><input type="checkbox" checked={allPicked}
              onChange={() => onPick(parts.map((p) => p.job_id), !allPicked)} /> Chọn tất cả ({parts.length})</label>
            {pickedParts.length > 0 && (
              <>
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
                        onClick={() => onEdit(pickedParts[0], pickedParts.map((p) => p.job_id))}>✏️ Chỉnh {pickedParts.length} video</button>
                <button type="button" className="qt-btn qt-btn--small" disabled={!pickedParts.some((p) => p.board_id)}
                        onClick={() => onDub(pickedParts.filter((p) => p.board_id).map((p) => p.board_id!).slice(0, 10))}
                        title="Mở trang Lồng tiếng với các video này (tối đa 10 một lần)">🎙 Lồng tiếng {Math.min(10, pickedParts.length)}</button>
                <ZipSaveButton className="qt-btn qt-btn--small" ids={pickedParts.filter((p) => p.board_id).map((p) => p.board_id!)}
                               label={`⬇ Tải ${pickedParts.length} (.zip)`} />
              </>
            )}
            {!pickedParts.length && parts.length > 1 && (
              <button type="button" className="qt-btn qt-btn--small" onClick={() => onEdit(parts[0])}>✏️ Chỉnh cả loạt</button>
            )}
          </div>
          <div className="ct-parts">
            {parts.map((p) => (
              <PartCard key={p.index} p={p} picked={picked.has(p.job_id)} onPick={() => toggle(p)}
                        onEdit={() => onEdit(p)} onDub={() => p.board_id && onDub([p.board_id])} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function PartCard({ p, picked, onPick, onEdit, onDub }: {
  p: CutPartView; picked: boolean; onPick: () => void; onEdit: () => void; onDub: () => void;
}) {
  const navigate = useNavigate();
  const working = !!p.status && WORKING.includes(p.status);
  const missing = p.status === "missing";
  const dur = p.duration_s ?? p.end - p.start;
  const name = p.name || p.title;
  return (
    <div className={`ct-part${picked ? " is-picked" : ""}`}>
      <button type="button" className="ct-part__thumb" onClick={onEdit} disabled={missing} title="Mở trình chỉnh sửa">
        <img src={`/api/media/${p.media_id}/poster`} alt="" loading="lazy" onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }} />
        <span className="ct-part__dur">{fmtClock(dur)}</span>
        {working && <span className="ct-part__busy">⏳ {p.status === "queued" ? "chờ" : `${p.progress ?? 0}%`}</span>}
        {p.status === "error" && <span className="ct-part__busy is-err" title={p.error ?? ""}>⚠ lỗi</span>}
      </button>
      <label className="ct-part__pick" title="Chọn video này"><input type="checkbox" checked={picked} onChange={onPick} /></label>
      <div className="ct-part__body">
        <strong title={name}>{p.index}. {name}</strong>
        {p.subtitle && <em className="ct-part__sub" title={p.subtitle}>{p.subtitle}</em>}
        <small>
          {fmtClock(p.start)}–{fmtClock(p.end)} · {p.edited ? "✓ đã chỉnh" : "chưa chỉnh"}
          {p.sub_lang && p.sub_lang !== "none" ? ` · phụ đề ${subLangName(p.sub_lang)}` : ""}
        </small>
      </div>
      <div className="ct-part__acts">
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={missing} onClick={onEdit}>✏️ Chỉnh</button>
        <a className="qt-btn qt-btn--small" href={`/media/${p.media_id}`} download={`${name.replace(/[\\/:*?"<>|]+/g, " ").trim() || "video"}.mp4`} title="Tải video">⬇</a>
        <button type="button" className="qt-btn qt-btn--small" disabled={!p.board_id} onClick={onDub} title="Lồng tiếng video này">🎙</button>
        {p.board_id && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${p.board_id}/export`)} title="Mở clip (đăng, lên lịch, viết bài)">Clip →</button>}
      </div>
    </div>
  );
}

/**
 * The parts of one analysed video — typed by the seller (minutes + seconds, a name, an optional second line) or filled
 * in by the AI and then changed — with the source to watch each one. Shown as soon as the video is analysed (its length
 * is known, so nothing can be typed past its end), before cutting, and again for "✂️ Sửa chỗ cắt".
 */
function RowsEditor({ s, initial, onCancel, onDone, prompts, onPrompts, langs, promptMax, waiting, onChanged }: {
  s: CutSession; initial: DubCutRow[]; onCancel?: () => void; onDone: () => void;
  prompts: CutPrompt[]; onPrompts: (list: CutPrompt[]) => void; langs: string[]; promptMax: number;
  /** the other analysed videos with no parts yet */
  waiting: CutSession[]; onChanged: () => void;
}) {
  const prefs = useMemo(loadForm, []);
  // just analysed: nothing chosen yet → the options used last time
  const fresh = !initial.length && !s.prompt;
  const [rows, setRowsState] = useState<PlanRow[]>(() => (initial.length ? rowsFrom(initial) : [newRow(0)]));
  // rows the seller changed are never replaced by a poll; rows straight from the agent follow it
  const touched = useRef(false);
  const adopted = useRef(JSON.stringify(initial));
  const setRows = (next: PlanRow[]) => { touched.current = true; setRowsState(next); };
  const [fromAi, setFromAi] = useState(initial.length > 0 && s.by !== "manual");
  const [tried, setTried] = useState(false);
  const lastPrompt = prompts.find((p) => p.id === prefs.promptId) ?? (prompts.length === 1 ? prompts[0] : undefined);
  const [how, setHow] = useState<CutHow>(fresh ? (prefs.how === "prompt" ? "prompt" : "ai") : s.how === "manual" ? "ai" : s.how);
  const [prompt, setPrompt] = useState(fresh ? lastPrompt?.text ?? "" : s.prompt);
  const [promptId, setPromptId] = useState(() => (fresh ? lastPrompt?.id ?? "" : prompts.find((p) => p.text.trim() === s.prompt.trim())?.id ?? ""));
  const [titleLang, setTitleLang] = useState(fresh ? prefs.titleLang : s.title_lang ?? "");
  const [name, setName] = useState(s.name ?? "");
  const [lenKey, setLenKey] = useState(() => (fresh ? prefs.lenKey : s.min_s === s.max_s ? CUSTOM : LENGTHS.find((l) => l.min === s.min_s && l.max === s.max_s)?.key ?? "30-60"));
  // "Tuỳ chỉnh": minutes typed by the seller (kept as text while typing)
  const [customMin, setCustomMin] = useState(() => String(!fresh && s.min_s === s.max_s ? cleanMin(s.min_s / 60) : prefs.customMin));
  const custom = lenKey === CUSTOM;
  const [maxParts, setMaxParts] = useState(fresh ? prefs.maxParts : s.max_parts);
  const [busy, setBusy] = useState<"" | "suggest" | "cut">("");
  const [note, setNote] = useState(s.note);
  // "Tốc độ" and "Sáng / tối": previewed on the source right here, put on every part when cut (and exported so)
  const [rate, setRate] = useState(() => normSpeed(s.speed ?? 1));
  const [vol, setVol] = useState(() => normVolume(s.volume ?? 1));
  const [bright, setBright] = useState(() => normAdjust(s.adjust ?? null)?.brightness ?? 1);
  const hearing = isHearing(s);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => { if (video.current) video.current.playbackRate = rate; }, [rate]);
  useEffect(() => { setGain(video.current, vol); }, [vol]);  // above 100 % goes through Web Audio
  const stopAt = useRef<number | null>(null);
  const dur = s.duration_s;
  const len = custom ? { min: cleanMin(customMin) * 60, max: cleanMin(customMin) * 60 } : LENGTHS.find((l) => l.key === lenKey) ?? LENGTHS[1];
  const plan = planParts(rows, dur);
  const total = plan.parts.reduce((n, p) => n + (p.end - p.start), 0);

  // the prompts arrive after the page opens: the one used last time goes into an empty box
  useEffect(() => {
    if (fresh && !prompt && lastPrompt) { setPrompt(lastPrompt.text); setPromptId(lastPrompt.id); }
  }, [lastPrompt?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // the AI filled this video's parts from another card ("cho cả N video"): show them, unless the seller typed here
  useEffect(() => {
    const key = JSON.stringify(initial);
    if (key === adopted.current) return;
    adopted.current = key;
    if (!touched.current && initial.length) { setRowsState(rowsFrom(initial)); setFromAi(s.by !== "manual"); setNote(s.note); setName(s.name ?? ""); }
  }, [initial]); // eslint-disable-line react-hooks/exhaustive-deps

  function play(a: number, b: number) {
    const v = video.current;
    if (!v) return;
    v.currentTime = a;
    stopAt.current = b;
    void v.play().catch(() => undefined);
  }

  /** The AI (or an even split) fills the table — for this video, or for every analysed video still waiting too. */
  async function suggest(all: boolean) {
    if (how === "prompt" && !prompt.trim()) { toast.warning("Gõ yêu cầu cắt trước (hoặc chọn một prompt đã lưu)."); return; }
    if (touched.current && rows.some((r) => r.title.trim() || r.end !== null)
        && !await askConfirm("Các đoạn đang có trong bảng sẽ được thay bằng gợi ý mới. Tiếp tục?")) return;
    try { window.localStorage.setItem(FORM_KEY, JSON.stringify({ ...prefs, how, lenKey, maxParts, promptId, titleLang, customMin: cleanMin(customMin) })); } catch { /* private mode */ }
    const body = { how, prompt, min_s: len.min, max_s: len.max, max_parts: how === "prompt" || custom ? 0 : maxParts, title_lang: how === "even" ? "" : titleLang };
    setBusy("suggest");
    try {
      const r = await suggestCut(s.id, body);
      touched.current = false;
      adopted.current = JSON.stringify(r.rows);
      setRowsState(rowsFrom(r.rows));
      setFromAi(true);
      setTried(false);
      setNote(r.note);
      setName(r.name ?? "");
      let others = 0;
      if (all) {
        for (const o of waiting) {
          try { await suggestCut(o.id, body); others++; } catch (e) { toast.error(`${sessionName(o)}: ${errMessage(e)}`); }
        }
      }
      toast.success(`${r.by === "ai" ? "AI gợi ý" : "Chia được"} ${r.rows.length} đoạn${others ? ` (và đã gợi ý cho ${others} video khác)` : ""} — xem lại, sửa nếu cần rồi bấm Cắt.`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
      onChanged();
    }
  }
  async function cut() {
    setTried(true);
    if (plan.problems.length) {
      toast.warning(plan.problems.slice(0, 3).join(" · ") + (plan.problems.length > 3 ? ` · và ${plan.problems.length - 3} lỗi khác` : ""));
      return;
    }
    if (s.parts.length && !await askConfirm(`Cắt lại sẽ thay video của ${s.parts.length} phần đã cắt (phần đã chỉnh giữ kiểu chỉnh, cần xuất lại). Tiếp tục?`)) return;
    setBusy("cut");
    try {
      // the slider was moved (or moved back): every part gets it; untouched → nothing is sent
      const adjust = normAdjust({ brightness: bright, contrast: 1, saturation: 1 });
      const hadAdjust = !!normAdjust(s.adjust ?? null);
      await cutNow(s.id, plan.parts, fromAi ? undefined : "manual", adjust ?? (hadAdjust ? {} : undefined),
                   rate !== 1 || (s.speed ?? 1) !== 1 ? rate : undefined, vol !== 1 || (s.volume ?? 1) !== 1 ? vol : undefined);
      announceRunning();
      toast.success(`Đang cắt ${plan.parts.length} video…`);
      onDone();
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="ct-rows">
      <div className="ct-rows__top">
        {s.source_url && (
          <div className="ct-rows__watch">
            <video ref={video} className="ct-rows__video" src={s.source_url} controls playsInline preload="metadata"
                   style={Math.abs(bright - 1) >= 0.005 ? { filter: `brightness(${bright})` } : undefined}
                   onLoadedMetadata={(e) => { e.currentTarget.playbackRate = rate; setGain(e.currentTarget, vol); }}
                   onPlay={(e) => { e.currentTarget.playbackRate = rate; setGain(e.currentTarget, vol); }}
                   onTimeUpdate={(e) => { const t = e.currentTarget.currentTime; if (stopAt.current !== null && t >= stopAt.current) { e.currentTarget.pause(); stopAt.current = null; } }} />
            <label className="ct-rows__bright" title="Tốc độ video: xem ở đây nhanh / chậm thế nào thì mọi đoạn cắt ra được XUẤT đúng tốc độ đó (hình và tiếng cùng đổi). 1× = như gốc; sửa tiếp được trong ✏️ Chỉnh">
              <span>Tốc độ <small>{speedLabel(rate)}{rate !== 1 ? " · các đoạn cắt xuất ra theo tốc độ này" : " · như gốc"}</small></span>
              <TickRange min={SPEED_MIN} max={SPEED_MAX} step={0.1} value={rate} every={0.1} marks={SPEED_MARKS} disabled={!!busy} onChange={(v) => setRate(normSpeed(v))} ariaLabel="Tốc độ video" />
            </label>
            <label className="ct-rows__bright" title="Âm lượng: mọi đoạn cắt ra được XUẤT to / nhỏ đúng mức này (0 = tắt tiếng, 100% = như gốc, 300% = to gấp ba). Nghe thử ở đây cũng to / nhỏ theo; sửa tiếp được trong ✏️ Chỉnh">
              <span>Âm lượng <small>{volumeLabel(vol)}{vol !== 1 ? " · áp cho các đoạn cắt" : " · như gốc"}</small></span>
              <TickRange min={0} max={VOLUME_MAX} step={0.05} value={vol} every={0.1} marks={VOLUME_MARKS} disabled={!!busy} onChange={(v) => setVol(normVolume(v))} ariaLabel="Âm lượng" />
            </label>
            <label className="ct-rows__bright" title="Làm sáng / tối video: mọi đoạn cắt ra đều theo mức này (sửa tiếp được trong ✏️ Chỉnh → Khung nền)">
              <span>Sáng / tối <small>{Math.round(bright * 100)}%{Math.abs(bright - 1) >= 0.005 ? " · áp cho các đoạn cắt" : ""}</small></span>
              <TickRange min={0.4} max={1.8} step={0.01} value={bright} every={0.1} marks={[1]} disabled={!!busy} onChange={setBright} ariaLabel="Sáng tối" />
            </label>
          </div>
        )}
        <div className="ct-rows__again">
          <strong>{fromAi ? "✨ Gợi ý lại" : "✨ Để AI chọn đoạn (không bắt buộc)"}</strong>
          {!fromAi && <small className="qt-card__hint">Tự nhập các đoạn ở bảng bên dưới — hoặc để AI điền sẵn rồi bạn sửa.{hearing
            ? ` Tool đang nghe lời (${s.hear_progress ?? 0}%) — AI chọn theo nội dung được khi nghe xong; “Chia đều” thì dùng được ngay.`
            : !s.lines ? " Video này chưa có lời nghe được nên AI chỉ chia đều theo độ dài." : ""}</small>}
          <select className="qt-input" value={how} onChange={(e) => setHow(e.target.value as CutHow)} aria-label="AI chọn đoạn theo cách nào">
            {SUGGEST_HOWS.map((h) => <option key={h.key} value={h.key}>{h.icon} {h.label}</option>)}
          </select>
          {how === "prompt" && (
            <PromptBox compact prompts={prompts} onPrompts={onPrompts} pickedId={promptId} onPick={setPromptId} text={prompt} onText={setPrompt}
                       lang={titleLang} onLang={setTitleLang} langs={langs} maxLength={promptMax} />
          )}
          <div className="ct-rows__opts" hidden={how === "prompt"}>
            <select className="qt-input" value={lenKey} onChange={(e) => setLenKey(e.target.value)} aria-label="Mỗi đoạn dài">
              {LENGTHS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
              <option value={CUSTOM}>Tuỳ chỉnh — tự nhập số phút…</option>
            </select>
            {custom && (
              <label className="ct-rows__custom" title="Mỗi đoạn dài đúng số phút này; đoạn cuối lấy hết phần còn lại của video">
                <input className="qt-input" type="number" min={0.5} max={20} step={0.5} inputMode="decimal" value={customMin} aria-label="Số phút mỗi đoạn"
                       onChange={(e) => setCustomMin(e.target.value)} onBlur={() => setCustomMin(String(cleanMin(customMin)))} />
                <span>phút / đoạn{dur ? ` → ${Math.max(1, Math.ceil((dur - 3) / (cleanMin(customMin) * 60)))} đoạn, đoạn cuối lấy phần còn lại` : ""}</span>
              </label>
            )}
            <select className="qt-input" value={maxParts} hidden={custom} onChange={(e) => setMaxParts(Number(e.target.value))} aria-label="Số đoạn tối đa">
              {MAX_PARTS_CHOICES.map((n) => <option key={n} value={n}>{n ? `tối đa ${n}` : "số video: tự động"}</option>)}
            </select>
          </div>
          <div className="ct-rows__aibtns">
            <button type="button" className="qt-btn qt-btn--small" disabled={!!busy || (hearing && how !== "even")} onClick={() => void suggest(false)}
                    title={hearing && how !== "even" ? "Chờ tool nghe xong lời trong video" : undefined}>
              {busy === "suggest" ? "AI đang chọn…" : hearing && how !== "even" ? `⏳ Chờ nghe lời ${s.hear_progress ?? 0}%` : how === "even" ? "⇔ Chia đều" : fromAi ? "✨ Gợi ý lại" : "✨ AI chọn đoạn"}
            </button>
            {waiting.length > 0 && (
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!!busy || (hearing && how !== "even")} onClick={() => void suggest(true)}
                      title="Dùng đúng cách này cho các video đã phân tích xong mà chưa có đoạn nào — rồi xem lại từng video và bấm Cắt">
                ✨ …cho cả {waiting.length} video đang chờ
              </button>
            )}
          </div>
          {note && <p className="ct-s__note">💡 {note}</p>}
          {name && (
            <p className="ct-s__name">
              <span>🏷 Tiêu đề video: <strong>{name}</strong></span>
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!plan.parts.length}
                      onClick={() => copyText(pipeText(name, plan.parts), "Đã copy Name + mốc giờ + tiêu đề từng đoạn.")}>📋 Copy cả dòng</button>
            </p>
          )}
        </div>
      </div>
      <PartsTable rows={rows} onRows={setRows} duration={dur} disabled={!!busy} showAll={tried}
                  now={s.source_url ? () => video.current?.currentTime ?? null : undefined} onPlay={s.source_url ? play : undefined} />
      <div className="ct-rows__foot">
        <span className="ct-rows__sum">
          {plan.parts.length ? `${plan.parts.length} đoạn hợp lệ · tổng ${clockText(total)}${dur ? ` / video ${clockText(dur)}` : ""}` : dur ? `Video dài ${clockText(dur)}` : ""}
        </span>
        <span className="ct-rows__sp" />
        {onCancel && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!!busy} onClick={onCancel}>Huỷ</button>}
        <button type="button" className="qt-btn qt-btn--accent" disabled={!!busy} onClick={() => void cut()}>
          {busy === "cut" ? "Đang gửi…" : `✂️ Cắt ${Math.max(1, plan.parts.length)} đoạn`}
        </button>
      </div>
    </div>
  );
}

