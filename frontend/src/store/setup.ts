import { create } from "zustand";
import { checkSetup, getSetup, type CheckOptions, type SetupStatus } from "../api/setup";
import { toast } from "./toast";

/**
 * Is DFlow ready to ask Flow for a picture? One place answers it: the guide on "Hôm nay", the pill in the sidebar and
 * the check in front of every generation (`ensureReady`) — which opens the guide instead of letting the click fail.
 */
interface SetupState {
  status: SetupStatus | null;
  busy: boolean;
  /** the guide dialog; `reason` says what the seller was trying to do */
  guideOpen: boolean;
  reason: string;
  refresh(): Promise<SetupStatus | null>;
  /** look at the Flow tab again (the agent may pin the open project / plan); `true` = use the tab's open project */
  check(opts?: CheckOptions | boolean): Promise<SetupStatus | null>;
  openGuide(reason?: string): void;
  closeGuide(): void;
  /** true when a generation can start; otherwise opens the guide and answers false */
  ensureReady(reason?: string): Promise<boolean>;
}

/** A status read less than this long ago and saying "ready" is trusted without asking again. */
const FRESH_MS = 20_000;
let readAt = 0;

export const useSetupStore = create<SetupState>((set, get) => ({
  status: null,
  busy: false,
  guideOpen: false,
  reason: "",
  async refresh() {
    try {
      const status = await getSetup();
      readAt = Date.now();
      set({ status });
      return status;
    } catch {
      return get().status;
    }
  },
  async check(opts = {}) {
    if (get().busy) return get().status;
    set({ busy: true });
    try {
      const status = await checkSetup(typeof opts === "boolean" ? { useTabProject: opts } : opts);
      readAt = Date.now();
      set({ status });
      if (status.changed?.length) toast.success(`Đã tự chọn: ${status.changed.join(", ")}`);
      return status;
    } catch {
      return get().status;
    } finally {
      set({ busy: false });
    }
  },
  openGuide(reason = "") {
    set({ guideOpen: true, reason });
    void get().check();
  },
  closeGuide() {
    set({ guideOpen: false, reason: "" });
  },
  async ensureReady(reason = "") {
    const known = get().status;
    if (known?.can_generate && Date.now() - readAt < FRESH_MS) return true;
    let status = await get().refresh();
    // not ready by the cheap answer: the Flow tab may have changed since it was last read — look once
    if (status && !status.can_generate && status.flow.connected) status = await get().check();
    if (!status || status.can_generate) return true; // agent not answering: let the real call say why
    set({ guideOpen: true, reason });
    return false;
  },
}));
