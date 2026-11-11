import { useEffect, useRef, useState } from "react";
import { useGenerationStore } from "../store/generation";
import {
  useSettingsStore,
  type ImageModelKey,
  type VideoQuality,
} from "../store/settings";
import { getLatestRelease, isNewerVersion, type LatestRelease } from "../api/github";
import { GeminiKeysSection } from "./GeminiKeysSection";
import { AiProvidersSection } from "./settings/AiProvidersSection";
import { MachineSection } from "./settings/MachineSection";
import { FlowAccountsSection } from "./settings/FlowAccountsSection";
import { AccountPoolSection } from "./settings/AccountPoolSection";
import { ImageProvidersSection } from "./settings/ImageProvidersSection";
import { GeminiMarkSection } from "./settings/GeminiMarkSection";
import { DataFolderSection } from "./settings/DataFolderSection";
import {
  getPinnedFlowProject,
  setPinnedFlowProject,
  type PinnedFlowProject,
} from "../api/client";
import packageJson from "../../package.json";

const APP_VERSION: string = packageJson.version;
// Loose on purpose: "is there a uuid in what they typed", not the backend's
// full project/-segment rule. Used only to enable the Save button.
const UUID_ANYWHERE =
  /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;


/**
 * Dashboard Settings popover anchored to the AccountPanel gear button.
 *
 * Surfaces the model context that drives every generation:
 *   - Paygate tier — read from FLOWBOARD_PAYGATE_TIER, read-only here.
 *     Flow's createProject stopped returning anything to detect it from
 *     in the September 2026 migration, so it is declared, not discovered.
 *   - Google Flow project — the single project uuid every board generates
 *     into. Server state (agent-side override on top of .env), so unlike
 *     everything else here it is fetched/PUT directly, never persisted to
 *     localStorage.
 *   - Video quality — Veo 3.1 Lite / Fast / Quality, plus Ultra-only
 *     Lite Relaxed / Fast Relaxed (0-credit low-priority queue). Applies
 *     to BOTH portrait and landscape; backend resolves
 *     [tier][quality][aspect] → concrete Flow model key.
 *   - Image model — Banana Pro vs Banana 2 picker. Persisted to
 *     localStorage; every gen_image / edit_image dispatch reads it.
 */

const IMAGE_MODELS: { key: ImageModelKey; label: string; hint: string }[] = [
  {
    key: "NANO_BANANA_PRO",
    label: "Nano Banana Pro",
    hint: "Bản cao cấp: ảnh nét hơn, chậm hơn một chút — nên dùng.",
  },
  {
    key: "NANO_BANANA_2",
    label: "Nano Banana 2",
    hint: "Bản nhẹ, nhanh hơn — Flow hay từ chối bản này, chỉ chọn khi bản Pro lỗi.",
  },
];

// Order: lite → fast → quality (paid), then the Ultra-only relaxed
// variants (0-credit low-priority queue). Only Lite renders on Pro
// (Tier 1): the batch path has no Pro id captured for Fast / Quality, and
// Flow rejected them with PUBLIC_ERROR_MODEL_ACCESS_DENIED (FB-007) — so
// everything but Lite is Ultra-only and Pro users see it locked. Same
// gating as GenerationDialog's model picker.
const VIDEO_QUALITIES: {
  key: VideoQuality;
  label: string;
  hint: string;
  ultraOnly: boolean;
}[] = [
  {
    key: "lite",
    label: "Veo 3.1 Lite",
    hint: "Nhanh nhất, model nhẹ nhất. Áp dụng cho cả 16:9 và 9:16.",
    ultraOnly: false,
  },
  {
    key: "fast",
    label: "Veo 3.1 Fast",
    hint: "Mặc định — cân bằng giữa chất lượng và tốc độ. Áp dụng cho cả 16:9 và 9:16.",
    ultraOnly: true,
  },
  {
    key: "quality",
    label: "Veo 3.1 Quality",
    hint: "Chất lượng cao nhất, chậm nhất. Hợp cho cảnh chính. Áp dụng cho cả 16:9 và 9:16.",
    ultraOnly: true,
  },
  {
    key: "lite_relaxed",
    label: "Veo 3.1 Lite (Ưu tiên thấp)",
    hint: "Cùng bản Lite nhưng xếp hàng ưu tiên thấp — 0 credit. Chậm hơn khi Flow đang bận.",
    ultraOnly: true,
  },
];

const OMNI_HINT =
  "Nên dùng. Làm video 8 giây từ ảnh cảnh (≈12 credit Flow mỗi video), dọc lẫn ngang đều được, " +
  "ổn định nhất trên cả gói Pro lẫn Ultra.";

type SettingsTab = "gen" | "flow" | "ai" | "keys" | "data" | "machine" | "about";
const TABS: { key: SettingsTab; icon: string; label: string }[] = [
  { key: "gen", icon: "🎬", label: "Tạo ảnh & video" },
  { key: "flow", icon: "⚡", label: "Google Flow" },
  // which AI writes scripts / posts (Claude CLI, Gemini CLI, Codex…): only the Canvas toolbar had it, and Canvas is hidden
  { key: "ai", icon: "🤖", label: "AI viết" },
  { key: "keys", icon: "🔑", label: "Gemini key" },
  { key: "data", icon: "☁", label: "Dữ liệu" },
  // the Flow plan, cloud line, folders, extension, restart — instead of editing .env by hand (the desktop app)
  { key: "machine", icon: "🖥", label: "Máy này" },
  { key: "about", icon: "ℹ", label: "Thông tin" },
];
const TAB_STORAGE = "flowboard.settings.tab";

function readTab(): SettingsTab {
  try {
    const v = window.localStorage.getItem(TAB_STORAGE);
    return TABS.some((t) => t.key === v) ? (v as SettingsTab) : "gen";
  } catch {
    return "gen";
  }
}

interface SettingsPanelProps {
  open: boolean;
  onClose(): void;
  // Provided by AccountPanel. Called when the user clicks "Sign out"
  // — AccountPanel owns the post-logout state reset (clear cached
  // profile, kick the /me poll). Pass undefined when no identity is
  // loaded (the button auto-hides in that case).
  onLogout?: () => Promise<void> | void;
  // True while the parent's logout call is in flight — disables the
  // button so a double-click doesn't fire two POSTs.
  logoutPending?: boolean;
  // Called after the pinned Flow project is saved or cleared, so the
  // sidebar — which shows the same pinned id — re-reads instead of
  // displaying the value the user just replaced.
  onFlowProjectChange?: () => void;
}

export function SettingsPanel({
  open,
  onClose,
  onLogout,
  logoutPending,
  onFlowProjectChange,
}: SettingsPanelProps) {
  const tier = useGenerationStore((s) => s.paygateTier);
  const imageModel = useSettingsStore((s) => s.imageModel);
  const setImageModel = useSettingsStore((s) => s.setImageModel);
  const videoQuality = useSettingsStore((s) => s.videoQuality);
  const setVideoQuality = useSettingsStore((s) => s.setVideoQuality);
  const videoModel = useSettingsStore((s) => s.videoModel);
  const setVideoModel = useSettingsStore((s) => s.setVideoModel);

  const panelRef = useRef<HTMLDivElement>(null);
  // Which group is open; remembered per browser (a convenience, not state).
  const [tab, setTab] = useState<SettingsTab>(readTab);
  function chooseTab(next: SettingsTab) {
    setTab(next);
    try {
      window.localStorage.setItem(TAB_STORAGE, next);
    } catch {
      /* private window / blocked storage: just don't remember */
    }
  }

  // Esc closes (click-outside is handled by the backdrop's onClick).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Check GitHub for a newer release. Cached in sessionStorage by
  // the helper, so re-opening the dialog doesn't burn API quota.
  const [latestRelease, setLatestRelease] = useState<LatestRelease | null>(null);
  // Sign-out takes two clicks; the second one must come within a few seconds.
  const [confirmLogout, setConfirmLogout] = useState(false);
  useEffect(() => {
    if (!confirmLogout) return;
    const t = setTimeout(() => setConfirmLogout(false), 5000);
    return () => clearTimeout(t);
  }, [confirmLogout]);
  useEffect(() => { if (!open) setConfirmLogout(false); }, [open]);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    getLatestRelease().then((r) => {
      if (alive) setLatestRelease(r);
    });
    return () => {
      alive = false;
    };
  }, [open]);
  const updateAvailable =
    !!latestRelease?.tagName &&
    isNewerVersion(latestRelease.tagName, APP_VERSION);

  // Pinned Flow project. Server state — read on open and PUT on save, never
  // mirrored into the persisted settings store, because the agent (and the
  // boards it rebinds) own it, not this browser.
  const [flowProject, setFlowProject] = useState<PinnedFlowProject | null>(null);
  const [flowProjectError, setFlowProjectError] = useState<string | null>(null);
  const [projectDraft, setProjectDraft] = useState("");
  const [projectSaving, setProjectSaving] = useState(false);
  const [projectSaveError, setProjectSaveError] = useState<string | null>(null);
  const [projectNotice, setProjectNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setFlowProject(null);
    setFlowProjectError(null);
    setProjectSaveError(null);
    setProjectNotice(null);
    getPinnedFlowProject()
      .then((p) => {
        if (!alive) return;
        setFlowProject(p);
        setProjectDraft(p.flow_project_id ?? "");
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setFlowProjectError(
          err instanceof Error ? err.message : "Không đọc được project đã ghim",
        );
      });
    return () => {
      alive = false;
    };
  }, [open]);

  // `null` clears the override and falls back to .env; a string pins it.
  async function saveFlowProject(next: string | null) {
    if (projectSaving) return;
    setProjectSaving(true);
    setProjectSaveError(null);
    setProjectNotice(null);
    try {
      const res = await setPinnedFlowProject(next);
      setFlowProject({
        flow_project_id: res.flow_project_id,
        source: res.source,
        env_project_id: res.env_project_id,
      });
      setProjectDraft(res.flow_project_id ?? "");
      // The generation store caches the project id for the whole page load
      // and nothing else clears it. Without this the dialog says "Saved",
      // the backend rebinds the boards, and every subsequent dispatch still
      // carries the OLD uuid — which flow_sdk takes as an explicit argument
      // and never resolves, so renders keep landing in the previous Flow
      // project with no error anywhere. Exactly the failure this whole
      // setting exists to remove, one layer up.
      useGenerationStore.setState({ projectId: null });
      setProjectNotice(
        res.rebound_boards > 0
          ? `Đã lưu — ${res.rebound_boards} board đã chuyển sang project này`
          : "Đã lưu",
      );
      onFlowProjectChange?.();
    } catch (err) {
      // 400 detail arrives verbatim from the backend (see setPinnedFlowProject).
      setProjectSaveError(err instanceof Error ? err.message : "Lưu thất bại");
    } finally {
      setProjectSaving(false);
    }
  }

  const trimmedDraft = projectDraft.trim();
  // Mirrors the backend's shape rule loosely, only to decide whether Save is
  // worth offering — the server stays the judge and its 400 is shown verbatim.
  const draftUuid = trimmedDraft.match(UUID_ANYWHERE)?.[0]?.toLowerCase() ?? null;
  // Two things had to be fixed together here.
  //
  // Comparing against the *effective* id meant a user on the .env default
  // could never turn it into a durable override — Save was permanently
  // disabled on the value the dialog was showing them. Comparing against the
  // override only fixes that.
  //
  // But doing just that opens the other half: the read path deliberately
  // accepts a legacy non-uuid `.env` value, so the dialog can be displaying
  // something the strict write path would reject. Requiring a uuid in the
  // draft is what stops the user clicking Save on the value in front of them
  // and being told it is not a Flow project ID.
  const canSaveProject =
    !!draftUuid &&
    (flowProject?.source !== "override" || draftUuid !== flowProject.flow_project_id);
  const legacyEnvId =
    flowProject?.source === "env" &&
    !!flowProject.flow_project_id &&
    !UUID_ANYWHERE.test(flowProject.flow_project_id);

  if (!open) return null;

  const tierLabel = tier === "PAYGATE_TIER_TWO"
    ? "Ultra"
    : tier === "PAYGATE_TIER_ONE"
      ? "Pro"
      : "Đang nhận diện…";
  const isUltra = tier === "PAYGATE_TIER_TWO";
  const videoValue = videoModel === "omni_flash" ? "omni_flash" : `veo:${videoQuality}`;
  const videoHint = videoModel === "omni_flash"
    ? OMNI_HINT
    : VIDEO_QUALITIES.find((q) => q.key === videoQuality)?.hint ?? "";
  const imageHint = IMAGE_MODELS.find((m) => m.key === imageModel)?.hint ?? "";

  return (
    <div
      className="settings-panel-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        className="settings-panel settings-panel--tabs"
        role="dialog"
        aria-modal="true"
        aria-label="Cài đặt"
      >
        <div className="settings-panel__header">
          <span className="settings-panel__title">Cài đặt</span>
          <button
            type="button"
            className="settings-panel__close"
            onClick={onClose}
            aria-label="Đóng cài đặt"
          >
            ×
          </button>
        </div>

        <div className="settings-panel__body">
          <nav className="settings-panel__nav" role="tablist" aria-label="Nhóm cài đặt">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={`settings-panel__tab${tab === t.key ? " settings-panel__tab--active" : ""}`}
                onClick={() => chooseTab(t.key)}
              >
                <span className="settings-panel__tab-icon" aria-hidden="true">{t.icon}</span>
                <span>{t.label}</span>
                {t.key === "about" && updateAvailable && <span className="settings-panel__tab-dot" title="Có bản mới" />}
              </button>
            ))}
          </nav>

          <div className="settings-panel__content" role="tabpanel">
            {tab === "gen" && (
              <>
                <div className="settings-panel__section">
                  <label className="settings-field">
                    <span className="settings-panel__label">Model video</span>
                    <select
                      className="settings-panel__select"
                      value={videoValue}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "omni_flash") {
                          setVideoModel("omni_flash");
                        } else {
                          setVideoModel("veo");
                          setVideoQuality(v.slice(4) as VideoQuality);
                        }
                      }}
                    >
                      <option value="omni_flash">Omni Flash — nên dùng</option>
                      {VIDEO_QUALITIES.map((q) => {
                        const locked = q.ultraOnly && !isUltra;
                        return (
                          <option key={q.key} value={`veo:${q.key}`} disabled={locked}>
                            {q.label}{q.ultraOnly ? " — chỉ Ultra" : ""}
                          </option>
                        );
                      })}
                    </select>
                  </label>
                  <div className="settings-panel__hint">{videoHint}</div>
                  {!isUltra && (
                    <div className="settings-panel__hint">
                      Gói đang dùng: <strong>{tierLabel}</strong> — các model "chỉ Ultra" bị khoá.
                    </div>
                  )}
                </div>

                <div className="settings-panel__section">
                  <label className="settings-field">
                    <span className="settings-panel__label">Model ảnh</span>
                    <select
                      className="settings-panel__select"
                      value={imageModel}
                      onChange={(e) => setImageModel(e.target.value as ImageModelKey)}
                    >
                      {IMAGE_MODELS.map((m) => (
                        <option key={m.key} value={m.key}>{m.label}</option>
                      ))}
                    </select>
                  </label>
                  <div className="settings-panel__hint">{imageHint}</div>
                </div>

                <ImageProvidersSection />
                <GeminiMarkSection />
              </>
            )}

            {tab === "flow" && (
              <>
                {/* The one uuid every board generates into. Flow dropped project
                    creation + listing in the September 2026 migration, so there is no
                    way to pick one from a list — the user pastes it, and until they do
                    nothing can generate. */}
                <div className="settings-panel__section">
                  <div className="settings-panel__row-head">
                    <span className="settings-panel__label">Project Google Flow</span>
                    <span
                      className="settings-panel__chip"
                      title="Đặt bằng FLOWBOARD_PAYGATE_TIER trong file .env của agent — Flow không còn báo gói tài khoản nên phải khai báo thủ công."
                    >
                      Gói {tierLabel}
                    </span>
                  </div>
                  {flowProjectError ? (
                    <>
                      <div className="settings-panel__project-error">{flowProjectError}</div>
                      <div className="settings-panel__hint">Đóng rồi mở lại Cài đặt để thử lại.</div>
                    </>
                  ) : !flowProject ? (
                    <div className="settings-panel__hint">Đang tải…</div>
                  ) : (
                    <>
                      {flowProject.source === "none" && (
                        <div className="settings-panel__project-error">
                          Chưa chọn dự án Flow nên chưa tạo được ảnh / video. Cách nhanh nhất: mở trang
                          Hôm nay → thẻ Thiết lập → “Dùng dự án đang mở”. Hoặc mở một dự án tại{" "}
                          <a
                            className="settings-panel__about-link"
                            href="https://flow.google.com/"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            flow.google.com
                          </a>
                          , copy địa chỉ trang đó rồi dán vào ô bên dưới.
                        </div>
                      )}

                      <div className="settings-panel__project-row">
                        <input
                          type="text"
                          className="settings-panel__project-input"
                          value={projectDraft}
                          placeholder="Dán link dự án Flow (https://flow.google.com/…/project/…)"
                          spellCheck={false}
                          autoComplete="off"
                          disabled={projectSaving}
                          aria-label="uuid project Flow"
                          onChange={(e) => setProjectDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && canSaveProject) {
                              saveFlowProject(trimmedDraft);
                            }
                          }}
                        />
                        <button
                          type="button"
                          className="settings-panel__project-btn"
                          disabled={projectSaving || !canSaveProject}
                          onClick={() => saveFlowProject(trimmedDraft)}
                        >
                          {projectSaving ? "Đang lưu…" : "Lưu"}
                        </button>
                      </div>

                      <div className="settings-panel__hint">
                        {flowProject.source === "override"
                          ? "Đặt tại Cài đặt (ghi đè .env). "
                          : flowProject.source === "env"
                            ? "Lấy từ FLOWBOARD_FLOW_PROJECT_ID trong .env. "
                            : ""}
                        Mọi board tạo vào project này; lưu project mới thì các board đang ở project cũ chuyển theo.
                      </div>

                      {legacyEnvId && (
                        <div className="settings-panel__hint">
                          ID trong <code>.env</code> không phải uuid. Vẫn dùng được, nhưng muốn ghim lại từ đây thì
                          cần dán uuid — nút Lưu tắt cho tới lúc đó.
                        </div>
                      )}

                      {flowProject.source === "override" && (
                        <button
                          type="button"
                          className="settings-panel__project-clear"
                          disabled={projectSaving}
                          onClick={() => saveFlowProject(null)}
                        >
                          Xoá ghi đè —{" "}
                          {flowProject.env_project_id
                            ? `quay về ${flowProject.env_project_id.slice(0, 8)}… trong .env`
                            : "sẽ không còn project nào, nên không tạo được nữa"}
                        </button>
                      )}

                      {projectSaveError && (
                        <div className="settings-panel__project-error">{projectSaveError}</div>
                      )}
                      {projectNotice && !projectSaveError && (
                        <div className="settings-panel__project-ok">{projectNotice}</div>
                      )}
                    </>
                  )}
                </div>

                <FlowAccountsSection onProjectChange={onFlowProjectChange} />

                <AccountPoolSection onProjectChange={onFlowProjectChange} />

                {onLogout && (
                  // Sign out lives here (not in the AccountPanel chip) so the
                  // chip stays narrow enough for the email + status row to
                  // render without ellipsizing on default sidebar widths.
                  <div className="settings-panel__section settings-panel__section--logout">
                    <button
                      type="button"
                      className={`settings-panel__logout-btn${confirmLogout ? " settings-panel__logout-btn--armed" : ""}`}
                      onClick={() => {
                        if (!confirmLogout) { setConfirmLogout(true); return; }
                        setConfirmLogout(false);
                        void onLogout();
                      }}
                      disabled={logoutPending}
                    >
                      {logoutPending
                        ? "Đang đăng xuất…"
                        : confirmLogout
                          ? "Bấm lần nữa để đăng xuất (việc tạo ảnh/video sẽ dừng cho tới khi đăng nhập lại)"
                          : "Đăng xuất khỏi tài khoản Flow"}
                    </button>
                    {confirmLogout && (
                      <button type="button" className="qt-link settings-panel__logout-cancel" onClick={() => setConfirmLogout(false)}>
                        Huỷ, không đăng xuất
                      </button>
                    )}
                    <div className="settings-panel__hint">
                      Xoá thông tin tài khoản đã lưu và báo extension bỏ token đang giữ. Kết nối vẫn mở nên đăng
                      nhập lại không cần khởi động lại Chrome.
                    </div>
                  </div>
                )}
              </>
            )}

            {tab === "ai" && <AiProvidersSection />}

            {tab === "keys" && <GeminiKeysSection />}

            {tab === "data" && <DataFolderSection />}

            {tab === "machine" && <MachineSection />}

            {tab === "about" && (
              <div className="settings-panel__section">
                <div className="settings-panel__label">Thông tin</div>
                <div className="settings-panel__about-row">
                  <span className="settings-panel__about-key">Phiên bản</span>
                  <span className="settings-panel__about-value">
                    <code>v{APP_VERSION}</code>
                    {updateAvailable && latestRelease && (
                      <a
                        className="settings-panel__update-badge"
                        href={latestRelease.htmlUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`Mới nhất: ${latestRelease.tagName}`}
                      >
                        Có bản mới {latestRelease.tagName} →
                      </a>
                    )}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
