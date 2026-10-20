import { useEffect, useRef, useState } from "react";
import { useGenerationStore } from "../store/generation";
import {
  useSettingsStore,
  type ImageModelKey,
  type VideoQuality,
} from "../store/settings";
import { getLatestRelease, isNewerVersion, type LatestRelease } from "../api/github";
import { GeminiKeysSection } from "./GeminiKeysSection";
import { FlowAccountsSection } from "./settings/FlowAccountsSection";
import { AccountPoolSection } from "./settings/AccountPoolSection";
import { ImageProvidersSection } from "./settings/ImageProvidersSection";
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

const COMMUNITY_URL = "https://www.facebook.com/groups/flowkit.flowboard.community";

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
    hint: "GEM_PIX_2 — cao cấp, ảnh nét hơn, chậm hơn một chút",
  },
  {
    key: "NANO_BANANA_2",
    label: "Nano Banana 2",
    hint: "NARWHAL — nhanh hơn, bản nhẹ hơn",
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
        className="settings-panel"
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

      <div className="settings-panel__section">
        <div className="settings-panel__label">Gói tài khoản</div>
        <div className="settings-panel__value settings-panel__value--readonly">
          {tierLabel}
        </div>
        <div className="settings-panel__hint">
          Đặt bằng FLOWBOARD_PAYGATE_TIER trong file .env của agent — Flow
          không còn báo gói tài khoản nữa nên phải khai báo thủ công.
        </div>
      </div>

      {/* The one uuid every board generates into. Flow dropped project
          creation + listing in the September 2026 migration, so there is no
          way to pick one from a list — the user pastes it, and until they do
          nothing can generate. */}
      <div className="settings-panel__section">
        <div className="settings-panel__label">Project Google Flow</div>
        {flowProjectError ? (
          <>
            <div className="settings-panel__project-error">{flowProjectError}</div>
            <div className="settings-panel__hint">
              Đóng rồi mở lại Cài đặt để thử lại.
            </div>
          </>
        ) : !flowProject ? (
          <div className="settings-panel__value settings-panel__value--readonly">
            Đang tải…
          </div>
        ) : (
          <>
            {flowProject.source === "none" ? (
              <div className="settings-panel__project-error">
                Chưa có project Flow nào được cấu hình nên mọi lần tạo đều sẽ lỗi.
                Hãy mở một project tại{" "}
                <a
                  className="settings-panel__about-link"
                  href="https://flow.google.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  flow.google.com
                </a>
                , copy uuid trên thanh địa chỉ rồi dán vào ô bên dưới.
              </div>
            ) : (
              <>
                <div className="settings-panel__value settings-panel__value--readonly">
                  <code>{flowProject.flow_project_id}</code>
                </div>
                <div className="settings-panel__hint">
                  {flowProject.source === "override"
                    ? "Đặt tại Cài đặt — ghi đè .env."
                    : "Ghim bằng FLOWBOARD_FLOW_PROJECT_ID trong file .env của agent."}
                </div>
              </>
            )}

            <div className="settings-panel__project-row">
              <input
                type="text"
                className="settings-panel__project-input"
                value={projectDraft}
                placeholder="1dfd992a-4149-4f97-9d68-a1ede77d3fc3"
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

            {legacyEnvId && (
              <div className="settings-panel__hint">
                ID trong <code>.env</code> không phải uuid. Nó vẫn dùng được —
                những gì đã ghim vẫn chạy bình thường — nhưng muốn ghim lại
                từ đây thì cần uuid, nên nút Lưu sẽ tắt cho đến khi bạn dán uuid.
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
                  ? `quay về ${flowProject.env_project_id} trong .env`
                  : "sẽ không còn project nào, nên không tạo được nữa"}
              </button>
            )}

            {projectSaveError && (
              <div className="settings-panel__project-error">{projectSaveError}</div>
            )}
            {projectNotice && !projectSaveError && (
              <div className="settings-panel__project-ok">{projectNotice}</div>
            )}

            <div className="settings-panel__hint">
              Mọi board đều tạo vào project này. Khi lưu, các board đang ở project
              cũ sẽ được chuyển sang project mới.
            </div>
          </>
        )}
      </div>

      {/* Single unified Video model picker — flat list of every option
          (Veo tiers + Omni Flash). Selecting a Veo row stamps both
          videoModel="veo" + the matching quality; selecting Omni Flash
          stamps videoModel="omni_flash" (duration is picked per dispatch
          in the GenerationDialog). */}
      <div className="settings-panel__section">
        <div className="settings-panel__label">Model video</div>
        <div className="settings-panel__radio-group">
          {VIDEO_QUALITIES.map((q) => {
            const locked = q.ultraOnly && tier !== "PAYGATE_TIER_TWO";
            const checked = videoModel === "veo" && videoQuality === q.key;
            return (
              <label
                key={q.key}
                className={`settings-panel__radio${checked ? " settings-panel__radio--active" : ""}${locked ? " settings-panel__radio--locked" : ""}`}
              >
                <input
                  type="radio"
                  name="video-model"
                  value={`veo:${q.key}`}
                  checked={checked}
                  disabled={locked}
                  onChange={() => {
                    setVideoModel("veo");
                    setVideoQuality(q.key);
                  }}
                />
                <div>
                  <div className="settings-panel__radio-label">
                    {q.label}
                    {q.ultraOnly && (
                      <span className="model-badge">Chỉ Ultra</span>
                    )}
                  </div>
                  <div className="settings-panel__radio-hint">{q.hint}</div>
                </div>
              </label>
            );
          })}
          <label
            className={`settings-panel__radio${videoModel === "omni_flash" ? " settings-panel__radio--active" : ""}`}
          >
            <input
              type="radio"
              name="video-model"
              value="omni_flash"
              checked={videoModel === "omni_flash"}
              onChange={() => setVideoModel("omni_flash")}
            />
            <div>
              <div className="settings-panel__radio-label">
                Omni Flash (r2v)
                <span className="model-badge">Mặc định</span>
              </div>
              <div className="settings-panel__radio-hint">
                Tạo video từ ảnh tham chiếu. Thời lượng linh hoạt (4 / 6 / 8 / 10s)
                chọn cho mỗi lần tạo — 15 / 20 / 25 / 30 credit. Hỗ trợ cả dọc
                lẫn ngang. Khuyên dùng: Veo 3.1 Lite hiện bị Flow
                nhận rồi huỷ trên tài khoản Pro thường.
              </div>
            </div>
          </label>
        </div>
      </div>

      <AccountPoolSection onProjectChange={onFlowProjectChange} />

      <FlowAccountsSection onProjectChange={onFlowProjectChange} />

      <GeminiKeysSection />

      <ImageProvidersSection />

      <div className="settings-panel__section">
        <div className="settings-panel__label">Model ảnh</div>
        <div className="settings-panel__radio-group">
          {IMAGE_MODELS.map((m) => (
            <label
              key={m.key}
              className={`settings-panel__radio${imageModel === m.key ? " settings-panel__radio--active" : ""}`}
            >
              <input
                type="radio"
                name="image-model"
                value={m.key}
                checked={imageModel === m.key}
                onChange={() => setImageModel(m.key)}
              />
              <div>
                <div className="settings-panel__radio-label">{m.label}</div>
                <div className="settings-panel__radio-hint">{m.hint}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

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
        <div className="settings-panel__about-row">
          <span className="settings-panel__about-key">Cộng đồng</span>
          <a
            className="settings-panel__about-link"
            href={COMMUNITY_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            FlowKit & Flowboard trên Facebook →
          </a>
        </div>
      </div>

      {onLogout && (
        // Sign out lives here (not in the AccountPanel chip) so the
        // chip stays narrow enough for the email + status row to
        // render without ellipsizing on default sidebar widths.
        <div className="settings-panel__section settings-panel__section--logout">
          <button
            type="button"
            className="settings-panel__logout-btn"
            onClick={onLogout}
            disabled={logoutPending}
          >
            {logoutPending ? "Đang đăng xuất…" : "Đăng xuất khỏi tài khoản Flow"}
          </button>
          <div className="settings-panel__hint">
            Xoá thông tin tài khoản đã lưu và báo extension bỏ token đang giữ
            trong bộ nhớ. Kết nối WebSocket vẫn mở nên đăng nhập lại không
            cần khởi động lại Chrome.
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

