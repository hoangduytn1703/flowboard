import { useEffect, useState } from "react";
import {
  listImageProviders,
  setImageProviderKey,
  testImageProvider,
  type ImageProviderId,
  type ImageProviderInfo,
} from "../../api/imageProviders";
import { useSettingsStore, type ImageProviderKey } from "../../store/settings";
import { toast } from "../../store/toast";

/**
 * Settings → "Nguồn tạo ảnh". Select: Flow (default, spends Flow credits) /
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
  const [blocked, setBlocked] = useState<string | null>(null);
  // What the select shows. An API source without a key can be *viewed* (to paste
  // its key) but is only *applied* once the key is saved.
  const [viewing, setViewing] = useState<string>(imageProvider);
  useEffect(() => { setViewing(imageProvider); }, [imageProvider]);

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
    try {
      const row = await setImageProviderKey(id, (drafts[id] ?? "").trim());
      setProviders((list) => (list ?? []).map((p) => (p.id === id ? row : p)));
      setDrafts((d) => ({ ...d, [id]: "" }));
      if (row.configured && viewing === id) {
        setImageProvider(id as ImageProviderKey);
        setBlocked(null);
        toast.success(`Đã lưu key — giờ tạo ảnh bằng ${row.label}.`);
      } else {
        toast.success(row.configured ? "Đã lưu key." : "Đã xoá key.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lưu key thất bại.");
    } finally {
      setBusy("");
    }
  }

  async function test(id: ImageProviderId) {
    setBusy(`test:${id}`);
    try {
      const draft = (drafts[id] ?? "").trim();
      const res = await testImageProvider(id, draft || undefined);
      if (res.ok) toast.success(res.message); else toast.error(res.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Kiểm tra key thất bại.");
    } finally {
      setBusy("");
    }
  }

  const shown = providers?.find((p) => p.id === viewing) ?? null;
  const shownIsApi = !!shown && shown.id !== "flow";
  const hasDraft = shown ? (drafts[shown.id] ?? "").trim().length > 0 : false;

  return (
    <div className="settings-panel__section">
      <label className="settings-field">
        <span className="settings-panel__label">Nguồn tạo ảnh</span>
        {providers === null ? (
          <div className="settings-panel__hint">Đang tải…</div>
        ) : (
          <select
            className="settings-panel__select"
            value={viewing}
            onChange={(e) => {
              const p = providers.find((x) => x.id === e.target.value);
              if (!p) return;
              setViewing(p.id);
              if (p.configured) pick(p);
              else setBlocked(null);
            }}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}{p.id === "flow" ? " — mặc định" : p.configured ? "" : " — chưa có key"}
              </option>
            ))}
          </select>
        )}
      </label>
      {shown && (
        <div className="settings-panel__hint">
          {shown.notes_vi}
          {shown.model && <> · <code>{shown.model}</code></>}
        </div>
      )}
      {shownIsApi && shown && (
        <div className="settings-panel__keybox">
          <div className="settings-panel__hint">
            {shown.configured
              ? imageProvider === shown.id ? "Đang dùng nguồn này. Dán key mới để thay, để trống rồi bấm Xoá key để bỏ." : "Đã có key."
              : `Chưa có key — dán key của ${shown.label} rồi Lưu để chuyển sang nguồn này.`}
          </div>
          <input
            type="password"
            className="settings-panel__project-input"
            autoComplete="off"
            placeholder={shown.configured ? "Đã có key — dán key mới để thay" : "Dán API key"}
            value={drafts[shown.id] ?? ""}
            onChange={(e) => setDrafts((d) => ({ ...d, [shown.id]: e.target.value }))}
            disabled={busy !== ""}
          />
          <div className="gemini-keys__actions">
            <button
              type="button"
              className="gemini-keys__btn"
              onClick={() => void test(shown.id)}
              disabled={busy !== "" || (!hasDraft && !shown.configured)}
            >
              {busy === `test:${shown.id}` ? "Đang kiểm tra…" : "Kiểm tra"}
            </button>
            <button
              type="button"
              className="gemini-keys__btn gemini-keys__btn--primary"
              onClick={() => void save(shown.id)}
              disabled={busy !== "" || (!hasDraft && !shown.configured)}
            >
              {busy === `save:${shown.id}` ? "Đang lưu…" : hasDraft || !shown.configured ? "Lưu" : "Xoá key"}
            </button>
          </div>
        </div>
      )}
      {blocked && <div className="settings-panel__hint">{blocked}</div>}
    </div>
  );
}
