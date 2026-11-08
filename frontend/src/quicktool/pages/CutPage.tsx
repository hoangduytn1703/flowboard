import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import { askConfirm } from "../../components/Dialogs";
import { exportsZipUrl } from "../../api/client";
import {
  dubSubtitleLines, getDubJob, getDubStatus, linksIn, renderDub, subLangName, uploadDubVideo,
  type DubCutRow, type DubJob, type DubRender, type DubStatus,
} from "../../api/dub";
import {
  cutAgain, cutNow, deleteCutSessions, getCutStatus, isBusy, LENGTHS, listCutParts, listCutSessions,
  PROMPT_IDEAS, startCut, stopCut, suggestCut,
  type CutHow, type CutPartView, type CutSession, type CutToolStatus,
} from "../../api/cut";
import { ChannelPicker } from "../channels/ChannelPicker";
import { DubEditor, type BatchLook } from "../dub/editor/DubEditor";
import { fmtClock, TimeBox } from "../dub/editor/CutPane";
import { PageEmpty, PageLoading } from "../PageState";
import { toast } from "../../store/toast";
import "../dub.css";
import "../posts.css";
import "../cut.css";

const MAX_LINKS = 10;
const FORM_KEY = "flowboard.cut.form";
const WORKING = ["queued", "running", "rendering"];
const isWorking = (j: DubJob) => WORKING.includes(j.status);
const MAX_PARTS_CHOICES = [0, 3, 5, 8, 10, 15, 20, 30];
const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

interface FormPrefs { how: CutHow; lenKey: string; maxParts: number; review: boolean }
function loadForm(): FormPrefs {
  const def: FormPrefs = { how: "ai", lenKey: "30-60", maxParts: 0, review: false };
  try {
    const raw = JSON.parse(window.localStorage.getItem(FORM_KEY) || "{}") as Partial<FormPrefs>;
    return {
      how: raw.how === "prompt" || raw.how === "even" ? raw.how : "ai",
      lenKey: LENGTHS.some((l) => l.key === raw.lenKey) ? raw.lenKey! : def.lenKey,
      maxParts: MAX_PARTS_CHOICES.includes(Number(raw.maxParts)) ? Number(raw.maxParts) : 0,
      review: !!raw.review,
    };
  } catch {
    return def;
  }
}

interface UpFile { key: string; name: string; media_id?: string; busy: boolean; error?: string }

const HOWS: { key: CutHow; icon: string; label: string; hint: string }[] = [
  { key: "ai", icon: "✨", label: "AI tự chọn đoạn hay", hint: "AI nghe lời trong video, giữ những đoạn đáng thành video ngắn (có móc mở đầu, trọn ý), bỏ chào hỏi, quảng cáo, lan man." },
  { key: "prompt", icon: "✍️", label: "Theo yêu cầu của bạn", hint: "Gõ muốn giữ đoạn nào — AI làm đúng như vậy." },
  { key: "even", icon: "⇔", label: "Chia đều", hint: "Chia hết cả video theo độ dài chọn bên dưới, cắt ở chỗ ngừng giữa hai câu." },
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
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<CutToolStatus | null>(null);
  const [dubStatus, setDubStatus] = useState<DubStatus | null>(null);
  const [sessions, setSessions] = useState<CutSession[] | null>(null);
  const prefs = useMemo(loadForm, []);
  const [links, setLinks] = useState<string[]>([""]);
  const [files, setFiles] = useState<UpFile[]>([]);
  const [how, setHow] = useState<CutHow>(prefs.how);
  const [prompt, setPrompt] = useState("");
  const [lenKey, setLenKey] = useState(prefs.lenKey);
  const [maxParts, setMaxParts] = useState(prefs.maxParts);
  const [review, setReview] = useState(prefs.review);
  const [channelId, setChannelId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<DubJob | null>(null);
  const [siblings, setSiblings] = useState<DubJob[]>([]);
  const jobRef = useRef<DubJob | null>(null);
  jobRef.current = job;
  const fileInput = useRef<HTMLInputElement>(null);
  const linkInputs = useRef<(HTMLInputElement | null)[]>([]);
  const cardRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    void getCutStatus().then(setStatus).catch(() => setStatus({ whisper: false, whisper_reason: "", remotion: false, max_minutes: 60,
      max_links: MAX_LINKS, max_parts: 30, prompt_max: 600, default_min: 30, default_max: 60 }));
    void getDubStatus().then(setDubStatus).catch(() => undefined);
  }, []);
  useEffect(() => {
    try { window.localStorage.setItem(FORM_KEY, JSON.stringify({ how, lenKey, maxParts, review })); } catch { /* private mode */ }
  }, [how, lenKey, maxParts, review]);

  function refresh() {
    void listCutSessions().then(setSessions).catch((e) => { toast.error(errMessage(e)); setSessions((s) => s ?? []); });
  }
  const anyBusy = (sessions ?? []).some(isBusy) || (sessions ?? []).some((s) => s.parts.some((p) => p.status && WORKING.includes(p.status)));
  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, anyBusy ? 3000 : 15000);
    return () => window.clearInterval(t);
  }, [anyBusy]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── the editor: /tools/cut?job=<part>&run=<run>[&parts=<job ids>] ───────
  const wantJob = params.get("job");
  const wantRun = params.get("run");
  const wantParts = params.get("parts");
  useEffect(() => {
    if (!wantJob) { setJob(null); setSiblings([]); return; }
    if (job?.job_id === wantJob) return;
    let gone = false;
    void (async () => {
      try {
        const j = await getDubJob(wantJob);
        const run = wantRun || j.cut?.run_id || j.batch_id || "";
        let sibs = run ? await listCutParts({ run }) : [j];
        if (wantParts) {
          const only = wantParts.split(",");
          sibs = sibs.filter((x) => only.includes(x.job_id));
        }
        if (gone) return;
        setSiblings(sibs.length ? sibs : [j]);
        setJob(j);
        window.scrollTo({ top: 0 });
      } catch (e) {
        if (!gone) { toast.error(errMessage(e)); setParams({}, { replace: true }); }
      }
    })();
    return () => { gone = true; };
  }, [wantJob, wantRun, wantParts]); // eslint-disable-line react-hooks/exhaustive-deps

  // the part being exported: poll it; the editor reloads the agent's copy when it is done
  useEffect(() => {
    if (!job || !isWorking(job)) return;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await getDubJob(job.job_id);
        if (stopped) return;
        setJob(j);
        setSiblings((ss) => ss.map((x) => (x.job_id === j.job_id ? j : x)));
        if (j.status === "done") { toast.success("Đã xuất xong — clip trong “Clip của tôi” dùng bản mới."); refresh(); }
        if (j.status === "error") toast.error(j.error ?? "Xuất video lỗi.");
      } catch { /* the next tick tries again */ }
    };
    const timer = window.setInterval(tick, 2000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [job?.job_id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function openEditor(part: { job_id: string }, s: CutSession, only?: string[]) {
    const q: Record<string, string> = { job: part.job_id, run: s.run_id };
    if (only && only.length > 1) q.parts = only.join(",");
    setParams(q);
  }
  function closeEditor() {
    setParams({});
    refresh();
  }
  function switchJob(id: string) {
    const q: Record<string, string> = { job: id };
    if (wantRun) q.run = wantRun;
    if (wantParts) q.parts = wantParts;
    const j = siblings.find((x) => x.job_id === id);
    if (j) setJob(j);
    setParams(q, { replace: true });
  }
  /** "⇪ Áp cho cả loạt": this part's look (+ its subtitle language) → every other part open in the editor. */
  async function applyToOthers(look: BatchLook): Promise<number> {
    const cur = jobRef.current;
    if (!cur) return 0;
    const targets = siblings.filter((j) => j.job_id !== cur.job_id && !isWorking(j));
    const skipped = siblings.length - 1 - targets.length;
    let sent = 0;
    for (const t of targets) {
      try {
        const body: DubRender = { layout: look.layout, style: look.style, engine: look.engine, highlights: look.highlights };
        if (look.lang && look.lang !== (t.sub_lang ?? "none")) {
          body.sub_lang = look.lang;
          if (look.lang !== "none" && t.segments.length) body.lines = (await dubSubtitleLines(t.job_id, look.lang)).lines;
        }
        await renderDub(t.job_id, body);
        sent++;
      } catch (e) {
        toast.error(`${t.name || t.job_id}: ${errMessage(e)}`);
      }
    }
    if (skipped) toast.warning(`${skipped} video đang xuất — bỏ qua, áp lại sau.`);
    announceRunning();
    const run = wantRun || cur.cut?.run_id;
    if (run) void listCutParts({ run }).then((all) => setSiblings((ss) => all.filter((x) => ss.some((y) => y.job_id === x.job_id)))).catch(() => undefined);
    return sent;
  }

  // ── the form ─────────────────────────────────────────────────────────────
  const cleanLinks = links.map((l) => l.trim()).filter(Boolean);
  const readyFiles = files.filter((f) => f.media_id);
  const count = cleanLinks.length + readyFiles.length;
  const len = LENGTHS.find((l) => l.key === lenKey) ?? LENGTHS[1];

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

  async function start() {
    if (!count || starting) return;
    if (how === "prompt" && !prompt.trim()) { toast.warning("Gõ yêu cầu cắt, hoặc chọn “AI tự chọn đoạn hay”."); return; }
    setStarting(true);
    try {
      const r = await startCut({ links: cleanLinks, media: readyFiles.map((f) => ({ media_id: f.media_id!, name: f.name })), how, prompt,
                                 min_s: len.min, max_s: len.max, max_parts: maxParts, review, channel_id: channelId });
      toast.success(`Đã đưa ${r.sessions.length} video vào hàng cắt — tải về, nghe lời, chọn đoạn rồi cắt.`);
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

  if (wantJob) {
    return (
      <>
        <header className="qt-header">
          <span className="qt-header__crumb">✂️ Cắt video{job ? ` › ${job.name || "chỉnh sửa"}` : ""}</span>
        </header>
        <div className="qt-home qt-dub">
          {job && dubStatus ? (
            <DubEditor key={job.job_id} job={job} status={dubStatus} onClose={closeEditor}
                       onJob={(j) => { setJob(j); setSiblings((ss) => ss.map((x) => (x.job_id === j.job_id ? j : x))); }}
                       siblings={siblings} onSwitch={siblings.length > 1 ? switchJob : undefined}
                       onApplyAll={siblings.length > 1 ? applyToOthers : undefined} />
          ) : <PageLoading text="Đang mở video…" />}
        </div>
      </>
    );
  }

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
              <div className="qt-card__eyebrow">2 · Cắt thế nào</div>
              <div className="ct__hows" role="radiogroup" aria-label="Cách cắt">
                {HOWS.map((h) => (
                  <label key={h.key} className={`ct__how${how === h.key ? " is-on" : ""}`}>
                    <input type="radio" name="ct-how" checked={how === h.key} onChange={() => setHow(h.key)} />
                    <span className="ct__howicon" aria-hidden="true">{h.icon}</span>
                    <span><strong>{h.label}</strong><small>{h.hint}</small></span>
                  </label>
                ))}
              </div>
              {how === "prompt" && (
                <div className="qt-field">
                  <span>Yêu cầu cắt</span>
                  <textarea className="qt-textarea" rows={3} maxLength={status.prompt_max} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                            placeholder="VD: Mỗi đoạn là một mẹo, bỏ phần giới thiệu và kêu gọi đăng ký kênh" />
                  <div className="ct__chips">
                    {PROMPT_IDEAS.map((p) => <button key={p} type="button" className="qt-chip" onClick={() => setPrompt(p)}>{p}</button>)}
                  </div>
                </div>
              )}
              {how !== "even" && !status.whisper && (
                <p className="ct__warn">⚠ Máy này chưa nghe được lời trong video ({status.whisper_reason || "thiếu Whisper của pyvideotrans"}) — AI không chọn theo
                  nội dung được, tool sẽ chia đều theo độ dài.</p>
              )}
              <div className="qt-field">
                <span>Mỗi video ngắn dài</span>
                <div className="ct__chips">
                  {LENGTHS.map((l) => (
                    <button key={l.key} type="button" className={`qt-chip${lenKey === l.key ? " qt-chip--on" : ""}`} onClick={() => setLenKey(l.key)}>{l.label}</button>
                  ))}
                </div>
              </div>
              <label className="qt-field">
                <span>Số video tối đa mỗi link</span>
                <select className="qt-input" value={maxParts} onChange={(e) => setMaxParts(Number(e.target.value))}>
                  {MAX_PARTS_CHOICES.map((n) => <option key={n} value={n}>{n ? `${n} video` : "Tự động (theo nội dung)"}</option>)}
                </select>
              </label>
              <label className="qt-check">
                <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} /> Cho mình xem lại các đoạn trước khi cắt
              </label>
              <ChannelPicker value={channelId} onChange={setChannelId} label="Lưu clip vào kênh (không bắt buộc)" />
              <button type="button" className="qt-btn qt-btn--accent qt-btn--big ct__go" disabled={!count || starting || files.some((f) => f.busy)} onClick={() => void start()}>
                {starting ? "Đang gửi…" : count ? `✂️ Cắt ${count} video` : "✂️ Cắt video"}
              </button>
              <p className="ct__tip">Mỗi video ngắn thành một clip trong <b>Clip của tôi</b> — chỉnh phụ đề, khung 9:16, nền, vùng mờ cho từng video
                hoặc cả loạt; tải về; đăng; muốn lồng tiếng thì chọn video rồi bấm 🎙.</p>
            </section>
          </div>

          <div className="ct__right">
            <div className="ct__listhead">
              <h3>Video đã cắt</h3>
              <small>{sessions.length ? `${sessions.length} video gốc` : ""}</small>
            </div>
            {!sessions.length ? (
              <PageEmpty icon="✂️" title="Chưa cắt video nào" compact>
                Dán link video dài bên trái rồi bấm ✂️ Cắt — các video ngắn hiện ở đây và trong Clip của tôi.
              </PageEmpty>
            ) : sessions.map((s) => (
              <SessionCard key={s.id} s={s} focused={s.id === focusSession || (!focusSession && s.run_id === focusRun)}
                           cardRef={(el) => { cardRefs.current[s.id] = el; }} onChanged={refresh}
                           onEdit={(part, only) => openEditor(part, s, only)}
                           onDub={(boardIds) => navigate(`/tools/dub?clips=${boardIds.join(",")}`)} />
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function SessionCard({ s, focused, cardRef, onChanged, onEdit, onDub }: {
  s: CutSession;
  focused: boolean;
  cardRef: (el: HTMLElement | null) => void;
  onChanged: () => void;
  onEdit: (part: CutPartView, only?: string[]) => void;
  onDub: (boardIds: number[]) => void;
}) {
  const [editingRows, setEditingRows] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const busy = isBusy(s);
  const showRows = s.status === "review" || editingRows;
  const parts = s.parts;
  const pickedParts = parts.filter((p) => picked.has(p.index));
  const toggle = (i: number) => setPicked((cur) => { const n = new Set(cur); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  const allPicked = parts.length > 0 && pickedParts.length === parts.length;
  const howLabel = s.how === "prompt" ? `theo yêu cầu “${s.prompt.slice(0, 60)}${s.prompt.length > 60 ? "…" : ""}”` : s.how === "even" ? "chia đều" : "AI tự chọn";

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
              s.prepared ? (s.lines ? `${s.lines} câu` : s.heard ? "không có lời" : "chưa nghe lời") : "", howLabel,
              `${s.min_s}–${s.max_s} giây`].filter(Boolean).join(" · ")}
          </small>
        </div>
        <div className="ct-s__acts">
          {busy && <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => void act(() => stopCut(s.id))}>Dừng</button>}
          {s.status === "error" && <button type="button" className="qt-btn qt-btn--small" onClick={() => void act(() => cutAgain(s.id), "Đã đưa vào hàng cắt lại.")}>↻ Làm lại</button>}
          {s.status === "done" && !editingRows && <button type="button" className="qt-btn qt-btn--small" onClick={() => setEditingRows(true)}>✂️ Sửa chỗ cắt</button>}
          {!busy && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Xoá khỏi danh sách (clip vẫn còn)" onClick={() => void remove()}>🗑</button>}
        </div>
      </div>
      {busy && (
        <div className="ct-s__progress">
          <div className="qt-dub__bar"><span style={{ width: `${s.status === "queued" ? 0 : s.progress}%` }} /></div>
          <span>{s.phase}{s.status !== "queued" ? ` · ${s.progress}%` : ""}</span>
        </div>
      )}
      {s.status === "error" && s.error && <p className="ct__err">⚠ {s.error}</p>}
      {s.note && !busy && <p className="ct-s__note">💡 {s.note}</p>}
      {showRows && s.prepared && (
        <RowsEditor s={s} initial={s.status === "done" && s.parts.length ? s.parts.map((p) => ({ start: p.start, end: p.end, title: p.title })) : s.rows}
                    onCancel={s.status === "done" ? () => setEditingRows(false) : undefined}
                    onDone={() => { setEditingRows(false); onChanged(); }} />
      )}
      {parts.length > 0 && !showRows && (
        <>
          <div className="ct-s__bar">
            <label className="qt-check"><input type="checkbox" checked={allPicked}
              onChange={() => setPicked(allPicked ? new Set() : new Set(parts.map((p) => p.index)))} /> Chọn tất cả ({parts.length})</label>
            {pickedParts.length > 0 && (
              <>
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
                        onClick={() => onEdit(pickedParts[0], pickedParts.map((p) => p.job_id))}>✏️ Chỉnh {pickedParts.length} video</button>
                <button type="button" className="qt-btn qt-btn--small" disabled={!pickedParts.some((p) => p.board_id)}
                        onClick={() => onDub(pickedParts.filter((p) => p.board_id).map((p) => p.board_id!).slice(0, 5))}
                        title="Mở trang Lồng tiếng với các video này (tối đa 5 một lần)">🎙 Lồng tiếng {Math.min(5, pickedParts.length)}</button>
                <a className="qt-btn qt-btn--small" href={exportsZipUrl(pickedParts.filter((p) => p.board_id).map((p) => p.board_id!))}>⬇ Tải {pickedParts.length} (.zip)</a>
              </>
            )}
            {!pickedParts.length && parts.length > 1 && (
              <button type="button" className="qt-btn qt-btn--small" onClick={() => onEdit(parts[0])}>✏️ Chỉnh cả loạt</button>
            )}
          </div>
          <div className="ct-parts">
            {parts.map((p) => (
              <PartCard key={p.index} p={p} picked={picked.has(p.index)} onPick={() => toggle(p.index)}
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

/** Check / change the parts before cutting (or cut again): title, start, end — with the source to watch each one. */
function RowsEditor({ s, initial, onCancel, onDone }: {
  s: CutSession; initial: DubCutRow[]; onCancel?: () => void; onDone: () => void;
}) {
  const [rows, setRows] = useState<DubCutRow[]>(initial);
  const [how, setHow] = useState<CutHow>(s.how);
  const [prompt, setPrompt] = useState(s.prompt);
  const [lenKey, setLenKey] = useState(() => LENGTHS.find((l) => l.min === s.min_s && l.max === s.max_s)?.key ?? "30-60");
  const [maxParts, setMaxParts] = useState(s.max_parts);
  const [busy, setBusy] = useState<"" | "suggest" | "cut">("");
  const [note, setNote] = useState(s.note);
  const video = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const dur = s.duration_s;
  const len = LENGTHS.find((l) => l.key === lenKey) ?? LENGTHS[1];

  function play(a: number, b: number) {
    const v = video.current;
    if (!v) return;
    v.currentTime = a;
    stopAt.current = b;
    void v.play().catch(() => undefined);
  }
  const setRow = (i: number, patch: Partial<DubCutRow>) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  function addRow() {
    setRows((rs) => {
      const last = rs[rs.length - 1];
      const start = Math.min(dur, last ? last.end : 0);
      return [...rs, { start, end: Math.min(dur, start + (len.min + len.max) / 2), title: "" }];
    });
  }
  const problem = (r: DubCutRow) => (dur > 0 && r.start >= dur - 0.05 ? "bắt đầu quá cuối video" : r.end - r.start < 3 ? "ngắn hơn 3 giây" : "");
  const bad = rows.some((r) => problem(r));

  async function suggest() {
    if (how === "prompt" && !prompt.trim()) { toast.warning("Gõ yêu cầu cắt trước."); return; }
    setBusy("suggest");
    try {
      const r = await suggestCut(s.id, { how, prompt, min_s: len.min, max_s: len.max, max_parts: maxParts });
      setRows(r.rows);
      setNote(r.note);
      toast.success(`${r.by === "ai" ? "AI gợi ý" : "Chia được"} ${r.rows.length} đoạn — xem lại rồi bấm Cắt.`);
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }
  async function cut() {
    if (s.parts.length && !await askConfirm(`Cắt lại sẽ thay video của ${s.parts.length} phần đã cắt (phần đã chỉnh giữ kiểu chỉnh, cần xuất lại). Tiếp tục?`)) return;
    setBusy("cut");
    try {
      await cutNow(s.id, rows);
      announceRunning();
      toast.success(`Đang cắt ${rows.length} video…`);
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
          <video ref={video} className="ct-rows__video" src={s.source_url} controls playsInline preload="metadata"
                 onTimeUpdate={(e) => { const t = e.currentTarget.currentTime; if (stopAt.current !== null && t >= stopAt.current) { e.currentTarget.pause(); stopAt.current = null; } }} />
        )}
        <div className="ct-rows__again">
          <strong>✨ Gợi ý lại</strong>
          <select className="qt-input" value={how} onChange={(e) => setHow(e.target.value as CutHow)}>
            {HOWS.map((h) => <option key={h.key} value={h.key}>{h.icon} {h.label}</option>)}
          </select>
          {how === "prompt" && <input className="qt-input" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Yêu cầu cắt…" />}
          <div className="ct-rows__opts">
            <select className="qt-input" value={lenKey} onChange={(e) => setLenKey(e.target.value)}>
              {LENGTHS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
            </select>
            <select className="qt-input" value={maxParts} onChange={(e) => setMaxParts(Number(e.target.value))}>
              {MAX_PARTS_CHOICES.map((n) => <option key={n} value={n}>{n ? `tối đa ${n}` : "số video: tự động"}</option>)}
            </select>
          </div>
          <button type="button" className="qt-btn qt-btn--small" disabled={!!busy} onClick={() => void suggest()}>
            {busy === "suggest" ? "Đang gợi ý…" : "✨ Gợi ý lại"}
          </button>
          {note && <p className="ct-s__note">💡 {note}</p>}
        </div>
      </div>
      <div className="ct-rows__table">
        <div className="ct-rows__row ct-rows__row--head"><span>#</span><span>Tên video</span><span>Từ</span><span>Đến</span><span>Dài</span><span /></div>
        {rows.map((r, i) => (
          <div key={i} className={`ct-rows__row${problem(r) ? " is-bad" : ""}`} title={problem(r)}>
            <span>{i + 1}</span>
            <input className="qt-input" value={r.title} placeholder={`${(s.title || "Video").slice(0, 40)} — Phần ${i + 1}`} onChange={(e) => setRow(i, { title: e.target.value })} />
            <TimeBox value={r.start} label="Bắt đầu" disabled={!!busy} onChange={(v) => setRow(i, { start: Math.max(0, v) })} />
            <TimeBox value={r.end} label="Kết thúc" disabled={!!busy} onChange={(v) => setRow(i, { end: dur ? Math.min(dur, v) : v })} />
            <small>{fmtClock(Math.max(0, r.end - r.start))}</small>
            <span className="ct-rows__btns">
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!s.source_url} title="Xem đoạn này" onClick={() => play(r.start, r.end)}>▶</button>
              <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Bỏ đoạn này" onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}>🗑</button>
            </span>
          </div>
        ))}
      </div>
      <div className="ct-rows__foot">
        <button type="button" className="qt-btn qt-btn--small" disabled={rows.length >= 30 || !!busy} onClick={addRow}>＋ Thêm đoạn</button>
        <span className="ct-rows__sp" />
        {onCancel && <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={!!busy} onClick={onCancel}>Huỷ</button>}
        <button type="button" className="qt-btn qt-btn--accent" disabled={!rows.length || bad || !!busy} onClick={() => void cut()}>
          {busy === "cut" ? "Đang gửi…" : `✂️ Cắt ${rows.length} đoạn`}
        </button>
      </div>
    </div>
  );
}

