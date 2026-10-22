import { create } from "zustand";

/**
 * Per-user model preferences. Survives page reload via localStorage —
 * single-user, single-host app, so no need for server persistence.
 *
 * Image model: Flow ships two checkpoints — "NANO_BANANA_PRO" (premium,
 * higher quality, slower) and "NANO_BANANA_2" (faster, lighter). Users
 * pick once in the dashboard Settings panel; every gen_image / edit_image
 * dispatch reads the cached preference and forwards it to the worker.
 *
 * Video model is currently derived from paygate tier + aspect (resolved
 * server-side via VIDEO_MODEL_KEYS), so it's a *display* on the panel
 * rather than a switchable preference. When/if Flow ships variants per
 * tier (e.g. fast vs quality) we extend this store with `videoModelKey`.
 */
export type ImageModelKey = "NANO_BANANA_PRO" | "NANO_BANANA_2";
// Veo 3.1 ships in four flavours:
//   - Lite (smaller checkpoint, fastest, lower fidelity)
//   - Fast (default — bigger model, balanced)
//   - Quality (highest fidelity, slowest)
//   - Lite Relaxed (Lite on a low-priority queue, 0 credits — Ultra only)
// Choice applies globally across both portrait and landscape; backend
// resolves the actual model key at dispatch time from [tier][quality][aspect].
// Tier 1 (Pro) users picking `lite_relaxed` fall back to Fast on the
// backend (and the Settings UI locks that radio for them).
export type VideoQuality =
  | "fast"
  | "lite"
  | "quality"
  | "lite_relaxed";

// Video model family. "veo" = the existing Veo 3.1 i2v family controlled
// by videoQuality (lite/fast/quality/...). "omni_flash" = the new
// reference-image r2v model with per-duration credit cost and no
// per-tier quality variants — duration is picked per dispatch in the
// GenerationDialog. The video dispatch path branches on this.
export type VideoModelFamily = "veo" | "omni_flash";

// Omni Flash duration → credit cost (informational, surfaced in the
// dialog so the user sees the cost before submit). Mirrors the backend
// OMNI_FLASH_CREDIT_COST table — pin both via tests.
export const OMNI_FLASH_CREDIT_COST: Record<4 | 6 | 8 | 10, number> = {
  4: 15,
  6: 20,
  8: 25,
  10: 30,
};
export type OmniFlashDuration = 4 | 6 | 8 | 10;
export const OMNI_FLASH_DURATIONS: OmniFlashDuration[] = [4, 6, 8, 10];

// Generation backend. "flow" = the existing Chrome-extension → Google
// Flow path. "muse" = delegated to a Pax worker via the provider-job
// queue (no Flow plan, no extension needed). Picked per dispatch in the
// GenerationDialog and sticky — persisted here like the model picks.
export type MediaProviderKey = "flow" | "muse";
// Image renderer for `gen_image`. "flow" = Flow credits via the extension
// (default). "openai" / "xai" = a paid API keyed in Settings → "Nguồn tạo
// ảnh"; the result is still uploaded into the Flow project so the video
// step can use it. Sent per image dispatch as `params.image_provider`.
export type ImageProviderKey = "flow" | "openai" | "xai";
// "quicktool" is the step-by-step clip maker (the default screen);
// "canvas" is the node board underneath it, for fine control.
export type UiMode = "quicktool" | "canvas";

interface SettingsState {
  imageModel: ImageModelKey;
  videoQuality: VideoQuality;
  videoModel: VideoModelFamily;
  omniFlashDuration: OmniFlashDuration;
  mediaProvider: MediaProviderKey;
  imageProvider: ImageProviderKey;
  uiMode: UiMode;
  hydrateFromAccount(prefs: Record<string, string | number | boolean>): void;
  setImageModel(model: ImageModelKey): void;
  setImageProvider(p: ImageProviderKey): void;
  setUiMode(mode: UiMode): void;
  setVideoQuality(q: VideoQuality): void;
  setVideoModel(m: VideoModelFamily): void;
  setOmniFlashDuration(d: OmniFlashDuration): void;
  setMediaProvider(p: MediaProviderKey): void;
}

const STORAGE_KEY = "flowboard.settings.v1";

interface PersistShape {
  // Bumped when a default changes in a way a stored value should follow.
  // 2: Omni Flash became the default video model — a stored "veo" from
  // before that is the old default, not a choice, so it is dropped once.
  v?: number;
  imageModel?: ImageModelKey;
  videoQuality?: VideoQuality;
  videoModel?: VideoModelFamily;
  omniFlashDuration?: OmniFlashDuration;
  mediaProvider?: MediaProviderKey;
  imageProvider?: ImageProviderKey;
  uiMode?: UiMode;
}

const PERSIST_VERSION = 2;

function loadPersisted(): PersistShape {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return {};
    if ((parsed.v ?? 1) < 2) {
      delete parsed.videoModel;
      delete parsed.omniFlashDuration;
    }
    return parsed;
  } catch {
    return {};
  }
}

// The account's copy on the agent (AppSetting `ui_prefs`, so the picks
// follow the login to another machine). localStorage stays as the instant
// cache; the server write is debounced and fire-and-forget.
let serverSync = false;
let saveTimer: ReturnType<typeof setTimeout> | null = null;

function persist(state: PersistShape): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage disabled / quota — non-fatal, just lose persistence.
  }
  if (!serverSync) return;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    const { v: _v, ...prefs } = state;
    void import("../api/account").then(({ putAccountPrefs }) => putAccountPrefs(prefs as Record<string, string | number>)).catch(() => {});
  }, 400);
}

const persisted = loadPersisted();

const VALID_VIDEO_QUALITIES: VideoQuality[] = ["fast", "lite", "quality", "lite_relaxed"];
const VALID_MEDIA_PROVIDERS: MediaProviderKey[] = ["flow", "muse"];
const VALID_IMAGE_PROVIDERS: ImageProviderKey[] = ["flow", "openai", "xai"];

function snapshotPersist(get: () => SettingsState): PersistShape {
  return {
    v: PERSIST_VERSION,
    imageModel: get().imageModel,
    videoQuality: get().videoQuality,
    videoModel: get().videoModel,
    omniFlashDuration: get().omniFlashDuration,
    mediaProvider: get().mediaProvider,
    imageProvider: get().imageProvider,
    uiMode: get().uiMode,
  };
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  // Pro, not 2: on 2026-10-11 Flow answered every NANO_BANANA_2 (NARWHAL)
  // image request on a Pro account with [5] NOT_FOUND, while GEM_PIX_2 rendered.
  imageModel: persisted.imageModel ?? "NANO_BANANA_PRO",
  videoQuality:
    persisted.videoQuality && VALID_VIDEO_QUALITIES.includes(persisted.videoQuality)
      ? persisted.videoQuality
      : "fast",
  // Omni Flash, not Veo: since mid-October 2026 Veo 3.1 Lite is accepted
  // and then dropped on ordinary Pro accounts (BUGLOG FB-025), while Omni
  // Flash renders. 8 s matches the templates' three-beat motion prompts.
  videoModel: persisted.videoModel ?? "omni_flash",
  omniFlashDuration: persisted.omniFlashDuration ?? 8,
  mediaProvider:
    persisted.mediaProvider && VALID_MEDIA_PROVIDERS.includes(persisted.mediaProvider)
      ? persisted.mediaProvider
      : "flow",
  imageProvider:
    persisted.imageProvider && VALID_IMAGE_PROVIDERS.includes(persisted.imageProvider)
      ? persisted.imageProvider
      : "flow",
  uiMode: persisted.uiMode === "canvas" ? "canvas" : "quicktool",
  /** Apply the preferences saved with the account (called once after login). */
  hydrateFromAccount(prefs) {
    const next: Partial<SettingsState> = {};
    if (prefs.imageModel === "NANO_BANANA_PRO" || prefs.imageModel === "NANO_BANANA_2") next.imageModel = prefs.imageModel;
    if (VALID_VIDEO_QUALITIES.includes(prefs.videoQuality as VideoQuality)) next.videoQuality = prefs.videoQuality as VideoQuality;
    if (prefs.videoModel === "veo" || prefs.videoModel === "omni_flash") next.videoModel = prefs.videoModel;
    if (OMNI_FLASH_DURATIONS.includes(prefs.omniFlashDuration as OmniFlashDuration)) next.omniFlashDuration = prefs.omniFlashDuration as OmniFlashDuration;
    if (VALID_MEDIA_PROVIDERS.includes(prefs.mediaProvider as MediaProviderKey)) next.mediaProvider = prefs.mediaProvider as MediaProviderKey;
    if (VALID_IMAGE_PROVIDERS.includes(prefs.imageProvider as ImageProviderKey)) next.imageProvider = prefs.imageProvider as ImageProviderKey;
    if (prefs.uiMode === "canvas" || prefs.uiMode === "quicktool") next.uiMode = prefs.uiMode;
    serverSync = true;
    if (Object.keys(next).length === 0) {
      // Nothing saved yet for this account: push what this browser has.
      persist(snapshotPersist(get));
      return;
    }
    set(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshotPersist(get)));
    } catch {
      /* non-fatal */
    }
  },
  setImageModel(model) {
    set({ imageModel: model });
    persist(snapshotPersist(get));
  },
  setImageProvider(p) {
    set({ imageProvider: p });
    persist(snapshotPersist(get));
  },
  setUiMode(mode) {
    set({ uiMode: mode });
    persist(snapshotPersist(get));
  },
  setVideoQuality(q) {
    set({ videoQuality: q });
    persist(snapshotPersist(get));
  },
  setVideoModel(m) {
    set({ videoModel: m });
    persist(snapshotPersist(get));
  },
  setOmniFlashDuration(d) {
    set({ omniFlashDuration: d });
    persist(snapshotPersist(get));
  },
  setMediaProvider(p) {
    set({ mediaProvider: p });
    persist(snapshotPersist(get));
  },
}));
