import { useEffect, useState } from "react";
import { getGeminiKeys, setGeminiKeys, testGeminiKeys, type GeminiKeyState } from "../api/client";
import { toast } from "../store/toast";

/**
 * Settings → Gemini API keys. Several keys pasted at once; the agent
 * rotates to the next one when a key runs out of quota. Keys are shown
 * masked and never sent back in full.
 */
export function GeminiKeysSection() {
  const [keys, setKeys] = useState<GeminiKeyState[] | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"" | "save" | "test">("");
  const [results, setResults] = useState<Record<string, string>>({});

  async function refresh() {
    try {
      setKeys((await getGeminiKeys()).keys);
    } catch {
      setKeys([]);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function save() {
    setBusy("save");
    try {
      const res = await setGeminiKeys(draft);
      setKeys(res.keys);
      setDraft("");
      setEditing(false);
      setResults({});
      toast.success(`Đã lưu ${res.count} key.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "lưu thất bại");
    } finally {
      setBusy("");
    }
  }

  async function test() {
    setBusy("test");
    try {
      const res = await testGeminiKeys();
      setKeys(res.keys);
      setResults(Object.fromEntries(res.results.map((r) => [
        r.masked,
        r.ok ? `✓ ${r.latency_ms} ms` : `✗ ${r.error}${r.detail ? ` — ${r.detail.slice(0, 80)}` : ""}`,
      ])));
      const ok = res.results.filter((r) => r.ok).length;
      const text = `${ok}/${res.results.length} key dùng được.`;
      if (ok === res.results.length) toast.success(text); else toast.warning(text);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "kiểm tra thất bại");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="settings-panel__section">
      <div className="settings-panel__label">Gemini API keys</div>
      <div className="settings-panel__hint">
        Dùng cho phân tích video mẫu, và thay CLI cho auto-prompt / vision / chat khi provider là Gemini.
        Nhiều key: hết quota key này tự chuyển sang key kế.
      </div>
      {keys === null ? (
        <div className="settings-panel__hint">Đang tải…</div>
      ) : keys.length === 0 && !editing ? (
        <div className="settings-panel__hint">Chưa có key.</div>
      ) : (
        <ul className="gemini-keys">
          {keys.map((k) => (
            <li key={k.masked} className={`gemini-keys__row${k.parked ? " gemini-keys__row--parked" : ""}`}>
              <code>{k.masked}</code>
              <span className="gemini-keys__state">
                {results[k.masked]
                  ?? (k.parked ? `tạm nghỉ ${Math.ceil(k.parked_for_s / 60)} phút${k.last_error ? ` — ${k.last_error.slice(0, 60)}` : ""}`
                    : k.calls > 0 ? `${k.calls} lần gọi` : "sẵn sàng")}
              </span>
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <>
          <textarea
            className="gemini-keys__textarea"
            rows={5}
            value={draft}
            placeholder={"Dán key, mỗi dòng một key (hoặc cách nhau bằng dấu phẩy).\nDanh sách này THAY THẾ danh sách cũ."}
            onChange={(e) => setDraft(e.target.value)}
            disabled={busy !== ""}
          />
          <div className="gemini-keys__actions">
            <button type="button" className="gemini-keys__btn gemini-keys__btn--primary" onClick={save} disabled={busy !== ""}>
              {busy === "save" ? "Đang lưu…" : "Lưu key"}
            </button>
            <button type="button" className="gemini-keys__btn" onClick={() => { setEditing(false); setDraft(""); }} disabled={busy !== ""}>
              Huỷ
            </button>
          </div>
        </>
      ) : (
        <div className="gemini-keys__actions">
          <button type="button" className="gemini-keys__btn" onClick={() => setEditing(true)} disabled={busy !== ""}>
            {keys && keys.length > 0 ? "Thay danh sách key" : "Thêm key"}
          </button>
          {keys && keys.length > 0 && (
            <button type="button" className="gemini-keys__btn" onClick={test} disabled={busy !== ""}>
              {busy === "test" ? "Đang kiểm tra…" : "Kiểm tra tất cả"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
