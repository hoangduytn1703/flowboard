import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  getTemplates,
  clipReady,
  clipThumbUrl,
  listBoardSummaries,
  mediaUrl,
  getDiskStatus,
  scanStorage,
  type BoardSummary,
  type BoardTemplate,
  type QuicktoolState,
  type DiskStatus,
  type StorageScan,
  getProduct,
  type ProductGender,
} from "../api/client";
import { ProductsPanel } from "../components/ProductsPanel";
import { ZipSaveButton } from "../components/ZipSaveButton";
import { SettingsPanel } from "../components/SettingsPanel";
import { useBoardStore } from "../store/board";
import { useQuicktoolStore } from "../store/quicktool";
import { useSettingsStore } from "../store/settings";
import { NewClipDialog, REFERENCE_KIND } from "./NewClipDialog";
import { QuicktoolSidebar } from "./QuicktoolSidebar";
import { creditsPerClip, deriveRoles, hasMedia, stepDone } from "./roles";
import { StepExport } from "./steps/StepExport";
import { StepMedia } from "./steps/StepMedia";
import { StepSequence } from "./steps/StepSequence";
import { StepScript } from "./steps/StepScript";
import { StepSetup } from "./steps/StepSetup";
import { CleanToolPage } from "./pages/CleanToolPage";
import { HistoryPage } from "./pages/HistoryPage";
import { TodayPage } from "./pages/TodayPage";
import { ModelsPage } from "./pages/ModelsPage";
import { VoicesPage } from "./pages/VoicesPage";
import { PromptsPage } from "./pages/PromptsPage";
import { PostsPage } from "./pages/PostsPage";
import { ChannelsPage } from "./pages/ChannelsPage";
import { AccountsPage } from "./pages/AccountsPage";
import { AccountPage } from "./pages/AccountPage";
import { DubPage } from "./pages/DubPage";
import { CutPage } from "./pages/CutPage";
import { GrabPage } from "./pages/GrabPage";
import { EditPage } from "./pages/EditPage";
import { VideoHubPage } from "./pages/VideoHubPage";
import { ClipChannel } from "./steps/ClipChannel";
import { ClipPost } from "./steps/ClipPost";
import { SchedulePage } from "./pages/SchedulePage";
import { SwipesPage } from "./pages/SwipesPage";
import { useFlowCredits } from "../components/credits";
import { AccountSwitchBanner } from "../components/AccountSwitchBanner";
import { BackgroundTasks } from "../components/BackgroundTasks";
import { SetupDialog } from "../components/SetupGuide";
import { useSetupStore } from "../store/setup";
import { AssistantWidget } from "../components/AssistantWidget";
import { useFeature } from "../lib/features";
import { editPath, importEditClips, MAX_EDIT_TOGETHER } from "../api/edit";
import { FeatureGate } from "./FeatureGate";
import { toast, useToastOn } from "../store/toast";
import { agoOf } from "../api/grab";
import { PageEmpty, PageLoading } from "./PageState";
import { askConfirm, askText } from "../components/Dialogs";

/** A part of "✂️ Cắt video" (board template "cut_part"): its project, run and place among the parts. */
function cutPartOf(qt: object, boardId: number | null): { job_id: string; run_id: string; index: number; total: number; board_id: number | null; imported: boolean } | null {
  const q = qt as { dub?: { job_id?: string }; cut?: { run_id?: string; index?: number; total?: number; origin?: string } };
  if (!q.dub?.job_id) return null;
  // origin "edit": a video brought into "🎞 Chỉnh sửa video" (a file, another clip), not a part of a cut
  return { job_id: q.dub.job_id, run_id: q.cut?.run_id ?? "", index: q.cut?.index ?? 1, total: q.cut?.total ?? 1, board_id: boardId, imported: q.cut?.origin === "edit" };
}

/** A clip made by a video tool rather than the step-by-step maker: what to call it (null = an ordinary clip). */
function videoKindOf(qt: object): string | null {
  const q = qt as { template_id?: string; dub?: { mode?: string }; cut?: { origin?: string } };
  switch (q.template_id) {
    case "dub": return q.dub?.mode === "sub" ? "Video có phụ đề" : "Video lồng tiếng";
    case "dub_part": return "Phần cắt từ video lồng tiếng";
    case "cut_part": return q.cut?.origin === "edit" ? "Video đã chỉnh sửa" : "Video cắt từ video dài";
    case "capcut": return "Video từ CapCut";
    default: return null;
  }
}

/** Wizard steps and their URL slugs: /clips/:id/<slug>. */
const STEPS = [
  { n: 1, slug: "setup", title: "Sản phẩm & thiết lập" },
  { n: 2, slug: "script", title: "Kịch bản & lời thoại" },
  { n: 3, slug: "images", title: "Tạo ảnh cảnh" },
  { n: 4, slug: "videos", title: "Tạo video" },
  { n: 5, slug: "export", title: "Ghép & lồng tiếng" },
] as const;

function slugOf(step: number): string {
  return STEPS.find((s) => s.n === step)?.slug ?? "setup";
}

function stepOf(slug: string | undefined): number | null {
  return STEPS.find((s) => s.slug === slug)?.n ?? null;
}

/** The browser tab says where you are; the base name stays last. */
function useTitle(title: string) {
  useEffect(() => {
    const prev = document.title;
    document.title = `${title} · DFlow`;
    return () => { document.title = prev; };
  }, [title]);
}

/** Back to the page this overlay opened from, or the library when the
 * overlay was the first thing opened (a deep link). */
function useCloseOverlay() {
  const navigate = useNavigate();
  return () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate("/clips", { replace: true });
  };
}

/**
 * The step-by-step clip maker: pick a product and a template, review the
 * script, render the scenes, render the clips, join them with a voice-over.
 * Everything acts on the ordinary board underneath (see `quicktool/roles`),
 * so the canvas stays available as the advanced view of the same clip.
 *
 * Pages have their own URLs: /clips (library), /clips/new,
 * /clips/from-video and /settings open over the library; /products is a page;
 * /clips/:id/:step is the wizard.
 */
export function QuicktoolApp() {
  const setUiMode = useSettingsStore((s) => s.setUiMode);
  const assistantOn = useFeature("assistant");
  const dubOn = useFeature("dub");
  const cutOn = useFeature("cut");
  const cleanOn = useFeature("clean");
  const [templates, setTemplates] = useState<BoardTemplate[]>([]);
  // the video editor gets the whole window: no app menu, no page title (its own bar has "← Quay lại" and the name)
  const here = useLocation();
  const focus = here.pathname === "/tools/edit" && /[?&]jobs?=/.test(here.search);

  useEffect(() => {
    setUiMode("quicktool");
    getTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [setUiMode]);

  return (
    <div className={`qt-app${focus ? " qt-app--focus" : ""}`}>
      <QuicktoolSidebar />
      <div className="qt-content">
        <AccountSwitchBanner />
        <BackgroundTasks />
        <SetupDialog />
        {assistantOn && <AssistantWidget />}
        <Routes>
          {/* Static paths first so "new" / "from-video" are never read as a clip id. */}
          <Route path="/clips" element={<Library templates={templates} />} />
          <Route path="/clips/new" element={<Library templates={templates} />} />
          <Route path="/clips/from-video" element={<Library templates={templates} />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/today" element={<TodayPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/voices" element={<VoicesPage />} />
          <Route path="/prompts" element={<PromptsPage />} />
          <Route path="/tools/clean" element={<FeatureGate feature="clean" title="Xoá chữ / logo"><CleanToolPage /></FeatureGate>} />
          <Route path="/posts" element={<FeatureGate feature="posts" title="Bài viết Facebook"><PostsPage /></FeatureGate>} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/accounts" element={<AccountsPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/schedule" element={<FeatureGate feature="facebook" title="Lịch đăng"><SchedulePage /></FeatureGate>} />
          <Route path="/swipes" element={<FeatureGate feature="swipes" title="Học bài viral"><SwipesPage /></FeatureGate>} />
          <Route path="/tools" element={dubOn || cutOn || cleanOn ? <VideoHubPage /> : <FeatureGate feature="dub" title="Xử lý video"><VideoHubPage /></FeatureGate>} />
          <Route path="/tools/dub" element={<FeatureGate feature="dub" title="Lồng tiếng video"><DubPage /></FeatureGate>} />
          {/* Edit auto CapCut is hidden (lib/features HIDDEN): it will come back inside the video editor; pages/CapcutPage.tsx is kept */}
          <Route path="/tools/edit" element={dubOn || cutOn ? <EditPage /> : <FeatureGate feature="cut" title="Chỉnh sửa video"><EditPage /></FeatureGate>} />
          <Route path="/tools/capcut" element={<Navigate to="/tools/cut" replace />} />
          <Route path="/tools/grab" element={<FeatureGate feature="grab" title="Cào video kênh"><GrabPage /></FeatureGate>} />
          <Route path="/tools/cut" element={<FeatureGate feature="cut" title="Cắt video"><CutPage /></FeatureGate>} />
          <Route path="/settings" element={<Library templates={templates} />} />
          <Route path="/clips/:id/:step" element={<Wizard templates={templates} />} />
          <Route path="/clips/:id" element={<Wizard templates={templates} />} />
          <Route path="*" element={<Navigate to="/clips" replace />} />
        </Routes>
      </div>
    </div>
  );
}

/** /products — the product library as a page of its own. */
function ProductsPage() {
  const navigate = useNavigate();
  useTitle("Sản phẩm");
  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Sản phẩm đang bán</span>
      </header>
      <div className="qt-home">
        <ProductsPanel
          asPage
          onClose={() => navigate("/clips")}
          onMakeClip={(p) => navigate(`/clips/new?product=${p.id}${p.template_id ? `&template=${p.template_id}` : ""}`)}
        />
      </div>
    </>
  );
}

/** /clips with the dialog routes layered over the clip grid. */
/** Columns the auto-fill grid shows right now (kept up to date when the window is resized). */
function useGridColumns(ref: React.RefObject<HTMLElement>): number {
  const [cols, setCols] = useState(4);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setCols(Math.max(1, getComputedStyle(el).gridTemplateColumns.split(" ").filter(Boolean).length));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return cols;
}

/** "Clip của tôi": at most this many rows of cards a page ("Clip mới" counts as one card). */
const LIBRARY_ROWS = 3;
type LibraryTab = "done" | "draft" | "missing";
const LIBRARY_TAB_KEY = "dflow.clips.tab";

function fmtBytes(n: number): string {
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1).replace(".", ",")} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`;
}

/** A clip made by "🎙 Lồng tiếng" / "✂️ Cắt video": the editor project behind it (several open together with "✏️ Chỉnh N video"). */
function dubJobOf(b: BoardSummary): string | null {
  const qt = (b.data as { quicktool?: { template_id?: string; dub?: { job_id?: string } } } | undefined)?.quicktool;
  return qt && (qt.template_id === "dub" || qt.template_id === "cut_part") ? qt.dub?.job_id ?? null : null;
}

function Library({ templates }: { templates: BoardTemplate[] }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const boardId = useBoardStore((s) => s.boardId);
  const boards = useBoardStore((s) => s.boards);
  const [summaries, setSummaries] = useState<BoardSummary[] | null>(null);
  const [disk, setDisk] = useState<DiskStatus | null>(null);
  const [scan, setScan] = useState<StorageScan | null>(null);
  const [scanning, setScanning] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(() => new Set());
  const queue = useQuicktoolStore((s) => s.queue);
  const runQueue = useQuicktoolStore((s) => s.runQueue);
  const autoClip = useFeature("auto_clip");
  const dubOn = useFeature("dub");
  const cutOn = useFeature("cut");
  const stopQueue = useQuicktoolStore((s) => s.stopQueue);
  const autoMessage = useQuicktoolStore((s) => s.autoMessage);
  const videoModel = useSettingsStore((s) => s.videoModel);
  const videoQuality = useSettingsStore((s) => s.videoQuality);
  const closeOverlay = useCloseOverlay();
  const { credits: flowCredits } = useFlowCredits();
  useTitle("Clip của tôi");

  useEffect(() => {
    listBoardSummaries().then(setSummaries).catch(() => setSummaries([]));
  }, [boards.length, pathname]);
  // Cheap (one syscall) so it is safe to check every time the page opens; the deeper per-clip
  // breakdown only runs from the "🔍 Quét bộ nhớ" button below.
  useEffect(() => {
    getDiskStatus().then(setDisk).catch(() => {});
  }, [pathname]);
  async function runStorageScan() {
    if (scanning) return;
    setScanning(true);
    try {
      const row = await scanStorage();
      setScan(row);
      setDisk(row);
      toast.info(`Video đã làm đang chiếm ${fmtBytes(row.total_clips_bytes)} trên máy này — còn trống ${fmtBytes(row.free)}.`);
    } catch {
      toast.error("Quét bộ nhớ lỗi, thử lại sau.");
    } finally {
      setScanning(false);
    }
  }
  // While the queue runs, the cards keep up with the clip being worked on.
  useEffect(() => {
    if (!queue.running) return;
    const t = setInterval(() => listBoardSummaries().then(setSummaries).catch(() => {}), 8000);
    return () => clearInterval(t);
  }, [queue.running]);

  const dialog = pathname === "/clips/new" ? "new"
    : pathname === "/clips/from-video" ? "reference"
    : pathname === "/settings" ? "settings"
    : null;
  const productParam = params.get("product");

  const all = (summaries ?? []).slice().reverse();
  // Only finished clips whose video plays here are "my clips"; the rest wait in their own tabs.
  const groups = {
    done: all.filter((b) => clipReady(b.summary)),
    draft: all.filter((b) => !b.summary.exported),
    missing: all.filter((b) => b.summary.exported && b.summary.video === "missing"),
  };
  const [tabPick, setTabPick] = useState<LibraryTab>(() => {
    try {
      const saved = sessionStorage.getItem(LIBRARY_TAB_KEY);
      return saved === "draft" || saved === "missing" ? saved : "done";
    } catch {
      return "done";
    }
  });
  // A tab left empty (its last clip deleted / finished) falls back to the finished clips.
  const tab: LibraryTab = tabPick !== "done" && summaries !== null && groups[tabPick].length === 0 ? "done" : tabPick;
  function chooseTab(t: LibraryTab) {
    setTabPick(t);
    setPicked(new Set());
    setConfirmDelete(false);
    setPage(1);
    try { sessionStorage.setItem(LIBRARY_TAB_KEY, t); } catch { /* private window */ }
  }
  const list = groups[tab];
  // Paged, three rows a page whatever the width: the "Clip mới" card opens every page.
  const gridRef = useRef<HTMLDivElement>(null);
  const cols = useGridColumns(gridRef);
  const perPage = Math.max(1, cols * LIBRARY_ROWS - 1);
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(list.length / perPage));
  const current = Math.min(page, pages);
  const shown = list.slice((current - 1) * perPage, current * perPage);
  // Clips that still have something to make: what "run all" would pick.
  const unfinished = groups.draft;
  const pickedList = list.filter((b) => picked.has(b.id));
  const perClip = creditsPerClip(videoModel, videoQuality);
  // Only the unfinished ones among the ticked clips can be run; any ticked clip can be downloaded / deleted.
  const pickedRunnable = pickedList.filter((b) => !b.summary.exported);
  // the ticked finished clips: open in the editor side by side, one look for all
  const pickedReady = pickedList.filter((b) => clipReady(b.summary));
  const editOn = dubOn || cutOn;
  const [opening, setOpening] = useState<number | null>(null);
  /** "✏️ Chỉnh" on the ticked clips (or one card): a dubbed / cut clip opens its own project; any other finished clip gets one
   *  for its video (its edited export becomes a clip of its own). */
  async function openInEditor(targets: BoardSummary[]) {
    const own = targets.map(dubJobOf).filter((id): id is string => !!id);
    const others = targets.filter((b) => !dubJobOf(b)).map((b) => b.id);
    const ids = [...own];
    if (others.length) {
      try {
        const r = await importEditClips(others);
        for (const e of r.errors) toast.warning(`${e.name}: ${e.error}`);
        ids.push(...r.job_ids);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    }
    if (!ids.length) return;
    if (ids.length > MAX_EDIT_TOGETHER) toast.warning(`Mở ${MAX_EDIT_TOGETHER} video đầu — trình chỉnh sửa nhận tối đa ${MAX_EDIT_TOGETHER} video một lượt.`);
    navigate(editPath(ids), { state: { back: "/clips" } });
  }
  async function editClip(b: BoardSummary) {
    setOpening(b.id);
    try { await openInEditor([b]); } finally { setOpening(null); }
  }
  function editPicked() {
    void openInEditor(pickedList.filter((b) => clipReady(b.summary)));
  }
  const allPicked = list.length > 0 && pickedList.length === list.length;
  const deleteBoardById = useBoardStore((s) => s.deleteBoardById);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  function toggleAll() {
    setConfirmDelete(false);
    setPicked(allPicked ? new Set() : new Set(list.map((b) => b.id)));
  }

  async function deletePicked() {
    if (pickedList.length === 0 || deleting) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setDeleting(true);
    const ids = pickedList.map((b) => b.id);
    let failed = 0;
    for (const id of ids) {
      await deleteBoardById(id);
      // deleteBoardById swallows errors into the store: a board still listed afterwards was not deleted.
      if (useBoardStore.getState().boards.some((b) => b.id === id)) failed += 1;
    }
    setPicked(new Set());
    setConfirmDelete(false);
    setDeleting(false);
    setSummaries(await listBoardSummaries().catch(() => []));
    if (failed) toast.error(`Không xoá được ${failed}/${ids.length} clip.`);
    else toast.success(`Đã xoá ${ids.length} clip.`);
  }

  function togglePick(id: number) {
    setConfirmDelete(false);
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function startQueue(targets: BoardSummary[]) {
    if (targets.length === 0 || queue.running) return;
    const videos = targets.reduce((t, b) => t + Math.max(b.summary.clips - b.summary.clips_done, 0), 0);
    const images = targets.reduce((t, b) => t + Math.max(b.summary.scenes - b.summary.scenes_done, 0), 0);
    const cost = videos * perClip;
    const balance = flowCredits === null ? "" : ` Tài khoản còn ${flowCredits.toLocaleString("vi-VN")} credit${cost > flowCredits ? " — KHÔNG ĐỦ cho cả hàng đợi" : ""}.`;
    const ok = await askConfirm(
      `Chạy tự động ${targets.length} clip, lần lượt từng clip: ` +
      `${images} ảnh + ${videos} video (~${cost} credit Flow).${balance} ` +
      `Khoảng ${Math.max(1, Math.round(videos * 2 + images * 0.5))} phút. Tiếp tục?`,
    );
    if (!ok) return;
    setPicked(new Set());
    void runQueue(targets.map((b) => b.id));
  }

  function cardState(id: number): { label: string; tone: string } | null {
    if (queue.current === id) return { label: autoMessage ?? "đang chạy…", tone: "busy" };
    if (queue.pending.includes(id)) return { label: "chờ đến lượt", tone: "idle" };
    if (queue.done.includes(id)) return { label: "✓ xong", tone: "done" };
    if (id in queue.failed) return { label: `lỗi: ${queue.failed[id]}`.slice(0, 80), tone: "error" };
    return null;
  }

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Clip của tôi</span>
      </header>
      <div className="qt-home">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Thư viện</div>
            <h3 className="qt-card__title">Clip của tôi{summaries ? ` · ${groups.done.length}` : ""}</h3>
          </div>
          <div className="qt-row">
            {queue.running ? (
              <button type="button" className="qt-btn qt-btn--danger" onClick={stopQueue}>■ Dừng hàng đợi</button>
            ) : pickedList.length > 0 ? (
              <>
                {pickedList.some((b) => b.summary.exported) && (
                  <ZipSaveButton ids={pickedList.filter((b) => b.summary.exported).map((b) => b.id)}
                                 label={`⬇ Tải ${pickedList.filter((b) => b.summary.exported).length} clip đã ghép`}
                                 title="Lưu các clip đã ghép (tên theo sản phẩm + ngày) vào thư mục lưu video — đổi thư mục ở Cài đặt → 🖥 Máy này" />
                )}
                {editOn && pickedReady.length > 0 && (
                  <button type="button" className="qt-btn qt-btn--accent" disabled={deleting} onClick={editPicked}
                          title="Mở trình chỉnh sửa với các clip đã chọn: chỉnh một clip rồi bấm “⇪ Áp cho cả loạt” để mọi clip cùng kiểu (khung, nền, phụ đề, chữ, nhân vật)">
                    ✏️ Chỉnh {pickedReady.length} video
                  </button>
                )}
                {autoClip && pickedRunnable.length > 0 && (
                  <button type="button" className="qt-btn qt-btn--accent" disabled={deleting} onClick={() => startQueue(pickedRunnable)}
                          title="Chỉ chạy các clip chưa ghép xong trong số đã chọn">
                    ⚡ Chạy {pickedRunnable.length} clip dở
                  </button>
                )}
                <button type="button" className="qt-btn qt-btn--danger" disabled={deleting} onClick={() => void deletePicked()}
                        title="Xoá clip khỏi thư viện (video đã xuất không bị xoá khỏi máy)">
                  {deleting ? "Đang xoá…" : confirmDelete ? `Bấm lần nữa để xoá ${pickedList.length} clip` : `🗑 Xoá ${pickedList.length} clip`}
                </button>
                <button type="button" className="qt-btn qt-btn--ghost" disabled={deleting}
                        onClick={() => { setPicked(new Set()); setConfirmDelete(false); }}>Bỏ chọn</button>
              </>
            ) : (
              <>
                {autoClip && tab === "draft" && unfinished.length > 1 && (
                  <button type="button" className="qt-btn qt-btn--ghost" onClick={() => startQueue(unfinished)}
                          title="Chạy tự động mọi clip chưa ghép xong, lần lượt từng clip">
                    ⚡ Chạy tất cả {unfinished.length} clip dở
                  </button>
                )}
                {tab === "done" && list.length > 0 && (
                  <button type="button" className="qt-btn qt-btn--ghost" disabled={scanning} onClick={() => void runStorageScan()}
                          title="Đo mỗi clip đang chiếm bao nhiêu dung lượng trên máy này, và còn trống bao nhiêu — có thể chậm một chút nếu thư viện lớn">
                    {scanning ? "Đang quét…" : "🔍 Quét bộ nhớ"}
                  </button>
                )}
                <button type="button" className="qt-btn qt-btn--accent" onClick={() => navigate("/clips/new")}>+ Clip mới</button>
              </>
            )}
          </div>
        </div>
        {queue.running && (
          <div className="qt-banner qt-banner--busy">
            <span className="qt-spinner" />
            Hàng đợi: clip {queue.done.length + Object.keys(queue.failed).length + 1}/{queue.done.length + Object.keys(queue.failed).length + 1 + queue.pending.length}
            {queue.current !== null && ` — ${list.find((b) => b.id === queue.current)?.name ?? `#${queue.current}`}`}
            {autoMessage ? ` · ${autoMessage}` : ""}
          </div>
        )}
        {disk?.low && (
          <div className="qt-banner qt-banner--warn">
            ⚠ Ổ đĩa máy này sắp hết chỗ — chỉ còn {fmtBytes(disk.free)} trống. Bấm "🔍 Quét bộ nhớ" để xem clip nào
            đang chiếm nhiều dung lượng rồi xoá bớt clip cũ không cần nữa.
          </div>
        )}
        {summaries !== null && (groups.draft.length > 0 || groups.missing.length > 0) && (
          <div className="qt-libtabs" role="tablist" aria-label="Loại clip">
            <button type="button" role="tab" aria-selected={tab === "done"} className={`qt-libtabs__tab${tab === "done" ? " qt-libtabs__tab--on" : ""}`}
                    onClick={() => chooseTab("done")}>✓ Đã xong <span className="qt-libtabs__n">{groups.done.length}</span></button>
            {groups.draft.length > 0 && (
              <button type="button" role="tab" aria-selected={tab === "draft"} className={`qt-libtabs__tab${tab === "draft" ? " qt-libtabs__tab--on" : ""}`}
                      onClick={() => chooseTab("draft")} title="Clip đang làm (chưa ghép thành video) — mở để làm tiếp">
                ✎ Đang làm dở <span className="qt-libtabs__n">{groups.draft.length}</span>
              </button>
            )}
            {groups.missing.length > 0 && (
              <button type="button" role="tab" aria-selected={tab === "missing"}
                      className={`qt-libtabs__tab qt-libtabs__tab--warn${tab === "missing" ? " qt-libtabs__tab--on" : ""}`}
                      onClick={() => chooseTab("missing")} title="Clip đã xong ở máy khác / ở app cài nhưng video không có trên máy này">
                ⚠ Video không có trên máy này <span className="qt-libtabs__n">{groups.missing.length}</span>
              </button>
            )}
          </div>
        )}
        {tab === "missing" && (
          <div className="qt-banner qt-banner--warn">
            Các clip này đã làm xong ở máy khác (hoặc ở app DFlow cài trên máy, app dùng thư mục dữ liệu riêng) nhưng video chưa
            lên được kho cloud, nên máy này không mở / tải được. Mở chúng bằng đúng máy / app đã làm ra, hoặc chọn rồi xoá khỏi danh sách.
          </div>
        )}
        {summaries !== null && summaries.length > 0 && tab === "done" && list.length === 0 && (
          <PageEmpty icon="🎬" title="Chưa có clip nào làm xong" compact
                     actions={groups.draft.length > 0
                       ? <button type="button" className="qt-btn qt-btn--accent" onClick={() => chooseTab("draft")}>Xem {groups.draft.length} clip đang làm dở</button>
                       : <button type="button" className="qt-btn qt-btn--accent" onClick={() => navigate("/clips/new")}>+ Clip mới</button>}>
            Clip chỉ hiện ở đây khi đã ghép xong thành video.
          </PageEmpty>
        )}
        {list.length > 0 && !queue.running && (
          <div className="qt-clip-bulk">
            <label className="qt-clip-bulk__all">
              <input type="checkbox" checked={allPicked} disabled={deleting} onChange={toggleAll} />
              <span>Chọn tất cả ({list.length})</span>
            </label>
            {pickedList.length > 0 && <span className="qt-clip-bulk__count">đã chọn {pickedList.length}</span>}
          </div>
        )}
        {summaries !== null && summaries.length === 0 && (
          <PageEmpty icon="🎬" title="Chưa có clip nào"
                     actions={<>
                       <button type="button" className="qt-btn qt-btn--accent qt-btn--big" onClick={() => navigate("/clips/new")}>+ Tạo clip đầu tiên</button>
                       <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate("/products")}>Thêm sản phẩm trước</button>
                     </>}>
            Bấm <strong>+ Clip mới</strong>, chọn kiểu clip và dán ảnh sản phẩm — AI viết kịch bản, tạo ảnh, tạo video và ghép lại có giọng đọc tiếng Việt.
          </PageEmpty>
        )}
        <div className="qt-home__grid" ref={gridRef}>
          {summaries === null && Array.from({ length: 6 }, (_, i) => (
            <div key={`sk-${i}`} className="qt-clip qt-clip--skeleton" aria-hidden="true">
              <span className="qt-clip__thumb qt-skeleton" />
              <span className="qt-skeleton qt-skeleton--line" />
              <span className="qt-skeleton qt-skeleton--line qt-skeleton--short" />
            </div>
          ))}
          {shown.map((b) => {
            const st = cardState(b.id);
            const pickable = !queue.running;
            return (
              <div key={b.id} className={`qt-clip${b.id === boardId ? " qt-clip--active" : ""}${picked.has(b.id) ? " qt-clip--picked" : ""}${st ? ` qt-clip--${st.tone}` : ""}`}>
                {pickable && (
                  <label className="qt-clip__pick" title="Chọn để chạy, tải hoặc xoá nhiều clip" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={picked.has(b.id)} onChange={() => togglePick(b.id)} />
                  </label>
                )}
                {tab === "done" && editOn && !queue.running && (
                  <button type="button" className="qt-clip__edit" disabled={opening === b.id} onClick={() => void editClip(b)}
                          title="Mở trình chỉnh sửa: khung, nền, chữ, phụ đề, che logo, tốc độ…" aria-label={`Chỉnh sửa “${b.name}”`}>
                    {opening === b.id ? "…" : "✏️ Chỉnh"}
                  </button>
                )}
                <button type="button" className="qt-clip__open" disabled={queue.running && queue.current !== b.id}
                        onClick={() => navigate(`/clips/${b.id}`)}>
                  {clipThumbUrl(b.summary) ? (
                    <img className="qt-clip__thumb" src={clipThumbUrl(b.summary)!} alt="" loading="lazy" />
                  ) : (
                    <span className="qt-clip__thumb qt-clip__thumb--empty">🎬</span>
                  )}
                  <span className="qt-clip__name">{b.name}</span>
                  <span className="qt-clip__age" title={`Tạo lúc ${new Date(b.created_at).toLocaleString("vi-VN")}`}>
                    {agoOf(b.created_at)}
                    {scan?.by_board[String(b.id)] !== undefined && ` · ${fmtBytes(scan.by_board[String(b.id)])}`}
                  </span>
                  {b.summary.exported ? (
                    <span className="qt-clip__meta">{videoKindOf((b.data as { quicktool?: object } | undefined)?.quicktool ?? {}) ?? "Clip sản phẩm"}</span>
                  ) : (
                    <span className="qt-clip__meta">
                      {b.summary.scenes_done}/{b.summary.scenes} ảnh cảnh · {b.summary.clips_done}/{b.summary.clips} video cảnh
                    </span>
                  )}
                  {(st || b.summary.video === "missing" || !b.summary.exported) && (
                    <span className={`qt-clip__state qt-clip__state--${st ? st.tone : b.summary.video === "missing" ? "error" : "idle"}`}>
                      {st ? st.label : b.summary.video === "missing" ? "⚠ video không có trên máy này" : "chưa ghép thành video"}
                    </span>
                  )}
                </button>
              </div>
            );
          })}
        </div>
        {pages > 1 && (
          <nav className="qt-pager qt-home__pager" aria-label="Phân trang clip">
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current <= 1} onClick={() => setPage(current - 1)}>← Trước</button>
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <button key={n} type="button" aria-current={n === current ? "page" : undefined}
                      className={`qt-pager__num${n === current ? " qt-pager__num--active" : ""}`} onClick={() => setPage(n)}>{n}</button>
            ))}
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current >= pages} onClick={() => setPage(current + 1)}>Sau →</button>
            <span className="qt-pager__info">{(current - 1) * perPage + 1}–{Math.min(current * perPage, list.length)} / {list.length} clip</span>
          </nav>
        )}
      </div>

      {(dialog === "new" || dialog === "reference") && (
        <NewClipDialog
          templates={templates}
          initialTemplateId={dialog === "reference" ? REFERENCE_KIND : params.get("template")}
          initialProductId={productParam ? Number(productParam) : null}
          onClose={closeOverlay}
          onCreated={(id) => navigate(`/clips/${id}/setup`, { replace: true })}
          onCreatedMany={() => navigate("/clips", { replace: true })}
        />
      )}
      <SettingsPanel open={dialog === "settings"} onClose={closeOverlay} logoutPending={false} />
    </>
  );
}

/** /clips/:id/:step — the wizard over one board. */
function Wizard({ templates }: { templates: BoardTemplate[] }) {
  const { id, step: stepSlug } = useParams();
  const navigate = useNavigate();
  const autoClip = useFeature("auto_clip");
  const routeId = Number(id);

  const boardId = useBoardStore((s) => s.boardId);
  const boardName = useBoardStore((s) => s.boardName);
  const boards = useBoardStore((s) => s.boards);
  const nodes = useBoardStore((s) => s.nodes);
  const edges = useBoardStore((s) => s.edges);
  const switchBoard = useBoardStore((s) => s.switchBoard);
  const renameBoard = useBoardStore((s) => s.renameBoard);
  const deleteBoardById = useBoardStore((s) => s.deleteBoardById);

  const setStep = useQuicktoolStore((s) => s.setStep);
  const syncFromBoard = useQuicktoolStore((s) => s.syncFromBoard);
  const auto = useQuicktoolStore((s) => s.auto);
  const autoMessage = useQuicktoolStore((s) => s.autoMessage);
  const error = useQuicktoolStore((s) => s.error);
  const clearError = useQuicktoolStore((s) => s.clearError);
  useToastOn(error, "error", clearError);
  const runAuto = useQuicktoolStore((s) => s.runAuto);
  const stopAuto = useQuicktoolStore((s) => s.stopAuto);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const videoModel = useSettingsStore((s) => s.videoModel);
  const videoQuality = useSettingsStore((s) => s.videoQuality);

  const loaded = !isNaN(routeId) && boardId === routeId;
  const roles = useMemo(() => deriveRoles(loaded ? nodes : [], loaded ? edges : []), [loaded, nodes, edges]);
  const running = auto !== "idle" && auto !== "done" && auto !== "stopped" && auto !== "failed";
  const qt = (boards.find((b) => b.id === routeId)?.data?.quicktool ?? {}) as QuicktoolState;
  const template = templates.find((t) => t.id === qt.template_id) ?? null;
  const isDrama = qt.template_id === "drama";
  // a video made by the tools (dub, cut, edit, CapCut): one screen — no product, scenes or steps 1–4
  const videoKind = videoKindOf(qt);
  const kindLabel = template?.title ?? (qt.template_id === "reference_video" ? "Theo video mẫu" : qt.template_id === "product_link" ? "Theo link sản phẩm" : isDrama ? "Drama" : "Clip");
  // Drama clips have no video step: stills are animated at export time, so
  // step 4 is where spliced-in footage is ordered.
  const stepTitles: Record<number, string> = isDrama
    ? { 1: "Nguồn & thiết lập", 2: "Lời kể từng đoạn", 3: "Tạo ảnh minh hoạ", 4: "Sắp xếp & chèn clip", 5: "Ghép & lồng tiếng" }
    : {};
  const step = stepOf(stepSlug);
  // Who the clip's product is for (step 1 only offers models of that gender)
  // and its industry (step 2 offers the saved prompts of that industry first).
  const [productGender, setProductGender] = useState<ProductGender>("");
  const [productCategory, setProductCategory] = useState<string | null>(null);
  // Name + price for step 5's text overlays ("+ Tên sản phẩm", "+ Giá").
  const [productLabel, setProductLabel] = useState<{ name: string; price: string }>({ name: "", price: "" });
  useEffect(() => {
    const pid = qt.product_id;
    if (!pid) { setProductGender(""); setProductCategory(null); setProductLabel({ name: "", price: "" }); return; }
    let alive = true;
    getProduct(pid)
      .then((p) => { if (alive) { setProductGender(p.gender ?? ""); setProductCategory(p.category ?? null); setProductLabel({ name: p.name ?? "", price: p.price ?? "" }); } })
      .catch(() => { if (alive) { setProductGender(""); setProductCategory(null); } });
    return () => { alive = false; };
  }, [qt.product_id]);
  // No saved product (link / video clips): the industry read from the page, else the template's.
  const clipCategory = productCategory ?? qt.reference?.category ?? (template?.category && template.category !== "any" ? template.category : null);
  const { credits: flowCredits } = useFlowCredits();
  useTitle(loaded && boardName ? (videoKind ? boardName : `${boardName} · Bước ${step ?? qt.step ?? 1}`) : "Đang mở clip…");

  /** The auto run, after saying what it will spend. */
  async function startAuto() {
    if (!(await useSetupStore.getState().ensureReady("tạo video tự động"))) return;
    const images = roles.scenes.filter((s) => !hasMedia(s.image)).length + (roles.model && !hasMedia(roles.model) ? 1 : 0);
    const videos = isDrama ? 0 : roles.scenes.filter((s) => s.video && !hasMedia(s.video)).length;
    const cost = videos * creditsPerClip(videoModel, videoQuality);
    const parts = [images ? `${images} ảnh` : "", videos ? `${videos} video (~${cost} credit Flow)` : ""].filter(Boolean);
    const what = parts.length ? `Sẽ tạo ${parts.join(" + ")}, rồi viết lời thoại và ghép clip.` : "Mọi cảnh đã có — chỉ viết lời thoại và ghép clip.";
    // Stills two at a time (~30 s), clips three at a time (~1–2 min a wave), then the join
    // (measured 26/10: 5 stills + 4 clips + export in ~4.5 min).
    const mins = Math.max(1, Math.round(Math.ceil(images / 2) * 0.5 + Math.ceil(videos / 3) * 1.2 + 1.5));
    const balance = flowCredits === null ? "" : `\nTài khoản Flow còn ${flowCredits.toLocaleString("vi-VN")} credit${cost > flowCredits ? " — KHÔNG ĐỦ, clip sẽ hỏng giữa chừng" : ""}.`;
    // a clip about a product nobody showed the AI comes out as some other product: say so before the credits go
    if (roles.products.length > 0 && !roles.products.some((p) => p.data.mediaId)) {
      const go = await askConfirm("⚠ Chưa có ảnh sản phẩm.\nKhông có ảnh thật, AI sẽ tự tưởng tượng sản phẩm — clip dễ ra sai món hàng. Nên upload ảnh ở Bước 1 trước.",
        { ok: "Vẫn tạo, không cần ảnh", cancel: "Về Bước 1 thêm ảnh" });
      if (!go) { if (boardId !== null) navigate(`/clips/${boardId}/setup`); return; }
    }
    if (!await askConfirm(`${what}${balance}\nKhoảng ${mins} phút. Tiếp tục?`)) return;
    void runAuto();
  }

  // URL → board: a deep link or the back button loads the board it names.
  // A board that is not in the list (just deleted, or a stale link) is not
  // fetched: that answered 404 and put an error toast on a clean delete.
  const loadingBoard = useBoardStore((s) => s.loading);
  const boardsLoaded = useBoardStore((s) => s.boardsLoaded);
  const refreshBoards = useBoardStore((s) => s.refreshBoards);
  // A clip made on the agent side after the list was read (🎁 content pack, 🔥 swipe, dubbing…)
  // is missing from it: read the list again once before calling the link stale.
  // `navigate` changes on every URL change (/clips/17 → /clips/17/script), so the
  // effect re-runs before the fresh list is back: wait for it, don't bounce.
  // The read in flight is a ref, not state: the effect can run again before a state update lands (StrictMode runs
  // effects twice; deps changing in the same commit) and then saw "already read, still missing" → bounced (31/10).
  const refreshedFor = useRef<number | null>(null);
  const refreshing = useRef(false);
  const [refreshTick, setRefreshTick] = useState(0);
  // A clip already loaded in the store may have changed on the agent since (a dub / CapCut export writes the new video
  // onto it): switchBoard skips the current board, so opening it again reads it fresh — Step 5 used to show (and
  // download) the video from before the last "Xuất lại" (29/10).
  const refreshBoardState = useBoardStore((s) => s.refreshBoardState);
  const freshFor = useRef<number | null>(null);
  useEffect(() => {
    if (isNaN(routeId) || routeId !== boardId || freshFor.current === routeId) return;
    freshFor.current = routeId;
    void refreshBoardState();
  }, [routeId, boardId, refreshBoardState]);
  useEffect(() => {
    if (isNaN(routeId) || routeId === boardId || !boardsLoaded || refreshing.current) return;
    if (boards.some((b) => b.id === routeId)) { freshFor.current = routeId; void switchBoard(routeId); return; }
    if (loadingBoard) return;
    if (refreshedFor.current !== routeId) {
      refreshedFor.current = routeId;
      refreshing.current = true;
      // a failed read falls through to the stale-link bounce on the next run
      void refreshBoards()
        .catch(() => undefined)
        .finally(() => { refreshing.current = false; setRefreshTick((t) => t + 1); });
      return;
    }
    navigate("/clips", { replace: true });
  }, [routeId, boardId, boards, boardsLoaded, loadingBoard, refreshTick, switchBoard, refreshBoards, navigate]);

  // No step in the URL: continue where this clip was left.
  useEffect(() => {
    if (step !== null || isNaN(routeId)) return;
    const saved = qt.step && qt.step >= 1 && qt.step <= 5 ? qt.step : 1;
    navigate(`/clips/${routeId}/${slugOf(saved)}`, { replace: true });
  }, [step, routeId, qt.step, navigate]);

  // URL step → store (persisted on the board) and the auto-run reset.
  useEffect(() => {
    if (!loaded) return;
    syncFromBoard();
    setConfirmDelete(false);
  }, [loaded, routeId, syncFromBoard]);
  useEffect(() => {
    if (loaded && step !== null && useQuicktoolStore.getState().step !== step) setStep(step);
  }, [loaded, step, setStep]);
  // The auto run ends on the export step — once, when it finishes. `auto`
  // stays "done" afterwards, so keying on the value alone sent every later
  // click on steps 1–4 straight back to step 5.
  const prevAuto = useRef(auto);
  useEffect(() => {
    const finished = auto === "done" && prevAuto.current !== "done";
    prevAuto.current = auto;
    if (finished && step !== 5 && loaded) navigate(`/clips/${routeId}/export`);
  }, [auto, step, loaded, routeId, navigate]);

  function go(n: number) {
    navigate(`/clips/${routeId}/${slugOf(n)}`);
  }

  async function removeClip() {
    if (!loaded) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    await deleteBoardById(routeId);
    setConfirmDelete(false);
    navigate("/clips");
  }

  async function rename() {
    const next = await askText("Tên clip", boardName);
    if (next && next.trim() && next.trim() !== boardName) void renameBoard(next.trim());
  }

  if (isNaN(routeId)) return <Navigate to="/clips" replace />;
  if (!loaded || step === null) {
    return (
      <>
        <header className="qt-header"><span className="qt-header__crumb">Đang mở clip…</span></header>
        <div className="qt-home"><PageLoading text="Đang mở clip…" /></div>
      </>
    );
  }

  const exportProps = {
    roles, productName: productLabel.name, price: productLabel.price, channelId: qt.channel_id ?? null, voiceless: !!qt.voiceless,
    dubJobId: qt.template_id === "dub" ? ((qt as { dub?: { job_id?: string } }).dub?.job_id ?? null)
      : qt.template_id === "dub_part" ? ((qt as { dub_part?: { job_id?: string } }).dub_part?.job_id ?? null) : null,
    dubPart: qt.template_id === "dub_part" ? ((qt as { dub_part?: { index: number; total: number } }).dub_part ?? null) : null,
    cutPart: qt.template_id === "cut_part" ? cutPartOf(qt, routeId) : null,
  };

  if (videoKind) {
    return (
      <>
        <header className="qt-header">
          <span className="qt-header__crumb">{boardName || videoKind}</span>
        </header>
        <div className="qt-project">
          <div className="qt-project__meta">
            <div className="qt-card__eyebrow">{videoKind}</div>
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" onClick={() => navigate("/clips")}>← Clip của tôi</button>
          </div>
          <div className="qt-project__actions">
            <button type="button" className="qt-btn qt-btn--ghost" onClick={rename}>Đổi tên</button>
            <button type="button" className={`qt-btn qt-btn--ghost${confirmDelete ? " qt-btn--danger" : ""}`} onClick={() => void removeClip()}>
              {confirmDelete ? "Bấm lần nữa để xoá" : "Xoá"}
            </button>
          </div>
        </div>
        <div className="qt-body qt-body--video">
          <main className="qt-main">
            <StepExport {...exportProps} videoOnly />
            <ClipPost boardId={routeId} productId={qt.product_id ?? null} channelId={qt.channel_id ?? null} />
          </main>
        </div>
      </>
    );
  }

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">{boardName || kindLabel}</span>
      </header>

      <div className="qt-project">
        <div className="qt-project__meta">
          <div className="qt-card__eyebrow">Clip · {kindLabel}</div>
          <select
            className="qt-project__select"
            value={routeId}
            onChange={(e) => navigate(`/clips/${e.target.value}`)}
            disabled={running}
          >
            {boards.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <div className="qt-project__actions">
          <button type="button" className="qt-btn qt-btn--ghost" onClick={rename} disabled={running}>Đổi tên</button>
          <button type="button" className={`qt-btn qt-btn--ghost${confirmDelete ? " qt-btn--danger" : ""}`} onClick={() => void removeClip()} disabled={running}>
            {confirmDelete ? "Bấm lần nữa để xoá" : "Xoá"}
          </button>
          {running ? (
            <button type="button" className="qt-btn qt-btn--danger" onClick={stopAuto}>■ Dừng tiến trình</button>
          ) : autoClip ? (
            <button type="button" className="qt-btn qt-btn--accent" onClick={startAuto} disabled={roles.scenes.length === 0}
                    title="Chạy hết: người mẫu → ảnh cảnh → video → lời thoại → ghép">
              ⚡ Tạo video tự động
            </button>
          ) : null}
        </div>
      </div>

      {(autoMessage || running) && (
        <div className={`qt-banner${running ? " qt-banner--busy" : ""}`}>
          {running && <span className="qt-spinner" />}
          {autoMessage ?? "Đang chạy…"}
        </div>
      )}

      <ol className="qt-stepper">
        {STEPS.map((s) => {
          const state = s.n === step ? "current" : stepDone(roles, s.n, isDrama) ? "done" : "todo";
          return (
            <li key={s.n} className={`qt-stepper__item qt-stepper__item--${state}`}>
              <button type="button" onClick={() => go(s.n)} disabled={running}>
                <span className="qt-stepper__num">{state === "done" ? "✓" : s.n}</span>
                <span className="qt-stepper__text"><small>Bước {s.n}</small>{stepTitles[s.n] ?? s.title}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="qt-body">
        <aside className="qt-locked">
          <div className="qt-card__eyebrow">Thông tin đã chốt</div>
          <div className="qt-locked__row"><span>Sản phẩm</span><strong>{roles.products.filter((p) => p.data.mediaId).length}/{roles.products.length} ảnh</strong></div>
          <div className="qt-locked__row"><span>Người mẫu</span><strong>{roles.model ? (roles.model.data.mediaId ? "đã có" : "chưa tạo") : qt.hands ? "chỉ bàn tay" : "không có"}</strong></div>
          <div className="qt-locked__row"><span>Cảnh</span><strong>{roles.scenes.filter((s) => s.image.data.mediaId).length}/{roles.scenes.length} ảnh</strong></div>
          {isDrama ? (
            <div className="qt-locked__row"><span>Thứ tự</span><strong>{(qt.sequence ?? []).length} mục</strong></div>
          ) : (
            <div className="qt-locked__row"><span>Video cảnh</span><strong>{roles.scenes.filter((s) => s.video?.data.mediaId).length}/{roles.scenes.length}</strong></div>
          )}
          <div className="qt-locked__row"><span>Clip cuối</span><strong>{roles.export?.data.mediaId ? "đã ghép" : "chưa"}</strong></div>
          {roles.products[0]?.data.mediaId && (
            <img className="qt-locked__thumb" src={mediaUrl(roles.products[0].data.mediaId as string)} alt="" />
          )}
        </aside>
        <main className="qt-main">
          {step === 1 && (
            <StepSetup
              key={routeId}
              productGender={productGender}
              roles={roles}
              sourceMediaId={(qt as { source_media_id?: string }).source_media_id ?? null}
              personRequired={!!template?.person_required || qt.reference?.category === "fashion"}
              hands={qt.hands ?? null}
              productId={qt.product_id ?? null}
              productName={productLabel.name || String(roles.products[0]?.data.title ?? "")}
            />
          )}
          {step === 2 && <StepScript roles={roles} category={clipCategory} productId={qt.product_id ?? null} boardId={routeId} voiceless={!!qt.voiceless} />}
          {step === 3 && <StepMedia roles={roles} kind="image" />}
          {step === 4 && (isDrama ? <StepSequence roles={roles} /> : <StepMedia roles={roles} kind="video" productName={productLabel.name} boardName={boardName} voiceless={!!qt.voiceless} />)}
          {step === 5 && <StepExport {...exportProps} />}
          {step === 1 && loaded && <ClipChannel boardId={routeId} channelId={qt.channel_id ?? null} />}
          {step === 5 && loaded && <ClipPost boardId={routeId} productId={qt.product_id ?? null} channelId={qt.channel_id ?? null} />}
          <div className="qt-footer">
            <button type="button" className="qt-btn qt-btn--ghost" disabled={running} onClick={() => (step <= 1 ? navigate("/clips") : go(step - 1))}>
              {step <= 1 ? "← Thư viện" : "← Quay lại"}
            </button>
            <button type="button" className="qt-btn" disabled={step >= 5 || running || (step === 4 && !isDrama && !roles.scenes.some((s) => hasMedia(s.video)))}
                    title={step === 4 && !isDrama && !roles.scenes.some((s) => hasMedia(s.video)) ? "Cần ít nhất một video để ghép" : undefined}
                    onClick={() => go(step + 1)}>Tiếp tục →</button>
          </div>
        </main>
      </div>
    </>
  );
}
