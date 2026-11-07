/**
 * The desktop app (Tauri) around this web UI: its own commands, reached through the IPC bridge Tauri injects
 * into the page (desktop/src-tauri/capabilities/ui.json lets http://127.0.0.1:8434 call them). In a normal
 * browser there is no bridge and every helper says so.
 */
interface TauriInternals {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
}

function bridge(): TauriInternals | null {
  const t = (window as unknown as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
  return t && typeof t.invoke === "function" ? t : null;
}

/** Running inside DFlow.exe (not a browser tab). */
export function inDesktopApp(): boolean {
  return bridge() !== null;
}

export interface AppUpdate {
  /** the version running */
  current: string;
  /** the newer version published, null = up to date */
  version: string | null;
  notes: string | null;
}

/** The newest version published on the public releases repo (null outside the app). */
export async function checkAppUpdate(): Promise<AppUpdate | null> {
  const t = bridge();
  if (!t) return null;
  return (await t.invoke("dflow_check_update")) as AppUpdate;
}

/** Download the new version, then the app closes, installs it and opens again (data and login stay). */
export async function installAppUpdate(): Promise<void> {
  const t = bridge();
  if (!t) throw new Error("Chỉ cập nhật được trong app DFlow");
  await t.invoke("dflow_install_update");
}
