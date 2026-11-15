import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import { askConfirm } from "../../components/Dialogs";
import { ZipSaveButton } from "../../components/ZipSaveButton";
import {
  dubSubtitleLines, getDubStatus, listDubJobsByIds, renderDub, uploadDubVideo,
  type DubJob, type DubRender, type DubStatus,
} from "../../api/dub";
import {
  addEditJobs, editPath, importEditClips, importEditFiles, listEditItems, MAX_EDIT_TOGETHER, removeEditJobs, type EditItem,
} from "../../api/edit";
import { toast } from "../../store/toast";
import { DubEditor, type BatchLook } from "../dub/editor/DubEditor";
import { ClipPickDialog } from "../dub/ClipPickDialog";
import { PageEmpty, PageLoading } from "../PageState";
import "../dub.css";
import "../edit.css";

/**
 * "🎞 Chỉnh sửa video" (/tools/edit) — the one place videos are edited, many at a time.
 * Bring videos in (files from this machine, clips of "Clip của tôi", or the "✏️ Chỉnh" buttons of the other
 * tools), tick them, and the CapCut-style editor opens with all of them side by side: edit one,
 * "⇪ Áp cho cả loạt" gives the others the same look, "Xuất cả N" renders them.
 *   /tools/edit                       the list
 *   /tools/edit?jobs=a,b,c&job=b      the editor on those videos
 */
const WORKING = ["queued", "running", "rendering"];
const isWorking = (j: { status: string }) => WORKING.includes(j.status);
const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const clock = (s: number | null) => {
  if (!s) return "";
  const t = Math.round(s);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};
const isVideo = (f: File) => f.type.startsWith("video/") || /\.(mp4|mov|webm|mkv|m4v)$/i.test(f.name);

interface Upload { key: string; name: string; state: "wait" | "up" | "done" | "error"; error?: string }

export function EditPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  // the page that sent the videos here ("✏️ Chỉnh N video" on Cào video kênh, Clip của tôi…): "← Danh sách" goes back to it
  const backTo = (location.state as { back?: string } | null)?.back;
  const [status, setStatus] = useState<DubStatus | null>(null);
  const [items, setItems] = useState<EditItem[] | null>(null);
  const [maxImport, setMaxImport] = useState(30);
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [clipsOpen, setClipsOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = "Chỉnh sửa video · DFlow";
    void getDubStatus().then(setStatus).catch((e) => toast.error(errMessage(e)));
  }, []);

  // ── the list ───────────────────────────────────────────────────────────
  const refresh = () => listEditItems().then((r) => { setItems(r.items); setMaxImport(r.max_import); })
    .catch((e) => { toast.error(errMessage(e)); setItems((x) => x ?? []); });
  const listBusy = (items ?? []).some((i) => isWorking(i) || i.hear.state === "wait" || i.hear.state === "run");
  const wantJobs = params.get("jobs");
  const wantJob = params.get("job");
  const editing = !!(wantJobs || wantJob);
  useEffect(() => {
    if (editing) return;
    void refresh();
    const t = window.setInterval(() => void refresh(), listBusy ? 2500 : 15000);
    return () => window.clearInterval(t);
  }, [editing, listBusy]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = items ?? [];
  const pickedItems = list.filter((i) => picked.has(i.job_id));
  const allPicked = list.length > 0 && pickedItems.length === list.length;
  const toggle = (id: string) => setPicked((cur) => { const n = new Set(cur); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  // ── bringing videos in ─────────────────────────────────────────────────
  const uploading = uploads.some((u) => u.state === "wait" || u.state === "up");
  async function addFiles(files: File[]) {
    const videos = files.filter(isVideo);
    if (!videos.length) { toast.warning("Không thấy file video nào (mp4, mov, webm, mkv)."); return; }
    if (uploading) { toast.info("Đang đưa các video trước vào — đợi xong rồi thêm tiếp."); return; }
    if (videos.length > maxImport) toast.warning(`Một lượt nhận tối đa ${maxImport} video — lấy ${maxImport} file đầu.`);
    const batch = videos.slice(0, maxImport).map((f, k) => ({ file: f, up: { key: `${Date.now()}-${k}`, name: f.name, state: "wait" } as Upload }));
    setUploads(batch.map((b) => b.up));
    const ready: { media_id: string; name: string }[] = [];
    for (const { file, up } of batch) {
      setUploads((us) => us.map((u) => (u.key === up.key ? { ...u, state: "up" } : u)));
      try {
        const r = await uploadDubVideo(file);
        ready.push({ media_id: r.media_id, name: file.name });
        setUploads((us) => us.map((u) => (u.key === up.key ? { ...u, state: "done" } : u)));
      } catch (e) {
        setUploads((us) => us.map((u) => (u.key === up.key ? { ...u, state: "error", error: errMessage(e) } : u)));
      }
    }
    if (!ready.length) return;
    try {
      const r = await importEditFiles(ready);
      for (const e of r.errors) toast.error(`${e.name}: ${e.error}`);
      if (r.job_ids.length) {
        // the new videos come ticked: "✏️ Chỉnh N video" is the next click
        setPicked((cur) => new Set([...cur, ...r.job_ids]));
        toast.success(`Đã thêm ${r.job_ids.length} video — đã tick sẵn, bấm “✏️ Chỉnh ${r.job_ids.length} video”.`);
      }
      setUploads((us) => us.filter((u) => u.state === "error"));
      await refresh();
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  async function addClips(boardIds: number[]) {
    setClipsOpen(false);
    if (!boardIds.length) return;
    try {
      const r = await importEditClips(boardIds);
      for (const e of r.errors) toast.warning(`${e.name}: ${e.error}`);
      if (r.job_ids.length) {
        setPicked((cur) => new Set([...cur, ...r.job_ids]));
        toast.success(`Đã thêm ${r.job_ids.length} video từ Clip của tôi — đã tick sẵn.`);
      }
      await refresh();
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    void addFiles(Array.from(e.dataTransfer.files));
  }
  async function removePicked(ids: string[]) {
    if (!ids.length) return;
    if (!(await askConfirm(`Bỏ ${ids.length} video khỏi danh sách chỉnh sửa?\nClip trong “Clip của tôi”, video đã xuất và file gốc vẫn còn nguyên.`,
                           { ok: `Bỏ ${ids.length} video`, danger: true }))) return;
    try {
      const r = await removeEditJobs(ids);
      if (r.kept.length) toast.warning(`${r.kept.length} video ${r.kept[0].why}.`);
      setPicked((cur) => { const n = new Set(cur); for (const id of r.removed) n.delete(id); return n; });
      await refresh();
    } catch (e) {
      toast.error(errMessage(e));
    }
  }
  function openEditor(ids: string[], first?: string) {
    if (!ids.length) return;
    if (ids.length > MAX_EDIT_TOGETHER) toast.warning(`Mở ${MAX_EDIT_TOGETHER} video đầu — trình chỉnh sửa nhận tối đa ${MAX_EDIT_TOGETHER} video một lượt.`);
    navigate(editPath(ids, first));
  }

  // ── the editor ─────────────────────────────────────────────────────────
  const [group, setGroup] = useState<DubJob[]>([]);
  const [job, setJob] = useState<DubJob | null>(null);
  const groupKey = wantJobs || wantJob || "";
  const groupIds = useMemo(() => groupKey.split(",").map((x) => x.trim()).filter(Boolean), [groupKey]);
  const loaded = useRef("");
  useEffect(() => {
    if (!editing) { setJob(null); setGroup([]); loaded.current = ""; return; }
    if (loaded.current === groupKey) {
      // the same videos: only the one on screen follows the URL
      const j = group.find((x) => x.job_id === wantJob);
      if (j && j.job_id !== job?.job_id) setJob(j);
      return;
    }
    let gone = false;
    void listDubJobsByIds(groupIds).then((jobs) => {
      if (gone) return;
      if (!jobs.length) {
        toast.warning("Không thấy các video này nữa trên máy.");
        setParams({}, { replace: true });
        return;
      }
      if (jobs.length < groupIds.length) toast.warning(`${groupIds.length - jobs.length} video không còn trên máy — mở ${jobs.length} video còn lại.`);
      loaded.current = groupKey;
      setGroup(jobs);
      setJob(jobs.find((x) => x.job_id === wantJob) ?? jobs[0]);
      // sent over by another tool: they join the list, so they are here next time too
      void addEditJobs(jobs.map((x) => x.job_id)).catch(() => undefined);
      window.scrollTo({ top: 0 });
    }).catch((e) => { if (!gone) { toast.error(errMessage(e)); setParams({}, { replace: true }); } });
    return () => { gone = true; };
  }, [editing, groupKey, wantJob]); // eslint-disable-line react-hooks/exhaustive-deps

  // while any of them is being exported: their state and percent (the editor's progress cover reads them)
  const groupWorking = group.some(isWorking);
  useEffect(() => {
    if (!editing || !groupWorking) return;
    let stopped = false;
    const tick = async () => {
      try {
        const jobs = await listDubJobsByIds(groupIds);
        if (stopped) return;
        setGroup((g) => g.map((x) => jobs.find((y) => y.job_id === x.job_id) ?? x));
        // the video on screen is only replaced when it really changed (a new object reloads the editor)
        setJob((j) => {
          const n = j ? jobs.find((x) => x.job_id === j.job_id) : undefined;
          if (!n || !j) return j;
          if (n.status === "done" && j.status !== "done") toast.success("Đã xuất xong — clip trong “Clip của tôi” dùng bản mới.");
          if (n.status === "error" && j.status !== "error") toast.error(n.error ?? "Xuất video lỗi.");
          return n.status !== j.status || n.media_id !== j.media_id || n.progress !== j.progress || n.phase !== j.phase ? n : j;
        });
      } catch { /* the next tick tries again */ }
    };
    const timer = window.setInterval(tick, 1500);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [editing, groupWorking, groupKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const patchGroup = (j: DubJob) => setGroup((g) => g.map((x) => (x.job_id === j.job_id ? j : x)));
  function switchJob(id: string) {
    const j = group.find((x) => x.job_id === id);
    if (j) setJob(j);
    navigate({ search: `?${new URLSearchParams(wantJobs ? { jobs: wantJobs, job: id } : { job: id }).toString()}` }, { replace: true, state: location.state });
  }
  function closeEditor() {
    if (backTo) { navigate(backTo); return; }
    setParams({}, { replace: true });
  }
  /** "⇪ Áp cho cả loạt": the look of the video on screen → every other one (each re-rendered; its own words and titles stay). */
  async function applyToOthers(look: BatchLook): Promise<number> {
    if (!job) return 0;
    const jobs = await listDubJobsByIds(groupIds);
    const targets = jobs.filter((j) => j.job_id !== job.job_id && (j.segments.length > 0 || j.kind === "cut") && !isWorking(j));
    const skipped = jobs.length - 1 - targets.length;
    let sent = 0;
    for (const t of targets) {
      try {
        const body: DubRender = { layout: look.layout, style: look.style, engine: look.engine, highlights: look.highlights, carried: true };
        // subtitles on / off / their language travel between videos without a voice-over only (a dubbed one stays Vietnamese)
        if (look.lang && t.kind === "cut" && look.lang !== (t.sub_lang ?? "none")) {
          if (look.lang === "none" || t.segments.length) body.sub_lang = look.lang;
          if (look.lang !== "none" && t.segments.length) body.lines = (await dubSubtitleLines(t.job_id, look.lang)).lines;
        }
        await renderDub(t.job_id, body);
        sent++;
      } catch (e) {
        toast.error(`${t.name || t.title || t.job_id}: ${errMessage(e)}`);
      }
    }
    if (skipped) toast.warning(`${skipped} video đang xuất hoặc chưa sẵn sàng — bỏ qua, áp lại sau.`);
    announceRunning();
    void listDubJobsByIds(groupIds).then((js) => setGroup((g) => g.map((x) => js.find((y) => y.job_id === x.job_id) ?? x))).catch(() => undefined);
    return sent;
  }

  if (!status) return <PageLoading text="Đang mở trình chỉnh sửa video…" />;

  if (editing) {
    return (
      <>
        <header className="qt-header">
          <span className="qt-header__crumb">🎞 Chỉnh sửa video{job ? ` › ${job.name || job.title || "video"}` : ""}</span>
        </header>
        <div className="qt-home qt-dub">
          {job ? (
            <DubEditor key={job.job_id} job={job} status={status} onClose={closeEditor}
                       onJob={(j) => { setJob(j); patchGroup(j); }} onSibling={patchGroup}
                       siblings={group} onSwitch={group.length > 1 ? switchJob : undefined}
                       onApplyAll={group.length > 1 ? applyToOthers : undefined} />
          ) : <PageLoading text="Đang mở video…" />}
        </div>
      </>
    );
  }

  const zipBoards = pickedItems.filter((i) => i.board_id && i.edited).map((i) => i.board_id!);
  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">🎞 Chỉnh sửa video</span>
      </header>
      <div className={`qt-home ed${dragOver ? " is-dropping" : ""}`}
           onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragOver(true); } }}
           onDragLeave={(e) => { if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false); }}
           onDrop={onDrop}>
        {dragOver && <div className="ed__dropmask"><div>📂 Thả video vào để thêm vào danh sách chỉnh sửa</div></div>}
        <input ref={fileInput} type="file" accept="video/*,.mkv" multiple hidden
               onChange={(e) => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />

        <section className="qt-card ed__add">
          <div className="ed__addtext">
            <h3 className="qt-card__title">Thêm video để chỉnh</h3>
            <p className="qt-card__hint">
              Thả nhiều file video vào trang này, hoặc lấy video đã có trong Clip của tôi. Tick các video → <b>✏️ Chỉnh</b> →
              chỉnh một video rồi <b>⇪ Áp cho cả loạt</b>.
            </p>
          </div>
          <div className="ed__addbtns">
            <button type="button" className="qt-btn qt-btn--accent" disabled={uploading} onClick={() => fileInput.current?.click()}>
              📁 Chọn video từ máy…
            </button>
            <button type="button" className="qt-btn" onClick={() => setClipsOpen(true)}>🎬 Chọn từ Clip của tôi</button>
          </div>
          {uploads.length > 0 && (
            <ul className="ed__ups" aria-live="polite">
              {uploads.map((u) => (
                <li key={u.key} className={`is-${u.state}`}>
                  <span className="ed__upname">{u.name}</span>
                  <span className="ed__upstate">
                    {u.state === "wait" ? "chờ…" : u.state === "up" ? "đang đưa vào…" : u.state === "done" ? "✓" : `⚠ ${u.error ?? "lỗi"}`}
                  </span>
                </li>
              ))}
              {!uploading && uploads.some((u) => u.state === "error") && (
                <li><button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setUploads([])}>Ẩn các file lỗi</button></li>
              )}
            </ul>
          )}
        </section>

        {items === null ? <PageLoading text="Đang tải danh sách…" /> : !list.length ? (
          <PageEmpty icon="🎞" title="Chưa có video nào để chỉnh" compact>
            Thả video vào trang này, bấm “📁 Chọn video từ máy…”, hoặc lấy từ Clip của tôi. Video lồng tiếng / cắt xong ở các menu khác
            cũng mở được ở đây bằng nút “✏️ Chỉnh”.
          </PageEmpty>
        ) : (
          <>
            <div className={`ed__bar${pickedItems.length ? " is-on" : ""}`} role="region" aria-label="Video đã chọn">
              <label className="qt-check">
                <input type="checkbox" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(list.map((i) => i.job_id)))} />
                Chọn tất cả ({list.length})
              </label>
              {pickedItems.length > 0 && <span className="ed__barcount">đã chọn <strong>{pickedItems.length}</strong></span>}
              <span className="ed__barspace" />
              {pickedItems.length > 0 ? (
                <>
                  <button type="button" className="qt-btn qt-btn--accent" onClick={() => openEditor(pickedItems.map((i) => i.job_id))}
                          title="Mở trình chỉnh sửa với các video đã chọn: chỉnh một video rồi “⇪ Áp cho cả loạt”">
                    ✏️ Chỉnh {pickedItems.length} video
                  </button>
                  {zipBoards.length > 0 && <ZipSaveButton ids={zipBoards} label={`⬇ Tải ${zipBoards.length} (.zip)`}
                                                          title="Lưu các video đã xuất trong số đã chọn thành một file .zip vào thư mục Tải về của máy này" />}
                  <button type="button" className="qt-btn qt-btn--danger" onClick={() => void removePicked(pickedItems.map((i) => i.job_id))}
                          title="Chỉ bỏ khỏi danh sách này — clip và file gốc vẫn còn">🗑 Bỏ {pickedItems.length}</button>
                </>
              ) : (
                <span className="ed__barhint">Tick video để chỉnh nhiều cái một lúc</span>
              )}
            </div>
            <div className="ed__grid">
              {list.map((i) => {
                const on = picked.has(i.job_id);
                const hearing = i.hear.state === "wait" || i.hear.state === "run";
                const tall = i.height > i.width;
                return (
                  <article key={i.job_id} className={`ed-v${on ? " is-on" : ""}${i.status === "error" ? " is-error" : ""}`}>
                    <label className="ed-v__thumb" title={on ? "Bỏ chọn" : "Chọn video này"}>
                      <input type="checkbox" checked={on} onChange={() => toggle(i.job_id)} aria-label={`Chọn “${i.name}”`} />
                      {i.media_id && <img className={tall ? "is-tall" : ""} src={`/api/media/${i.media_id}/poster`} alt="" loading="lazy"
                                          onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }} />}
                      <span className="ed-v__tick" aria-hidden="true">{on ? "✓" : ""}</span>
                      {i.duration_s ? <span className="ed-v__dur">{clock(i.duration_s)}</span> : null}
                    </label>
                    <div className="ed-v__body">
                      <div className="ed-v__name" title={i.name}>{i.name}</div>
                      <div className="ed-v__meta">
                        <span className="ed-v__kind">{i.origin === "dub" ? "🎙 lồng tiếng" : i.origin === "cut" ? "✂️ đã cắt" : "📁 thêm vào"}</span>
                        {isWorking(i) ? <span className="ed-v__chip is-run">⏳ {i.status === "queued" ? "chờ xuất" : `đang xuất ${i.progress}%`}</span>
                          : hearing ? <span className="ed-v__chip is-run">🎧 {i.hear.state === "wait" ? "chờ nghe lời" : `nghe lời ${i.hear.progress}%`}</span>
                          : i.status === "error" ? <span className="ed-v__chip is-bad" title={i.error ?? ""}>⚠ xuất lỗi</span>
                          : i.edited ? <span className="ed-v__chip is-ok">✓ đã xuất</span>
                          : <span className="ed-v__chip">chưa chỉnh</span>}
                      </div>
                      <div className="ed-v__acts">
                        <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
                                onClick={() => (on && pickedItems.length > 1 ? openEditor(pickedItems.map((p) => p.job_id), i.job_id) : openEditor([i.job_id]))}
                                title={on && pickedItems.length > 1 ? `Mở cả ${pickedItems.length} video đã chọn, bắt đầu từ video này` : "Mở trình chỉnh sửa"}>
                          ✏️ Chỉnh{on && pickedItems.length > 1 ? ` ${pickedItems.length}` : ""}
                        </button>
                        {i.media_id && <a className="qt-btn qt-btn--small" href={`/media/${i.media_id}`} target="_blank" rel="noreferrer" title="Xem video hiện tại">▶ Xem</a>}
                        {i.board_id && <button type="button" className="qt-btn qt-btn--small" onClick={() => navigate(`/clips/${i.board_id}/export`)} title="Clip của video này: tải, đăng, lên lịch">Clip →</button>}
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => void removePicked([i.job_id])} title="Bỏ khỏi danh sách (clip và file gốc vẫn còn)" aria-label={`Bỏ “${i.name}” khỏi danh sách`}>🗑</button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </div>
      {clipsOpen && (
        <ClipPickDialog everyClip max={maxImport} initial={[]} onClose={() => setClipsOpen(false)}
                        onPick={(clips) => void addClips(clips.map((c) => c.board_id))} />
      )}
    </>
  );
}
