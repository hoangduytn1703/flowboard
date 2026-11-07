import { useEffect, useRef, useState } from "react";
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
import { DialogHost } from "./components/Dialogs";
import { AppUpdateBanner } from "./components/AppUpdate";
import { AppLoading } from "./components/AppLoading";
import { GenerationDialog } from "./components/GenerationDialog";
import { ResultViewer } from "./components/ResultViewer";
import { ForcedSetupGate } from "./components/ForcedSetupGate";
import { QuicktoolApp } from "./quicktool/QuicktoolApp";
import { useBoardStore } from "./store/board";
import { useReferencesStore } from "./store/references";
import { useSettingsStore } from "./store/settings";
import { getAccountMe, getAccountPrefs, type AccountMe } from "./api/account";
import { LoginPage } from "./components/LoginPage";
import { useAccountStore } from "./store/account";

/**
 * Routes:
 *   /clips, /clips/new, /clips/from-video, /products, /settings  → Quicktool
 *   /clips/:id/:step                                               → Quicktool wizard
 *   /canvas, /canvas/:id                                           → node canvas
 *   /                                                              → last used mode
 */
/**
 * Nothing loads before the login is known: the stores would hit 401 and
 * toast errors. Once logged in the rest of the app mounts; a 401 from any
 * later call (session expired, agent restarted) brings the login back.
 */
export function App() {
  const [state, setState] = useState<"checking" | "in" | "out">("checking");
  const setMe = useAccountStore((s) => s.setMe);

  useEffect(() => {
    let alive = true;
    getAccountMe()
      .then((me) => { if (alive) { setMe(me); setState("in"); } })
      .catch(() => { if (alive) setState("out"); });
    const onUnauthorized = () => { setMe(null); setState("out"); };
    window.addEventListener("flowboard:unauthorized", onUnauthorized);
    return () => { alive = false; window.removeEventListener("flowboard:unauthorized", onUnauthorized); };
  }, [setMe]);

  if (state === "checking") return <AppLoading />;
  if (state === "out") return <LoginPage onLoggedIn={(me: AccountMe) => { setMe(me); setState("in"); }} />;
  return <AppInner key={useAccountStore.getState().me?.username ?? "local"} />;
}

function AppInner() {
  const loadInitialBoard = useBoardStore((s) => s.loadInitialBoard);
  const loadReferences = useReferencesStore((s) => s.load);
  const loading = useBoardStore((s) => s.loading);
  const boardId = useBoardStore((s) => s.boardId);
  const uiMode = useSettingsStore((s) => s.uiMode);
  const ran = useRef(false);
  // The pages mount once, after the first board load: the store starts with loading=false, so the routes used to
  // mount, get swapped for <AppLoading> when the load began, and mount again — a page lost what it had just read
  // from its URL (?post=, ?assistant=, ?job=) and whatever was clicked in between (30/10).
  const [booted, setBooted] = useState(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    void loadInitialBoard().finally(() => setBooted(true));
    // Fire-and-forget: panel renders the loading state inline and the
    // app stays usable even if references fail to hydrate.
    void loadReferences();
    // Model picks etc. saved with the account (another machine's choices).
    if (useAccountStore.getState().me?.auth) {
      void getAccountPrefs().then((p) => useSettingsStore.getState().hydrateFromAccount(p)).catch(() => {});
    }
  }, [loadInitialBoard, loadReferences]);

  if (!booted || (loading && boardId === null)) {
    return <AppLoading />;
  }

  return (
    <>
      <Routes>
        <Route path="/" element={<Navigate to={uiMode === "canvas" ? "/canvas" : "/today"} replace />} />
        <Route path="/canvas/:id?" element={<CanvasApp />} />
        <Route path="/*" element={<QuicktoolApp />} />
      </Routes>
      <Toaster />
      <DialogHost />
      <AppUpdateBanner />
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
