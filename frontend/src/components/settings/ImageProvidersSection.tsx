import { useEffect, useState } from "react";
import {
  listImageProviders,
  setImageProviderKey,
  testImageProvider,
  type ImageProviderId,
  type ImageProviderInfo,
} from "../../api/imageProviders";
import { useSettingsStore, type ImageProviderKey } from "../../store/settings";

/**
 * Settings → "Nguồn tạo ảnh". Radio: Flow (default, spends Flow credits) /
 * OpenAI GPT Image / xAI Grok Image, each API row with its own key input,
 * "Kiểm tra" (free models-endpoint probe) and "Lưu". A provider without a
 * saved key cannot be selected — the dispatch would only fail later in the
 * worker, so it is refused here with a message instead.
 */
export function ImageProvidersSection() {
  const imageProvider = useSettingsStore((s) => s.imageProvider);
  const setImageProvider = useSettingsStore((s) => s.setImageProvider);
  const [providers, setProviders] = useState<ImageProviderInfo[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string>("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [blocked, setBlocked] = useState<string | null>(null);

  async function refresh() {
    try {
      setProviders(await listImageProviders());
    } catch (err) {
      setProviders([]);
      setBlocked(err instanceof Error ? err.message : "không tải được danh sách");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  // A key removed elsewhere (or a fresh machine) must not leave an API
  // provider selected that can no longer render: fall back to Flow.
  useEffect(() => {
    if (!providers || imageProvider === "flow") return;
    const row = providers.find((p) => p.id === imageProvider);
    if (row && !row.configured) {
      setImageProvider("flow");
      setBlocked(`${row.label} chưa có API key nên đã chuyển về Flow.`);
    }
  }, [providers, imageProvider, setImageProvider]);

  function pick(p: ImageProviderInfo) {
    if (!p.configured) {
      setBlocked(`Nhập và lưu API key cho ${p.label} trước khi chọn.`);
      return;
    }
    setBlocked(null);
    setImageProvider(p.id as ImageProviderKey);
  }

  async function save(id: ImageProviderId) {
    setBusy(`save:${id}`);
    setNotes((n) => ({ ...n, [id]: "" }));
    try {
      const row = await setImageProviderKey(id, (drafts[id] ?? "").trim());
      setProviders((list) => (list ?? []).map((p) => (p.id === id ? row : p)));
      setDrafts((d) => ({ ...d, [id]: "" }));
      setNotes((n) => ({ ...n, [id]: row.configured ? "Đã lưu key." : "Đã xoá key." }));
    } catch (err) {
      setNotes((n) => ({ ...n, [id]: err instanceof Error ? err.message : "lưu thất bại" }));
    } finally {
      setBusy("");
    }
  }

  async function test(id: ImageProviderId) {
    setBusy(`test:${id}`);
    setNotes((n) => ({ ...n, [id]: "" }));
    try {
      const draft = (drafts[id] ?? "").trim();
      const res = await testImageProvider(id, draft || undefined);
      setNotes((n) => ({ ...n, [id]: `${res.ok ? "✓" : "✗"} ${res.message}` }));
    } catch (err) {
      setNotes((n) => ({ ...n, [id]: err instanceof Error ? err.message : "kiểm tra thất bại" }));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="settings-panel__section">
      <div className="settings-panel__label">Nguồn tạo ảnh</div>
      <div className="settings-panel__hint">
        Bước tạo ảnh có thể dùng tài khoản API khác thay vì credit Flow. Ảnh từ API vẫn được
        đưa vào Flow project để làm nguyên liệu cho bước tạo video.
      </div>
      {providers === null ? (
        <div className="settings-panel__hint">Đang tải…</div>
      ) : (
        <div className="settings-panel__radio-group">
          {providers.map((p) => {
            const active = imageProvider === p.id;
            const isApi = p.id !== "flow";
            const hasDraft = (drafts[p.id] ?? "").trim().length > 0;
            return (
              <label
                key={p.id}
                className={`settings-panel__radio${active ? " settings-panel__radio--active" : ""}${
                  !p.configured ? " settings-panel__radio--locked" : ""
                }`}
                title={p.configured ? undefined : "Chưa có API key"}
              >
                <input
                  type="radio"
                  name="image-provider"
                  value={p.id}
                  checked={active}
                  onChange={() => pick(p)}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="settings-panel__radio-label">
                    <span
                      aria-label={p.configured ? "đã cấu hình" : "chưa có key"}
                      style={{
                        display: "inline-block",
                        width: 8,
                        height: 8,
                        borderRadius: 999,
                        background: p.configured ? "#2ecc71" : "#888",
                        flex: "0 0 auto",
                      }}
                    />
                    {p.label}
                    {p.id === "flow" && <span className="model-badge">Mặc định</span>}
                    {p.model && <code style={{ fontSize: 12, opacity: 0.7 }}>{p.model}</code>}
                  </div>
                  <div className="settings-panel__radio-hint">{p.notes_vi}</div>
                  {isApi && (
                    <div
                      // Stop the label from toggling the radio when the user
                      // clicks into the key field / buttons.
                      onClick={(e) => e.preventDefault()}
                      style={{ marginTop: 6 }}
                    >
                      <input
                        type="password"
                        className="gemini-keys__textarea"
                        style={{ width: "100%", boxSizing: "border-box" }}
                        autoComplete="off"
                        placeholder={p.configured ? "Đã có key — dán key mới để thay, để trống rồi Lưu để xoá" : "Dán API key"}
                        value={drafts[p.id] ?? ""}
                        onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                        disabled={busy !== ""}
                      />
                      <div className="gemini-keys__actions">
                        <button
                          type="button"
                          className="gemini-keys__btn"
                          onClick={() => void test(p.id)}
                          disabled={busy !== "" || (!hasDraft && !p.configured)}
                        >
                          {busy === `test:${p.id}` ? "Đang kiểm tra…" : "Kiểm tra"}
                        </button>
                        <button
                          type="button"
                          className="gemini-keys__btn gemini-keys__btn--primary"
                          onClick={() => void save(p.id)}
                          disabled={busy !== "" || (!hasDraft && !p.configured)}
                        >
                          {busy === `save:${p.id}` ? "Đang lưu…" : hasDraft ? "Lưu" : "Xoá key"}
                        </button>
                      </div>
                      {notes[p.id] && <div className="settings-panel__hint">{notes[p.id]}</div>}
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      )}
      {blocked && <div className="settings-panel__hint">{blocked}</div>}
    </div>
  );
}
