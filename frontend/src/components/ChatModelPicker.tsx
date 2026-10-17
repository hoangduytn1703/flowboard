import { useEffect, useRef, useState } from "react";
import {
  getLlmProviders,
  setLlmConfig,
  type LLMFeatureConfig,
  type LLMProviderInfo,
  type LLMProviderName,
} from "../api/client";

/**
 * Quick provider / model / effort switch for the Chat AI, opened from the
 * pill in the ChatDock header. Writes the optional `chat_agent` feature —
 * the same pin as the "Chat AI" row in Settings → AI Providers — so the two
 * never disagree. Until something is saved here the chat inherits the
 * Planner's pin (`current.inherited`).
 */

const PROVIDER_LABEL: Record<LLMProviderName, string> = {
  claude: "Claude",
  gemini: "Gemini (agy)",
  openai: "OpenAI (Codex)",
  muse: "Muse",
};
// Muse is left out on purpose: no worker / gateway runs here (BUGLOG FB-006).
const SHOWN: LLMProviderName[] = ["gemini", "claude", "openai"];

function defaultEffortFor(p: LLMProviderInfo | undefined): string | null {
  if (!p || !p.supportsEffort || p.efforts.length === 0) return null;
  return p.efforts.includes("medium") ? "medium" : p.efforts[0];
}

interface Props {
  current: { pin: LLMFeatureConfig; inherited: boolean } | null;
  onClose: () => void;
  onSaved: () => void;
}

export function ChatModelPicker({ current, onClose, onSaved }: Props) {
  const [providers, setProviders] = useState<LLMProviderInfo[] | null>(null);
  const [provider, setProvider] = useState<LLMProviderName | null>(current?.pin.provider ?? null);
  const [model, setModel] = useState<string | null>(current?.pin.model ?? null);
  const [effort, setEffort] = useState<string | null>(current?.pin.effort ?? null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    getLlmProviders()
      .then((list) => {
        if (alive) setProviders(list);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, []);

  // Close on outside click / Escape, like the other header popovers.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const anchor = boxRef.current?.parentElement;
      if (anchor && !anchor.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const shown = (providers ?? []).filter((p) => SHOWN.includes(p.name));
  const info = shown.find((p) => p.name === provider);
  const models = info?.models ?? [];
  // A pinned id the catalog no longer lists stays selectable instead of
  // being silently replaced.
  const modelOptions =
    model && !models.some((m) => m.id === model) ? [{ id: model, label: model }, ...models] : models;

  function pickProvider(name: LLMProviderName) {
    const next = shown.find((p) => p.name === name);
    setProvider(name);
    setModel(next?.defaultModel ?? null);
    setEffort(defaultEffortFor(next));
    setError(null);
  }

  async function save() {
    if (!provider || saving) return;
    setSaving(true);
    setError(null);
    try {
      await setLlmConfig({ chat_agent: { provider, model, effort } });
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="chat-model-picker" ref={boxRef} role="dialog" aria-label="Chọn model cho Chat AI">
      <div className="chat-model-picker__title">
        Model cho Chat AI
        {current?.inherited && <span className="chat-model-picker__hint">đang theo Planner</span>}
      </div>

      {providers === null && !error && <div className="chat-model-picker__hint">Đang tải…</div>}

      {providers !== null && (
        <>
          <label className="chat-model-picker__field">
            <span>Provider</span>
            <select
              value={provider ?? ""}
              onChange={(e) => pickProvider(e.target.value as LLMProviderName)}
            >
              <option value="" disabled>
                Chọn…
              </option>
              {shown.map((p) => (
                <option key={p.name} value={p.name} disabled={!p.available}>
                  {PROVIDER_LABEL[p.name]}
                  {p.available ? "" : " — chưa cài"}
                </option>
              ))}
            </select>
          </label>

          {provider && (
            <label className="chat-model-picker__field">
              <span>Model</span>
              {modelOptions.length > 0 ? (
                <select value={model ?? ""} onChange={(e) => setModel(e.target.value || null)}>
                  <option value="">Mặc định của CLI</option>
                  {modelOptions.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label || m.id}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={model ?? ""}
                  placeholder="Mặc định của CLI"
                  onChange={(e) => setModel(e.target.value.trim() || null)}
                />
              )}
            </label>
          )}

          {provider && info?.supportsEffort && info.efforts.length > 0 && (
            <label className="chat-model-picker__field">
              <span>Effort</span>
              <select value={effort ?? ""} onChange={(e) => setEffort(e.target.value || null)}>
                <option value="">Mặc định</option>
                {info.efforts.map((lvl) => (
                  <option key={lvl} value={lvl}>
                    {lvl}
                  </option>
                ))}
              </select>
            </label>
          )}
        </>
      )}

      {error && (
        <div className="chat-model-picker__error" role="alert">
          {error}
        </div>
      )}

      <div className="chat-model-picker__actions">
        <button type="button" className="chat-model-picker__btn" onClick={onClose}>
          Huỷ
        </button>
        <button
          type="button"
          className="chat-model-picker__btn chat-model-picker__btn--primary"
          onClick={() => void save()}
          disabled={!provider || saving}
        >
          {saving ? "Đang lưu…" : "Lưu"}
        </button>
      </div>
    </div>
  );
}
