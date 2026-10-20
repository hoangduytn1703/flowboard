import { useEffect, useRef } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { Board } from "./canvas/Board";
import { AddNodePalette } from "./canvas/AddNodePalette";
import { StatusBar } from "./components/StatusBar";
import { Toolbar } from "./components/Toolbar";
// import { ChatSidebar } from "./components/ChatSidebar";
import { ChatDock } from "./components/ChatDock";
import { ProjectSidebar } from "./components/ProjectSidebar";
import { ReferencesPanel } from "./components/ReferencesPanel";
import { Toaster } from "./components/Toaster";
import { AppLoading } from "./components/AppLoading";
import { GenerationDialog } from "./components/GenerationDialog";
import { ResultViewer } from "./components/ResultViewer";
import { ForcedSetupGate } from "./components/ForcedSetupGate";
import { QuicktoolApp } from "./quicktool/QuicktoolApp";
import { useBoardStore } from "./store/board";
import { useReferencesStore } from "./store/references";
import { useSettingsStore } from "./store/settings";

/**
 * Routes:
 *   /clips, /clips/new, /clips/from-video, /products, /settings  → Quicktool
 *   /clips/:id/:step                                               → Quicktool wizard
 *   /canvas, /canvas/:id                                           → node canvas
 *   /                                                              → last used mode
 */
export function App() {
  const loadInitialBoard = useBoardStore((s) => s.loadInitialBoard);
  const loadReferences = useReferencesStore((s) => s.load);
  const loading = useBoardStore((s) => s.loading);
  const boardId = useBoardStore((s) => s.boardId);
  const uiMode = useSettingsStore((s) => s.uiMode);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    loadInitialBoard();
    // Fire-and-forget: panel renders the loading state inline and the
    // app stays usable even if references fail to hydrate.
    void loadReferences();
  }, [loadInitialBoard, loadReferences]);

  if (loading && boardId === null) {
    return <AppLoading />;
  }

  return (
    <>
      <Routes>
        <Route path="/" element={<Navigate to={uiMode === "canvas" ? "/canvas" : "/clips"} replace />} />
        <Route path="/canvas/:id?" element={<CanvasApp />} />
        <Route path="/*" element={<QuicktoolApp />} />
      </Routes>
      <Toaster />
      <GenerationDialog />
      <ResultViewer />
      <ForcedSetupGate />
    </>
  );
}

/** The node canvas — the advanced view of the same board. `/canvas/:id`
 * switches to that board and settles on `/canvas`, so the project sidebar
 * keeps driving the board without the URL going stale. */
function CanvasApp() {
  const { id } = useParams();
  const navigate = useNavigate();
  const boardId = useBoardStore((s) => s.boardId);
  const switchBoard = useBoardStore((s) => s.switchBoard);
  const setUiMode = useSettingsStore((s) => s.setUiMode);

  useEffect(() => {
    setUiMode("canvas");
  }, [setUiMode]);

  useEffect(() => {
    if (id === undefined) return;
    const target = Number(id);
    if (!isNaN(target) && target !== boardId) void switchBoard(target);
    navigate("/canvas", { replace: true });
  }, [id, boardId, switchBoard, navigate]);

  return (
    <div className="app">
      <ProjectSidebar />
      <ReactFlowProvider>
        <div className="canvas-wrap">
          <Toolbar />
          <Board />
          <AddNodePalette />
          <StatusBar />
          <ReferencesPanel />
        </div>
      </ReactFlowProvider>
      {/* <ChatSidebar /> */}
      <ChatDock />
    </div>
  );
}
