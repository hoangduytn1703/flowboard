import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { announceRunning } from "../../components/BackgroundTasks";
import {
  dubSubtitleLines, getDubStatus, listDubJobsByIds, renderDub,
  type DubJob, type DubRender, type DubStatus,
} from "../../api/dub";
import { addEditJobs } from "../../api/edit";
import { toast } from "../../store/toast";
import { DubEditor, type BatchLook } from "../dub/editor/DubEditor";
import { PageLoading } from "../PageState";
import "../dub.css";
import "../edit.css";

/**
 * "✏️ Chỉnh sửa" (/tools/edit?jobs=a,b,c&job=b) — the CapCut-style editor on one or many videos side by side: edit one,
 * "⇪ Áp cho cả loạt" gives the others the same look, "Xuất cả N" renders them. The videos come from "Clip của tôi"
 * ("✏️ Chỉnh"), from "📥 Thêm video" (files, clips) or from the other tools; there is no second list of videos here
 * (24/11 — "Clip của tôi" is the one list). /tools/edit with no videos → "📥 Thêm video" with "Chỉnh sửa" picked.
 */
const WORKING = ["queued", "running", "rendering"];
const isWorking = (j: { status: string }) => WORKING.includes(j.status);
const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function EditPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  // the page that sent the videos here ("✏️ Chỉnh N video" on Cào video kênh, Clip của tôi…): "← Danh sách" goes back to it
  const backTo = (location.state as { back?: string } | null)?.back;
  const [status, setStatus] = useState<DubStatus | null>(null);
  const wantJobs = params.get("jobs");
  const wantJob = params.get("job");
  const editing = !!(wantJobs || wantJob);

  useEffect(() => {
    document.title = "Chỉnh sửa video · DFlow";
    if (editing) void getDubStatus().then(setStatus).catch((e) => toast.error(errMessage(e)));
  }, [editing]);

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
    navigate(backTo || "/clips");
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

  if (!editing) return <Navigate to="/tools?do=edit" replace />;
  if (!status) return <PageLoading text="Đang mở trình chỉnh sửa video…" />;
  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">✏️ Chỉnh sửa video{job ? ` › ${job.name || job.title || "video"}` : ""}</span>
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
