import { useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  getTemplates,
  listBoardSummaries,
  mediaUrl,
  type BoardSummary,
  type BoardTemplate,
  type QuicktoolState,
} from "../api/client";
import { ProductsPanel } from "../components/ProductsPanel";
import { SettingsPanel } from "../components/SettingsPanel";
import { useBoardStore } from "../store/board";
import { useQuicktoolStore } from "../store/quicktool";
import { useSettingsStore } from "../store/settings";
import { NewClipDialog, REFERENCE_KIND } from "./NewClipDialog";
import { QuicktoolSidebar } from "./QuicktoolSidebar";
import { deriveRoles, furthestStep } from "./roles";
import { StepExport } from "./steps/StepExport";
import { StepMedia } from "./steps/StepMedia";
import { StepScript } from "./steps/StepScript";
import { StepSetup } from "./steps/StepSetup";

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

/**
 * The step-by-step clip maker: pick a product and a template, review the
 * script, render the scenes, render the clips, join them with a voice-over.
 * Everything acts on the ordinary board underneath (see `quicktool/roles`),
 * so the canvas stays available as the advanced view of the same clip.
 *
 * Pages have their own URLs: /clips (library), /clips/new,
 * /clips/from-video, /products and /settings open over the library;
 * /clips/:id/:step is the wizard.
 */
export function QuicktoolApp() {
  const boardId = useBoardStore((s) => s.boardId);
  const boards = useBoardStore((s) => s.boards);
  const setUiMode = useSettingsStore((s) => s.setUiMode);
  const [templates, setTemplates] = useState<BoardTemplate[]>([]);
  const qt = (boards.find((b) => b.id === boardId)?.data?.quicktool ?? {}) as QuicktoolState;

  useEffect(() => {
    setUiMode("quicktool");
    getTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [setUiMode]);

  return (
    <div className="qt-app">
      <QuicktoolSidebar templates={templates} activeTemplateId={qt.template_id ?? null} />
      <div className="qt-content">
        <Routes>
          {/* Static paths first so "new" / "from-video" are never read as a clip id. */}
          <Route path="/clips" element={<Library templates={templates} />} />
          <Route path="/clips/new" element={<Library templates={templates} />} />
          <Route path="/clips/from-video" element={<Library templates={templates} />} />
          <Route path="/products" element={<Library templates={templates} />} />
          <Route path="/settings" element={<Library templates={templates} />} />
          <Route path="/clips/:id/:step" element={<Wizard templates={templates} />} />
          <Route path="/clips/:id" element={<Wizard templates={templates} />} />
          <Route path="*" element={<Navigate to="/clips" replace />} />
        </Routes>
      </div>
    </div>
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

  useEffect(() => {
    listBoardSummaries().then(setSummaries).catch(() => setSummaries([]));
  }, [boards.length, pathname]);

  const dialog = pathname === "/clips/new" ? "new"
    : pathname === "/clips/from-video" ? "reference"
    : pathname === "/products" ? "products"
    : pathname === "/settings" ? "settings"
    : null;
  const productParam = params.get("product");

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Clip của tôi</span>
      </header>
      <div className="qt-home">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Thư viện</div>
            <h3 className="qt-card__title">Clip của tôi</h3>
          </div>
          <div className="qt-row">
            <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate("/clips/from-video")}>🎞️ Từ video mẫu</button>
            <button type="button" className="qt-btn qt-btn--accent" onClick={() => navigate("/clips/new")}>+ Clip mới</button>
          </div>
        </div>
        <div className="qt-home__grid">
          <button type="button" className="qt-clip qt-clip--new" onClick={() => navigate("/clips/new")}>
            <span className="qt-clip__plus">+</span>
            <span>Clip mới</span>
          </button>
          {summaries === null && <div className="qt-empty">Đang tải…</div>}
          {(summaries ?? []).slice().reverse().map((b) => (
            <button key={b.id} type="button" className={`qt-clip${b.id === boardId ? " qt-clip--active" : ""}`} onClick={() => navigate(`/clips/${b.id}`)}>
              {b.summary.thumbnail ? (
                <img className="qt-clip__thumb" src={mediaUrl(b.summary.thumbnail)} alt="" />
              ) : (
                <span className="qt-clip__thumb qt-clip__thumb--empty">🎬</span>
              )}
              <span className="qt-clip__name">{b.name}</span>
              <span className="qt-clip__meta">
                {b.summary.scenes_done}/{b.summary.scenes} ảnh · {b.summary.clips_done}/{b.summary.clips} video
                {b.summary.exported ? " · ✓ đã ghép" : ""}
              </span>
            </button>
          ))}
        </div>
      </div>

      {(dialog === "new" || dialog === "reference") && (
        <NewClipDialog
          templates={templates}
          initialTemplateId={dialog === "reference" ? REFERENCE_KIND : params.get("template")}
          initialProductId={productParam ? Number(productParam) : null}
          onClose={() => navigate("/clips")}
          onCreated={(id) => navigate(`/clips/${id}/setup`)}
        />
      )}
      {dialog === "products" && (
        <ProductsPanel
          onClose={() => navigate("/clips")}
          onMakeClip={(p) => navigate(`/clips/new?product=${p.id}${p.template_id ? `&template=${p.template_id}` : ""}`)}
        />
      )}
      <SettingsPanel open={dialog === "settings"} onClose={() => navigate("/clips")} logoutPending={false} />
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
  const runAuto = useQuicktoolStore((s) => s.runAuto);
  const stopAuto = useQuicktoolStore((s) => s.stopAuto);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const loaded = !isNaN(routeId) && boardId === routeId;
  const roles = useMemo(() => deriveRoles(loaded ? nodes : [], loaded ? edges : []), [loaded, nodes, edges]);
  const reached = furthestStep(roles);
  const running = auto !== "idle" && auto !== "done" && auto !== "stopped" && auto !== "failed";
  const qt = (boards.find((b) => b.id === routeId)?.data?.quicktool ?? {}) as QuicktoolState;
  const template = templates.find((t) => t.id === qt.template_id) ?? null;
  const kindLabel = template?.title ?? (qt.template_id === "reference_video" ? "Theo video mẫu" : "Clip");
  const step = stepOf(stepSlug);

  // URL → board: a deep link or the back button loads the board it names.
  useEffect(() => {
    if (isNaN(routeId)) return;
    if (routeId !== boardId) void switchBoard(routeId);
  }, [routeId, boardId, switchBoard]);

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
  // The auto run ends on the export step.
  useEffect(() => {
    if (auto === "done" && step !== 5 && loaded) navigate(`/clips/${routeId}/export`);
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
        <div className="qt-home"><div className="qt-empty">Đang tải board #{routeId}…</div></div>
      </>
    );
  }

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Công cụ nhanh · {kindLabel}</span>
        <span className="qt-header__name">{boardName}</span>
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
          <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate(`/clips/new${qt.template_id && qt.template_id !== "reference_video" ? `?template=${qt.template_id}` : ""}`)}>+ Clip mới</button>
          <button type="button" className="qt-btn qt-btn--ghost" onClick={rename} disabled={running}>Đổi tên</button>
          <button type="button" className={`qt-btn qt-btn--ghost${confirmDelete ? " qt-btn--danger" : ""}`} onClick={() => void removeClip()} disabled={running}>
            {confirmDelete ? "Bấm lần nữa để xoá" : "Xoá"}
          </button>
          {running ? (
            <button type="button" className="qt-btn qt-btn--danger" onClick={stopAuto}>■ Dừng tiến trình</button>
          ) : (
            <button type="button" className="qt-btn qt-btn--accent" onClick={() => void runAuto()} disabled={roles.scenes.length === 0}
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
      {error && (
        <div className="qt-banner qt-banner--error" role="alert">
          {error}
          <button type="button" className="qt-link" onClick={clearError}>đóng</button>
        </div>
      )}

      <ol className="qt-stepper">
        {STEPS.map((s) => {
          const state = s.n === step ? "current" : s.n < reached ? "done" : "todo";
          return (
            <li key={s.n} className={`qt-stepper__item qt-stepper__item--${state}`}>
              <button type="button" onClick={() => go(s.n)} disabled={running}>
                <span className="qt-stepper__num">{state === "done" ? "✓" : s.n}</span>
                <span className="qt-stepper__text"><small>Bước {s.n}</small>{s.title}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="qt-body">
        <aside className="qt-locked">
          <div className="qt-card__eyebrow">Input · đã chốt</div>
          <div className="qt-locked__row"><span>Sản phẩm</span><strong>{roles.products.filter((p) => p.data.mediaId).length}/{roles.products.length} ảnh</strong></div>
          <div className="qt-locked__row"><span>Người mẫu</span><strong>{roles.model ? (roles.model.data.mediaId ? "đã có" : "chưa tạo") : "—"}</strong></div>
          <div className="qt-locked__row"><span>Cảnh</span><strong>{roles.scenes.filter((s) => s.image.data.mediaId).length}/{roles.scenes.length} ảnh</strong></div>
          <div className="qt-locked__row"><span>Video</span><strong>{roles.scenes.filter((s) => s.video?.data.mediaId).length}/{roles.scenes.length} clip</strong></div>
          <div className="qt-locked__row"><span>Clip cuối</span><strong>{roles.export?.data.mediaId ? "đã ghép" : "chưa"}</strong></div>
          {roles.products[0]?.data.mediaId && (
            <img className="qt-locked__thumb" src={mediaUrl(roles.products[0].data.mediaId as string)} alt="" />
          )}
        </aside>
        <main className="qt-main">
          {step === 1 && <StepSetup roles={roles} sourceMediaId={(qt as { source_media_id?: string }).source_media_id ?? null} />}
          {step === 2 && <StepScript roles={roles} />}
          {step === 3 && <StepMedia roles={roles} kind="image" />}
          {step === 4 && <StepMedia roles={roles} kind="video" />}
          {step === 5 && <StepExport roles={roles} />}
          <div className="qt-footer">
            <button type="button" className="qt-btn qt-btn--ghost" disabled={step <= 1 || running} onClick={() => go(step - 1)}>← Quay lại</button>
            <button type="button" className="qt-btn" disabled={step >= 5 || running} onClick={() => go(step + 1)}>Tiếp tục →</button>
          </div>
        </main>
      </div>
    </>
  );
}
