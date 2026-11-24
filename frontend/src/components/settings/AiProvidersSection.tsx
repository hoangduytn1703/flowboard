import { useCallback, useEffect, useRef, useState } from "react";
import {
  getLlmProviderModels,
  setLlmConfig,
  testLlmProvider,
  type LLMConfig,
  type LLMConfigUpdate,
  type LLMFeature,
  type LLMFeatureConfig,
  type LLMModelInfo,
  type LLMProviderInfo,
  type LLMProviderName,
} from "../../api/client";
import { FeatureConfigRow, type FeatureTest } from "./FeatureConfigRow";
import { ProviderSetupModal } from "./ProviderSetupModal";
import { MUSE_ENABLED } from "../../quicktool/muse";
import { getLlmConfigCached, getLlmProvidersCached, LLM_CONFIG_POLL_MS } from "../llmConfigCache";
import { toast } from "../../store/toast";

/**
 * Per-feature provider configuration. Each of Auto-prompt / Vision /
 * Planner independently picks a provider, a model and an effort level.
 *
 * Why the single-provider model was dropped: it forced one decision to
 * serve three very different jobs. Auto-prompt fires on every node and
 * wants something cheap and fast; Planner runs once per board and is
 * worth a slow expensive model; Vision only works on providers that can
 * read an image at all. One row per feature costs a little more screen
 * space and removes the compromise.
 *
 * "Configured" now means every feature has a provider — model and
 * effort stay optional (null = let the provider pick its default), so
 * a user who doesn't care about model choice can finish setup with
 * three provider picks.
 *
 * Draft vs. saved state: the three rows edit a local `draft` that is
 * seeded once from /config and re-seeded after Apply. The 30s poll
 * deliberately never overwrites it — a background refresh landing
 * mid-edit and resetting the user's half-made selection would be
 * maddening.
 *
 * CLI-only philosophy: only OAuth-CLI providers are surfaced
 * (Claude Code / Gemini via the agy CLI / OpenAI Codex).
 */

// Order matters — this is the option order in every provider select.
// Gemini first (lowest install friction), Claude middle, Codex last.
// Muse is hidden while MUSE_ENABLED is off (18/11).
const SHOWN_PROVIDERS: LLMProviderName[] = (["gemini", "claude", "openai", "muse"] as LLMProviderName[])
  .filter((p) => p !== "muse" || MUSE_ENABLED);
const FEATURES: LLMFeature[] = ["auto_prompt", "vision", "planner", "chat_agent"];
// Chat AI may stay unset (it then thinks with the Planner's pin), so it
// never blocks setup.
const OPTIONAL_FEATURES: LLMFeature[] = ["chat_agent"];

const FEATURE_META: Record<LLMFeature, { title: string; blurb: string }> = {
  auto_prompt: {
    title: "Viết kịch bản, lời thoại, bài đăng",
    blurb: "Việc chạy nhiều nhất — nên chọn AI nhanh.",
  },
  vision: {
    title: "Đọc ảnh, video",
    blurb: "Đọc ảnh sản phẩm, xem video mẫu. Chỉ liệt kê AI đọc được ảnh.",
  },
  planner: {
    title: "Lên kế hoạch",
    blurb: "Ít khi chạy — nên chọn AI mạnh.",
  },
  chat_agent: {
    title: "Trợ lý chat",
    blurb: "Không bắt buộc: để trống thì dùng AI của mục Lên kế hoạch.",
  },
};

// Gemini runs through its `agy` CLI; the seller only needs the name.
const PROVIDER_LABEL: Record<LLMProviderName, string> = {
  claude: "Claude",
  gemini: "Gemini",
  openai: "ChatGPT (Codex)",
  muse: "Muse",
};

const UNTESTED: FeatureTest = { state: "untested" };
const INITIAL_TESTS: Record<LLMFeature, FeatureTest> = {
  auto_prompt: UNTESTED,
  vision: UNTESTED,
  planner: UNTESTED,
  chat_agent: UNTESTED,
};

type Draft = Record<LLMFeature, LLMFeatureConfig>;

function draftFrom(config: LLMConfig): Draft {
  // Structural copy — the draft is mutated by the rows and must not
  // alias the fetched config (which `dirty` compares against).
  return {
    auto_prompt: { ...config.auto_prompt },
    vision: { ...config.vision },
    planner: { ...config.planner },
    chat_agent: { ...config.chat_agent },
  };
}

function sameFeature(a: LLMFeatureConfig, b: LLMFeatureConfig): boolean {
  return a.provider === b.provider && a.model === b.model && a.effort === b.effort;
}

/** Effort default when the user switches providers. The backend has no
 * `defaultEffort` field, so we pick the middle of the road: "medium"
 * when the provider offers it, otherwise the first level it reports. */
function defaultEffortFor(p: LLMProviderInfo | undefined): string | null {
  if (!p || !p.supportsEffort || p.efforts.length === 0) return null;
  return p.efforts.includes("medium") ? "medium" : p.efforts[0];
}

export function AiProvidersSection() {
  const [providers, setProviders] = useState<LLMProviderInfo[] | null>(null);
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Local edits, seeded from /config (see the draft note in the header).
  const [draft, setDraft] = useState<Draft | null>(null);
  const [tests, setTests] = useState<Record<LLMFeature, FeatureTest>>(INITIAL_TESTS);
  // Catalogs fetched via the ⟳ button, overlaid on top of whatever
  // GET /providers shipped. Keyed by provider so two features sharing a
  // provider share the refreshed list.
  const [catalogs, setCatalogs] = useState<
    Partial<Record<LLMProviderName, LLMModelInfo[]>>
  >({});
  // Tracked per provider rather than as one global flag: two rows on
  // different providers can refresh at the same time, and two rows on
  // the SAME provider must both show the spinner (they share a catalog).
  const [refreshingModels, setRefreshingModels] = useState<
    Partial<Record<LLMProviderName, boolean>>
  >({});
  const [applying, setApplying] = useState(false);
  const [helpFor, setHelpFor] = useState<LLMProviderName | null>(null);

  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  // `fresh` skips the shared cache: after Apply and on the manual retry
  // the page must show the server's current state, not a minute-old copy.
  const refresh = useCallback(async (fresh = false): Promise<LLMConfig | null> => {
    try {
      const [p, c] = await Promise.all([getLlmProvidersCached({ fresh }), getLlmConfigCached({ fresh })]);
      if (!aliveRef.current) return null;
      setProviders(p);
      setConfig(c);
      setLoadError(null);
      return c;
    } catch (err) {
      if (!aliveRef.current) return null;
      setLoadError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, []);

  // Initial load + 30s polling, visibility-aware.
  useEffect(() => {
    void refresh();
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, LLM_CONFIG_POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [refresh]);

  // Seed the draft the first time /config lands. Guarded on
  // `draft === null` so later polls leave in-progress edits alone.
  useEffect(() => {
    if (draft !== null || config === null) return;
    setDraft(draftFrom(config));
  }, [config, draft]);

  function patchFeature(feature: LLMFeature, patch: Partial<LLMFeatureConfig>) {
    setDraft((prev) => (prev ? { ...prev, [feature]: { ...prev[feature], ...patch } } : prev));
  }

  function handleProviderChange(feature: LLMFeature, name: LLMProviderName) {
    const info = providers?.find((p) => p.name === name);
    // Model + effort belong to the provider that offered them, so a
    // provider switch resets both to that provider's defaults rather
    // than carrying over an id the new CLI has never heard of.
    patchFeature(feature, {
      provider: name,
      model: info?.defaultModel ?? null,
      effort: defaultEffortFor(info),
    });
    // The previous test result was against a different target.
    setTests((prev) => ({ ...prev, [feature]: UNTESTED }));
  }

  function catalogFor(name: LLMProviderName | null): LLMModelInfo[] {
    if (!name) return [];
    return catalogs[name] ?? providers?.find((p) => p.name === name)?.models ?? [];
  }

  async function refreshModels(name: LLMProviderName) {
    if (refreshingModels[name]) return;
    setRefreshingModels((prev) => ({ ...prev, [name]: true }));
    try {
      const { models } = await getLlmProviderModels(name, true);
      if (!aliveRef.current) return;
      setCatalogs((prev) => ({ ...prev, [name]: models }));
      if (models.length > 0) toast.success(`${PROVIDER_LABEL[name]}: ${models.length} model.`);
      else toast.warning(`${PROVIDER_LABEL[name]} không trả về model nào — hãy nhập ID model.`);
    } catch (err) {
      toast.error(`Không làm mới được danh sách model: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      if (aliveRef.current) {
        setRefreshingModels((prev) => ({ ...prev, [name]: false }));
      }
    }
  }

  async function runTest(feature: LLMFeature) {
    const pin = draft?.[feature];
    if (!pin?.provider) return;
    setTests((prev) => ({ ...prev, [feature]: { state: "testing" } }));
    // Tests carry the row's exact model + effort: a provider that
    // answers on its default model can still fail on an exotic one.
    const result = await testLlmProvider(pin.provider, {
      model: pin.model,
      effort: pin.effort,
    });
    if (!aliveRef.current) return;
    setTests((prev) => ({
      ...prev,
      [feature]: result.ok
        ? { state: "ok", latencyMs: result.latencyMs }
        : { state: "fail", error: result.error || "kiểm tra thất bại" },
    }));
  }

  /** The simple choice: one AI for everything (reading pictures stays as it is when that AI cannot read them). */
  async function useEverywhere(name: LLMProviderName) {
    if (!providers || applying) return;
    const info = providers.find((p) => p.name === name);
    if (!info) return;
    setApplying(true);
    try {
      const body: LLMConfigUpdate = {};
      for (const feature of FEATURES) {
        if (feature === "vision" && !info.supportsVision) continue;
        body[feature] = { provider: name, model: info.defaultModel ?? null, effort: defaultEffortFor(info) };
      }
      await setLlmConfig(body);
      toast.success(`Từ giờ ${PROVIDER_LABEL[name]} viết cho bạn.`);
      const fresh = await refresh(true);
      if (fresh && aliveRef.current) setDraft(draftFrom(fresh));
      window.dispatchEvent(new CustomEvent("flowboard:llm-config-changed"));
    } catch (err) {
      toast.error(`Không lưu được: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      if (aliveRef.current) setApplying(false);
    }
  }

  async function handleApply() {
    if (!draft || applying) return;
    setApplying(true);
    try {
      const body: LLMConfigUpdate = {};
      for (const feature of FEATURES) {
        const pin = draft[feature];
        // A feature with no provider has nothing to pin — leave it out
        // rather than PUTting a null the backend would have to special
        // case. model/effort DO go out as null when unset: that's the
        // signal for "use the provider default", and omitting them
        // would leave a stale id from the previous provider in place.
        if (!pin.provider) continue;
        body[feature] = { provider: pin.provider, model: pin.model, effort: pin.effort };
      }
      await setLlmConfig(body);
      toast.success("Đã lưu cài đặt AI.");
      const fresh = await refresh(true);
      if (fresh && aliveRef.current) setDraft(draftFrom(fresh));
      // Broadcast so the badge + ForcedSetupGate refresh immediately
      // instead of waiting up to 30s for their own poll. Plain window
      // event keeps the contract loose — anyone interested subscribes,
      // no shared store coupling.
      window.dispatchEvent(new CustomEvent("flowboard:llm-config-changed"));
    } catch (err) {
      toast.error(`Không áp dụng được: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      if (aliveRef.current) setApplying(false);
    }
  }

  // ── Render guards ───────────────────────────────────────────────

  if ((!providers || !config || !draft) && !loadError) {
    return (
      <div className="ai-providers-section">
        <div className="ai-providers-section__skeleton">
          <div className="ai-providers-section__skeleton-row ai-providers-section__skeleton-row--tall" />
          <div className="ai-providers-section__skeleton-row ai-providers-section__skeleton-row--tall" />
          <div className="ai-providers-section__skeleton-row ai-providers-section__skeleton-row--tall" />
        </div>
      </div>
    );
  }

  if (loadError && (!providers || !config || !draft)) {
    return (
      <div className="ai-providers-section">
        <div className="ai-providers-section__error" role="alert">
          ⚠ Không tải được cài đặt AI.
          <button
            type="button"
            className="ai-providers-section__retry"
            onClick={() => void refresh(true)}
          >
            Thử lại
          </button>
          <div className="ai-providers-section__error-detail">{loadError}</div>
        </div>
      </div>
    );
  }

  // Past this point providers / config / draft are all non-null.
  const allProviders = providers!;
  const currentDraft = draft!;
  const ordered = SHOWN_PROVIDERS.map((name) =>
    allProviders.find((p) => p.name === name),
  ).filter((p): p is LLMProviderInfo => p !== undefined);
  const visionCapable = ordered.filter((p) => p.supportsVision);

  const missing = FEATURES.filter(
    (f) => !OPTIONAL_FEATURES.includes(f) && !currentDraft[f].provider,
  );
  const dirty = FEATURES.some((f) => !sameFeature(currentDraft[f], config![f]));

  // the one AI every task uses, when they all agree (else the detailed choice below says who does what)
  const saved = config!;
  const mainUses = FEATURES.filter((f) => f !== "chat_agent").map((f) => saved[f].provider);
  const oneAi = mainUses.every((p) => p && p === mainUses[0]) ? mainUses[0] : null;
  return (
    <div className="ai-providers-section">
      <div className="ai-providers-section__intro">
        AI viết kịch bản, lời thoại, bài đăng và đọc ảnh sản phẩm cho bạn. Chưa chọn, hoặc AI đã chọn bị lỗi / hết lượt, thì DFlow
        tự dùng Gemini key bạn đã nhập ở tab 🔑 Gemini key.
      </div>

      <div className="settings-panel__section">
        <div className="settings-panel__label">AI viết cho bạn</div>
        <div className="qt-post__actions" role="radiogroup" aria-label="AI viết cho bạn">
          {ordered.map((p) => (
            <button key={p.name} type="button" role="radio" aria-checked={oneAi === p.name} disabled={applying || !p.available}
                    className={`qt-btn qt-btn--small${oneAi === p.name ? " qt-btn--accent" : " qt-btn--ghost"}`}
                    title={p.available ? `Dùng ${PROVIDER_LABEL[p.name]} cho mọi việc viết` : `${PROVIDER_LABEL[p.name]} chưa cài trên máy này`}
                    onClick={() => oneAi !== p.name && void useEverywhere(p.name)}>
              {PROVIDER_LABEL[p.name]}{p.available ? "" : " (chưa cài)"}
            </button>
          ))}
        </div>
        <div className="settings-panel__hint">
          {oneAi ? <>Đang dùng <strong>{PROVIDER_LABEL[oneAi]}</strong> cho mọi việc.</>
            : mainUses.some(Boolean) ? "Mỗi việc đang dùng một AI khác nhau — xem mục Nâng cao bên dưới."
            : "Chưa chọn — DFlow dùng Gemini key."}
          {" "}AI “chưa cài” cần cài trên máy trước (bấm “Hướng dẫn cài” trong mục Nâng cao).
        </div>
      </div>

      <details className="ai-providers-section__advanced">
        <summary>Nâng cao: chọn AI, phiên bản, mức suy nghĩ riêng cho từng việc</summary>

      {missing.length > 0 && (
        // Setup isn't complete until every feature has a provider —
        // that's exactly what the backend's `configured` flag (and the
        // forced-setup gate) keys off.
        <div className="ai-providers-section__mixed-notice" role="alert">
          ⓘ Chưa chọn: {missing.map((f) => FEATURE_META[f].title).join(", ")}.
          Chọn AI cho từng mục rồi bấm Áp dụng — hoặc chọn một AI ở trên cho mọi việc.
        </div>
      )}

      <div className="feature-config-list">
        {FEATURES.map((feature) => {
          const pin = currentDraft[feature];
          const options = feature === "vision" ? visionCapable : ordered;
          // Resolved against the full list, not `options` — see the
          // `selected` prop docs on FeatureConfigRow.
          const selected = pin.provider
            ? allProviders.find((p) => p.name === pin.provider) ?? null
            : null;
          return (
            <FeatureConfigRow
              key={feature}
              title={FEATURE_META[feature].title}
              blurb={FEATURE_META[feature].blurb}
              options={options}
              selected={selected}
              value={pin}
              models={catalogFor(pin.provider)}
              modelsRefreshing={pin.provider ? refreshingModels[pin.provider] === true : false}
              test={tests[feature]}
              providerLabel={(name) => PROVIDER_LABEL[name]}
              onProviderChange={(name) => handleProviderChange(feature, name)}
              onPatch={(patch) => patchFeature(feature, patch)}
              onTest={() => void runTest(feature)}
              onRefreshModels={() => {
                if (pin.provider) void refreshModels(pin.provider);
              }}
              onSetupHelp={() => setHelpFor(pin.provider)}
            />
          );
        })}
      </div>

      <div className="selection-panel__actions">
        <button
          type="button"
          className="selection-panel__apply-btn"
          onClick={handleApply}
          disabled={!dirty || applying}
          title={
            dirty
              ? "Lưu các lựa chọn này."
              : "Chưa có thay đổi nào kể từ lần lưu trước."
          }
        >
          {applying ? "Đang áp dụng…" : dirty ? "Áp dụng thay đổi" : "Đã lưu"}
        </button>
      </div>
      </details>

      <ProviderSetupModal
        provider={helpFor ?? "claude"}
        open={helpFor !== null}
        onClose={() => setHelpFor(null)}
      />
    </div>
  );
}
