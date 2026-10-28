import { useEffect, useState } from "react";
import { getFptKey, getGeminiKeys, setFptKey, setGeminiKeys, testGeminiKeys, type GeminiKeyState } from "../api/client";
import { toast } from "../store/toast";

/**
 * Settings → Gemini API keys. Several keys pasted at once; the agent
 * rotates to the next one when a key runs out of quota. Keys are shown
 * masked and never sent back in full.
 */
function restIn(sec: number): string {
  return sec >= 3600 ? `${Math.floor(sec / 3600)} giờ ${Math.ceil((sec % 3600) / 60)} phút` : `${Math.ceil(sec / 60)} phút`;
}

/** Settings → FPT.AI TTS key: the "review phim" voices (Ban Mai…); 100 000 characters a month free at console.fpt.ai. */
function FptKeySection() {
  const [state, setState] = useState<{ set: boolean; masked: string } | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { void getFptKey().then(setState).catch(() => setState({ set: false, masked: "" })); }, []);
  async function save(key: string) {
    setBusy(true);
    try {
      setState(await setFptKey(key));
      setDraft("");
      toast.success(key ? "Đã lưu key FPT.AI — giọng FPT dùng được ở mọi ô chọn giọng." : "Đã bỏ key FPT.AI.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lưu thất bại");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="settings-panel__section">
      <div className="settings-panel__label">FPT.AI — giọng review phim (Ban Mai, Lê Minh…)</div>
      <div className="settings-panel__hint">
        Đăng ký miễn phí ở console.fpt.ai → Text to Speech → lấy API key (gói miễn phí 100.000 ký tự/tháng ≈ 15–40 video ngắn).
        {state?.set ? ` Đang dùng key ${state.masked}.` : " Chưa có key: giọng FPT bị mờ trong ô chọn giọng."}
      </div>
      <div className="gemini-keys__actions">
        <input type="password" className="settings-field__input" value={draft} placeholder={state?.set ? "Dán key mới để thay" : "Dán API key FPT.AI"}
               onChange={(e) => setDraft(e.target.value)} disabled={busy} style={{ flex: "1 1 220px" }} autoComplete="off" />
        <button type="button" className="gemini-keys__btn gemini-keys__btn--primary" onClick={() => void save(draft.trim())} disabled={busy || !draft.trim()}>
          {busy ? "Đang lưu…" : "Lưu key"}
        </button>
        {state?.set && <button type="button" className="gemini-keys__btn" onClick={() => void save("")} disabled={busy}>Bỏ key</button>}
      </div>
    </div>
  );
}

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
    <>
    <div className="settings-panel__section">
      <div className="settings-panel__label">Gemini API keys</div>
      <div className="settings-panel__hint">
        Dùng cho phân tích video mẫu, và thay CLI cho auto-prompt / vision / chat khi provider là Gemini.
        Nhiều key: hết quota key này tự chuyển sang key kế. Quota miễn phí tính theo <b>từng model</b> — giọng đọc Gemini chỉ
        được ~10 câu/ngày/key, hết thì tự sang model TTS dự phòng; video dài nên dùng giọng Edge (không giới hạn).
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
                  ?? (k.parked ? `bị từ chối — nghỉ ${Math.ceil(k.parked_for_s / 60)} phút${k.last_error ? ` — ${k.last_error.slice(0, 60)}` : ""}`
                    : Object.keys(k.models_parked ?? {}).length
                      ? `hết quota: ${Object.entries(k.models_parked ?? {}).map(([m, sec]) => `${m.replace(/^gemini-/, "")}${k.model_limits?.[m] ? ` (${k.model_limits[m]}/ngày)` : ""} · còn ${restIn(sec)}`).join("; ")}${k.calls > 0 ? ` · ${k.calls} lần gọi` : ""}`
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
    <FptKeySection />
    </>
  );
}
