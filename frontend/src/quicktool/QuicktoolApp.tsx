import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  exportsZipUrl,
  getTemplates,
  listBoardSummaries,
  mediaUrl,
  type BoardSummary,
  type BoardTemplate,
  type QuicktoolState,
  getProduct,
  type ProductGender,
} from "../api/client";
import { ProductsPanel } from "../components/ProductsPanel";
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
import { PromptsPage } from "./pages/PromptsPage";
import { PostsPage } from "./pages/PostsPage";
import { ChannelsPage } from "./pages/ChannelsPage";
import { DubPage } from "./pages/DubPage";
import { ClipChannel } from "./steps/ClipChannel";
import { ClipPost } from "./steps/ClipPost";
import { SchedulePage } from "./pages/SchedulePage";
import { SwipesPage } from "./pages/SwipesPage";
import { useFlowCredits } from "../components/credits";
import { AccountSwitchBanner } from "../components/AccountSwitchBanner";
import { useToastOn } from "../store/toast";
import { PageEmpty, PageLoading } from "./PageState";

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
    document.title = `${title} · Flowboard`;
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
  const [templates, setTemplates] = useState<BoardTemplate[]>([]);

  useEffect(() => {
    setUiMode("quicktool");
    getTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [setUiMode]);

  return (
    <div className="qt-app">
      <QuicktoolSidebar />
      <div className="qt-content">
        <AccountSwitchBanner />
        <Routes>
          {/* Static paths first so "new" / "from-video" are never read as a clip id. */}
          <Route path="/clips" element={<Library templates={templates} />} />
          <Route path="/clips/new" element={<Library templates={templates} />} />
          <Route path="/clips/from-video" element={<Library templates={templates} />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/today" element={<TodayPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/prompts" element={<PromptsPage />} />
          <Route path="/tools/clean" element={<CleanToolPage />} />
          <Route path="/posts" element={<PostsPage />} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/schedule" element={<SchedulePage />} />
          <Route path="/swipes" element={<SwipesPage />} />
          <Route path="/tools/dub" element={<DubPage />} />
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
function Library({ templates }: { templates: BoardTemplate[] }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const boardId = useBoardStore((s) => s.boardId);
  const boards = useBoardStore((s) => s.boards);
  const [summaries, setSummaries] = useState<BoardSummary[] | null>(null);
  const [picked, setPicked] = useState<Set<number>>(() => new Set());
  const queue = useQuicktoolStore((s) => s.queue);
  const runQueue = useQuicktoolStore((s) => s.runQueue);
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

  const list = (summaries ?? []).slice().reverse();
  // Clips that still have something to make: what "run all" would pick.
  const unfinished = list.filter((b) => !b.summary.exported);
  const pickedList = list.filter((b) => picked.has(b.id));
  const perClip = creditsPerClip(videoModel, videoQuality);

  function togglePick(id: number) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function startQueue(targets: BoardSummary[]) {
    if (targets.length === 0 || queue.running) return;
    const videos = targets.reduce((t, b) => t + Math.max(b.summary.clips - b.summary.clips_done, 0), 0);
    const images = targets.reduce((t, b) => t + Math.max(b.summary.scenes - b.summary.scenes_done, 0), 0);
    const cost = videos * perClip;
    const balance = flowCredits === null ? "" : ` Tài khoản còn ${flowCredits.toLocaleString("vi-VN")} credit${cost > flowCredits ? " — KHÔNG ĐỦ cho cả hàng đợi" : ""}.`;
    const ok = window.confirm(
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
            <h3 className="qt-card__title">Clip của tôi{summaries ? ` · ${summaries.length}` : ""}</h3>
          </div>
          <div className="qt-row">
            {queue.running ? (
              <button type="button" className="qt-btn qt-btn--danger" onClick={stopQueue}>■ Dừng hàng đợi</button>
            ) : pickedList.length > 0 ? (
              <>
                {pickedList.some((b) => b.summary.exported) && (
                  <a className="qt-btn" href={exportsZipUrl(pickedList.filter((b) => b.summary.exported).map((b) => b.id))}
                     title="Một file .zip chứa các clip đã ghép, tên file theo sản phẩm + ngày">
                    ⬇ Tải {pickedList.filter((b) => b.summary.exported).length} clip đã ghép
                  </a>
                )}
                <button type="button" className="qt-btn qt-btn--accent" onClick={() => startQueue(pickedList)}>
                  ⚡ Chạy {pickedList.length} clip đã chọn
                </button>
                <button type="button" className="qt-btn qt-btn--ghost" onClick={() => setPicked(new Set())}>Bỏ chọn</button>
              </>
            ) : (
              <>
                {unfinished.length > 1 && (
                  <button type="button" className="qt-btn qt-btn--ghost" onClick={() => startQueue(unfinished)}
                          title="Chạy tự động mọi clip chưa ghép xong, lần lượt từng clip">
                    ⚡ Chạy tất cả {unfinished.length} clip dở
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
        {summaries !== null && summaries.length === 0 && (
          <PageEmpty icon="🎬" title="Chưa có clip nào"
                     actions={<>
                       <button type="button" className="qt-btn qt-btn--accent qt-btn--big" onClick={() => navigate("/clips/new")}>+ Tạo clip đầu tiên</button>
                       <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate("/products")}>Thêm sản phẩm trước</button>
                     </>}>
            Bấm <strong>+ Clip mới</strong>, chọn kiểu clip và dán ảnh sản phẩm — AI viết kịch bản, tạo ảnh, tạo video và ghép lại có giọng đọc tiếng Việt.
          </PageEmpty>
        )}
        <div className="qt-home__grid">
          {summaries === null && Array.from({ length: 6 }, (_, i) => (
            <div key={`sk-${i}`} className="qt-clip qt-clip--skeleton" aria-hidden="true">
              <span className="qt-clip__thumb qt-skeleton" />
              <span className="qt-skeleton qt-skeleton--line" />
              <span className="qt-skeleton qt-skeleton--line qt-skeleton--short" />
            </div>
          ))}
          {summaries !== null && summaries.length > 0 && (
            <button type="button" className="qt-clip qt-clip--new" onClick={() => navigate("/clips/new")}>
              <span className="qt-clip__plus">+</span>
              <span>Clip mới</span>
            </button>
          )}
          {list.map((b) => {
            const st = cardState(b.id);
            const pickable = !queue.running && !b.summary.exported;
            return (
              <div key={b.id} className={`qt-clip${b.id === boardId ? " qt-clip--active" : ""}${picked.has(b.id) ? " qt-clip--picked" : ""}${st ? ` qt-clip--${st.tone}` : ""}`}>
                {pickable && (
                  <label className="qt-clip__pick" title="Chọn để chạy tự động nhiều clip" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={picked.has(b.id)} onChange={() => togglePick(b.id)} />
                  </label>
                )}
                <button type="button" className="qt-clip__open" disabled={queue.running && queue.current !== b.id}
                        onClick={() => navigate(`/clips/${b.id}`)}>
                  {b.summary.thumbnail ? (
                    <img className="qt-clip__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" />
                  ) : (
                    <span className="qt-clip__thumb qt-clip__thumb--empty">🎬</span>
                  )}
                  <span className="qt-clip__name">{b.name}</span>
                  <span className="qt-clip__meta">
                    {b.summary.scenes_done}/{b.summary.scenes} ảnh · {b.summary.clips_done}/{b.summary.clips} video
                  </span>
                  <span className={`qt-clip__state qt-clip__state--${st ? st.tone : b.summary.exported ? "done" : "idle"}`}>
                    {st ? st.label : b.summary.exported ? "✓ đã ghép xong" : "chưa ghép"}
                  </span>
                </button>
              </div>
            );
          })}
        </div>
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
  useTitle(loaded && boardName ? `${boardName} · Bước ${step ?? qt.step ?? 1}` : "Đang mở clip…");

  /** The auto run, after saying what it will spend. */
  function startAuto() {
    const images = roles.scenes.filter((s) => !hasMedia(s.image)).length + (roles.model && !hasMedia(roles.model) ? 1 : 0);
    const videos = isDrama ? 0 : roles.scenes.filter((s) => s.video && !hasMedia(s.video)).length;
    const cost = videos * creditsPerClip(videoModel, videoQuality);
    const parts = [images ? `${images} ảnh` : "", videos ? `${videos} video (~${cost} credit Flow)` : ""].filter(Boolean);
    const what = parts.length ? `Sẽ tạo ${parts.join(" + ")}, rồi viết lời thoại và ghép clip.` : "Mọi cảnh đã có — chỉ viết lời thoại và ghép clip.";
    // Stills two at a time (~30 s), clips three at a time (~1–2 min a wave), then the join
    // (measured 26/10: 5 stills + 4 clips + export in ~4.5 min).
    const mins = Math.max(1, Math.round(Math.ceil(images / 2) * 0.5 + Math.ceil(videos / 3) * 1.2 + 1.5));
    const balance = flowCredits === null ? "" : `\nTài khoản Flow còn ${flowCredits.toLocaleString("vi-VN")} credit${cost > flowCredits ? " — KHÔNG ĐỦ, clip sẽ hỏng giữa chừng" : ""}.`;
    if (!window.confirm(`${what}${balance}\nKhoảng ${mins} phút. Tiếp tục?`)) return;
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
  const refreshedFor = useRef<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => {
    if (isNaN(routeId) || routeId === boardId || !boardsLoaded || refreshing) return;
    if (boards.some((b) => b.id === routeId)) { void switchBoard(routeId); return; }
    if (loadingBoard) return;
    if (refreshedFor.current !== routeId) {
      refreshedFor.current = routeId;
      setRefreshing(true);
      void refreshBoards()
        .catch(() => navigate("/clips", { replace: true }))
        .finally(() => setRefreshing(false));
      return;
    }
    navigate("/clips", { replace: true });
  }, [routeId, boardId, boards, boardsLoaded, loadingBoard, refreshing, switchBoard, refreshBoards, navigate]);

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

  function rename() {
    const next = window.prompt("Tên clip", boardName);
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

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Công cụ nhanh · {kindLabel}</span>
      </header>

      <div className="qt-project">
        <div className="qt-project__meta">
          <div className="qt-card__eyebrow">Dự án · {kindLabel}</div>
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
          <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate(`/clips/new${qt.template_id && qt.template_id !== "reference_video" && qt.template_id !== "product_link" ? `?template=${qt.template_id}` : ""}`)}>+ Clip mới</button>
          <button type="button" className="qt-btn qt-btn--ghost" onClick={rename} disabled={running}>Đổi tên</button>
          <button type="button" className={`qt-btn qt-btn--ghost${confirmDelete ? " qt-btn--danger" : ""}`} onClick={() => void removeClip()} disabled={running}>
            {confirmDelete ? "Bấm lần nữa để xoá" : "Xoá"}
          </button>
          {running ? (
            <button type="button" className="qt-btn qt-btn--danger" onClick={stopAuto}>■ Dừng tiến trình</button>
          ) : (
            <button type="button" className="qt-btn qt-btn--accent" onClick={startAuto} disabled={roles.scenes.length === 0}
                    title="Chạy hết: người mẫu → ảnh cảnh → video → lời thoại → ghép">
              ⚡ Tạo video tự động
            </button>
          )}
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
            <div className="qt-locked__row"><span>Video</span><strong>{roles.scenes.filter((s) => s.video?.data.mediaId).length}/{roles.scenes.length} clip</strong></div>
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
          {step === 2 && <StepScript roles={roles} category={clipCategory} productId={qt.product_id ?? null} boardId={routeId} />}
          {step === 3 && <StepMedia roles={roles} kind="image" />}
          {step === 4 && (isDrama ? <StepSequence roles={roles} /> : <StepMedia roles={roles} kind="video" productName={productLabel.name} boardName={boardName} />)}
          {step === 5 && <StepExport roles={roles} productName={productLabel.name} price={productLabel.price} channelId={qt.channel_id ?? null} />}
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
