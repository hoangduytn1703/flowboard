import { useEffect, useRef, useState } from "react";
import { listBoardRequests, mediaUrl } from "../../api/client";
import type { FlowNode } from "../../store/board";
import { useQuicktoolStore } from "../../store/quicktool";
import { toast } from "../../store/toast";
import { hasMedia, isBusy, type ClipRoles } from "../roles";
import {
  FLOW_SLOW_AFTER_S, MUSE_MAX_VIDEOS, MUSE_URL, clockOf, isPortrait916, museBatches, museMessage,
  orderMuseFiles, slugOf, stillFileName, type MuseScene,
} from "../muse";

const MAX_FILE_BYTES = 200 * 1024 * 1024; // /api/reference-video/upload

/** When each running Flow clip of the board was sent (its request's
 * `created_at`, ms), by video node id. Polled while any clip is running —
 * the node itself only says "running", not since when. */
export function useFlowWaits(boardId: number | null, busyIds: string[]): Record<string, number> {
  const [since, setSince] = useState<Record<string, number>>({});
  const key = [...busyIds].sort().join(",");
  useEffect(() => {
    if (boardId === null || !key) { setSince({}); return; }
    let live = true;
    const load = () => listBoardRequests(boardId, { active: true })
      .then(({ items }) => {
        if (!live) return;
        const next: Record<string, number> = {};
        for (const r of items) {
          if (r.node_id === null || (r.type !== "gen_video" && r.type !== "gen_video_omni")) continue;
          const t = Date.parse(r.created_at);
          const id = String(r.node_id);
          if (!isNaN(t) && (next[id] === undefined || t < next[id])) next[id] = t;
        }
        setSince(next);
      })
      .catch(() => undefined);
    void load();
    const timer = setInterval(load, 15_000);
    return () => { live = false; clearInterval(timer); };
  }, [boardId, key]);
  return since;
}

/** `Date.now()`, refreshed every `everyMs` while `active` (the waiting clocks). */
export function useNow(active: boolean, everyMs = 5000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(timer);
  }, [active, everyMs]);
  return now;
}

/** Seconds a scene clip has been waiting on Flow; null when it is not running. */
export function flowWaitS(node: FlowNode | null, waits: Record<string, number>, now: number): number | null {
  if (!node || !isBusy(node) || node.data.autoPromptStatus === "pending") return null;
  const t = waits[node.id];
  return t === undefined ? null : Math.max(0, (now - t) / 1000);
}

/** "Cảnh 3 - Cận kết cấu" → "Cận kết cấu". */
function sceneTitle(title: unknown): string {
  return String(title ?? "").replace(/^\s*Cảnh\s*\d+\s*[-–—:·]\s*/i, "").trim();
}

function extOf(type: string): string {
  if (type.includes("png")) return "png";
  if (type.includes("webp")) return "webp";
  return "jpg";
}

async function stillBlob(mediaId: string): Promise<Blob> {
  const res = await fetch(mediaUrl(mediaId));
  if (!res.ok) throw new Error(`không tải được ảnh (${res.status})`);
  return res.blob();
}

/** The clipboard takes PNG only; scene stills are JPEG. */
async function asPng(blob: Blob): Promise<Blob> {
  if (blob.type === "image/png") return blob;
  const bmp = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  canvas.getContext("2d")?.drawImage(bmp, 0, 0);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("không đổi được ảnh sang PNG"))), "image/png"));
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function probeVideo(url: string): Promise<{ width: number; height: number; duration: number }> {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    v.preload = "metadata";
    v.muted = true;
    v.onloadedmetadata = () => resolve({ width: v.videoWidth, height: v.videoHeight, duration: v.duration || 0 });
    v.onerror = () => resolve({ width: 0, height: 0, duration: 0 });
    v.src = url;
  });
}

interface PickedFile {
  key: string;
  file: File;
  url: string;
  width: number;
  height: number;
  duration: number;
  /** The scene it goes onto; null = skip. */
  scene: number | null;
}

/** Which scene each attached still was, in message order — kept per clip so
 * the clips Muse sends back can be matched after a trip to muse.ai or a reload. */
function loadBatch(boardId: number | null): number[] {
  if (boardId === null) return [];
  try {
    const raw = localStorage.getItem(`flowboard.muse.batch.${boardId}`);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((n): n is number => typeof n === "number") : [];
  } catch {
    return [];
  }
}

function saveBatch(boardId: number | null, batch: number[]) {
  if (boardId === null) return;
  try { localStorage.setItem(`flowboard.muse.batch.${boardId}`, JSON.stringify(batch)); } catch { /* per-viewer convenience */ }
}

export interface MuseFocus {
  scene: number;
  /** Bumped on every click, so the same scene can be asked for twice. */
  nonce: number;
}

/**
 * Step 4 — "🎬 Làm video bằng Muse": scene clips made in Muse (Meta) when
 * Flow is slow or drops them. Muse has no API (it is a chat assistant), so
 * this is a one-round-trip bridge: ① tick the scenes, ② one ready message +
 * the scene stills in order (copy or download), ③ drop the clips Muse sends
 * back and they land on the right scenes. A Flow render still running on a
 * scene is cancelled when its Muse clip goes on.
 */
export function MuseBridge({ roles, productName, boardName, boardId, focus, waits, now }: {
  roles: ClipRoles;
  productName: string;
  boardName: string;
  boardId: number | null;
  focus: MuseFocus | null;
  waits: Record<string, number>;
  now: number;
}) {
  const attachMuseVideo = useQuicktoolStore((s) => s.attachMuseVideo);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [batch, setBatch] = useState<number[]>(() => loadBatch(boardId));
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [attaching, setAttaching] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [showText, setShowText] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLElement>(null);
  const filesRef = useRef<PickedFile[]>([]);
  filesRef.current = files;

  const scenes = roles.scenes.filter((s) => s.video);
  const slug = slugOf(boardName || productName);

  function stateOf(s: (typeof scenes)[number]) {
    const v = s.video;
    const wait = flowWaitS(v, waits, now);
    if (!hasMedia(s.image)) return { tone: "idle", text: "chưa có ảnh cảnh (Bước 3)", needs: false, usable: false };
    if (wait !== null) {
      const slow = wait >= FLOW_SLOW_AFTER_S;
      return { tone: slow ? "error" : "busy", text: `Flow đang chạy ${clockOf(wait)}${slow ? " — chậm" : ""}`, needs: slow, usable: true };
    }
    if (isBusy(v)) return { tone: "busy", text: "Flow đang chạy", needs: false, usable: true };
    if (v?.data.status === "error") return { tone: "error", text: "Flow bỏ lượt / lỗi", needs: true, usable: true };
    if (hasMedia(v)) {
      return { tone: "done", text: v?.data.uploadedFrom === "muse" ? "đã có video Muse" : v?.data.uploaded ? "đã có video của bạn" : "đã có video Flow", needs: false, usable: true };
    }
    return { tone: "idle", text: "chưa có video", needs: true, usable: true };
  }

  const needing = scenes.filter((s) => stateOf(s).needs).map((s) => s.index);

  // Opened from a tile ("Làm cảnh này bằng Muse"): open, tick that scene, scroll here.
  useEffect(() => {
    if (!focus) return;
    setOpen(true);
    setSelected((prev) => {
      const next = prev.size ? new Set(prev) : new Set(needing);
      next.add(focus.scene);
      return next;
    });
    requestAnimationFrame(() => boxRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.nonce]);

  // Object URLs of the dropped clips live until they are attached or dropped.
  useEffect(() => () => { for (const f of filesRef.current) URL.revokeObjectURL(f.url); }, []);

  function toggleOpen() {
    if (!open && selected.size === 0) {
      const usable = scenes.filter((s) => stateOf(s).usable && !hasMedia(s.video)).map((s) => s.index);
      setSelected(new Set(needing.length ? needing : usable));
    }
    setOpen(!open);
  }

  const chosen: MuseScene[] = scenes
    .filter((s) => selected.has(s.index) && stateOf(s).usable)
    .map((s) => ({ index: s.index, title: sceneTitle(s.image.data.title), prompt: String(s.video?.data.prompt ?? "") }));
  const parts = museBatches(chosen);
  const messages = parts.map((p, i) => museMessage(productName, p, i + 1, parts.length));

  function remember() {
    const order = chosen.map((s) => s.index);
    setBatch(order);
    saveBatch(boardId, order);
  }

  async function copyMessage(i: number) {
    remember();
    try {
      await navigator.clipboard.writeText(messages[i]);
      toast.success(parts.length > 1
        ? `Đã copy tin nhắn ${i + 1}/${parts.length}. Dán vào Muse, đính kèm ảnh ${i * MUSE_MAX_VIDEOS + 1}–${i * MUSE_MAX_VIDEOS + parts[i].length} theo thứ tự rồi gửi.`
        : `Đã copy tin nhắn. Dán vào Muse, đính kèm ${chosen.length} ảnh theo thứ tự (anh-1, anh-2…) rồi gửi.`);
    } catch {
      setShowText(true);
      toast.warning("Trình duyệt không cho copy tự động — bôi đen tin nhắn bên dưới rồi Ctrl+C.");
    }
  }

  async function copyStill(sceneIndex: number) {
    const s = scenes.find((x) => x.index === sceneIndex);
    const id = s && hasMedia(s.image) ? String(s.image.data.mediaId) : null;
    if (!id) return;
    try {
      const png = await asPng(await stillBlob(id));
      await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
      toast.success(`Đã copy ảnh cảnh ${sceneIndex} — bấm vào ô chat của Muse rồi Ctrl+V.`);
    } catch (err) {
      toast.error(`Không copy được ảnh: ${err instanceof Error ? err.message : "lỗi"}. Dùng nút ⬇ để tải ảnh.`);
    }
  }

  async function downloadStills(only?: number) {
    remember();
    setDownloading(true);
    try {
      const list = only === undefined ? chosen : chosen.filter((s) => s.index === only);
      for (const s of list) {
        const scene = scenes.find((x) => x.index === s.index);
        if (!scene || !hasMedia(scene.image)) continue;
        const blob = await stillBlob(String(scene.image.data.mediaId));
        const position = chosen.findIndex((c) => c.index === s.index) + 1;
        saveBlob(blob, stillFileName(slug, position, s.index, extOf(blob.type)));
        // Chrome asks once before a page saves several files; spaced saves keep the order.
        await new Promise((r) => setTimeout(r, 350));
      }
      if (only === undefined) toast.success(`Đã tải ${list.length} ảnh (anh-1… theo đúng thứ tự trong tin nhắn).`);
    } catch (err) {
      toast.error(`Không tải được ảnh: ${err instanceof Error ? err.message : "lỗi"}`);
    } finally {
      setDownloading(false);
    }
  }

  async function addFiles(list: FileList | File[] | null) {
    const incoming = orderMuseFiles(Array.from(list ?? []).filter((f) =>
      f.type.startsWith("video/") || /\.(mp4|mov|webm|m4v)$/i.test(f.name)));
    if (!incoming.length) {
      toast.warning("Chỉ nhận file video (mp4 / mov / webm).");
      return;
    }
    const probed = await Promise.all(incoming.map(async (file) => {
      const url = URL.createObjectURL(file);
      return { key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`, file, url, ...(await probeVideo(url)), scene: null as number | null };
    }));
    setFiles((prev) => {
      // Match in message order: the k-th clip Muse sent → the k-th still attached.
      const order = (batch.length ? batch : chosen.map((s) => s.index)).filter((n) => scenes.some((s) => s.index === n));
      const taken = new Set(prev.map((f) => f.scene).filter((n): n is number => n !== null));
      const free = order.filter((n) => !taken.has(n));
      const next = probed.map((f) => ({ ...f, scene: free.shift() ?? null }));
      return [...prev, ...next];
    });
  }

  function setScene(key: string, scene: number | null) {
    setFiles((prev) => prev.map((f) => (f.key === key ? { ...f, scene } : f)));
  }

  function removeFile(key: string) {
    setFiles((prev) => {
      const gone = prev.find((f) => f.key === key);
      if (gone) URL.revokeObjectURL(gone.url);
      return prev.filter((f) => f.key !== key);
    });
  }

  const assigned = files.filter((f) => f.scene !== null);
  const dupes = new Set(assigned.map((f) => f.scene).filter((n, i, a) => a.indexOf(n) !== i));
  const tooBig = files.filter((f) => f.file.size > MAX_FILE_BYTES);
  const canAttach = assigned.length > 0 && dupes.size === 0 && !assigned.some((f) => f.file.size > MAX_FILE_BYTES) && !attaching;

  async function attach() {
    const running = assigned
      .map((f) => scenes.find((s) => s.index === f.scene))
      .filter((s): s is (typeof scenes)[number] => !!s && isBusy(s.video));
    if (running.length && !window.confirm(
      `Cảnh ${running.map((s) => s.index).join(", ")} vẫn đang chạy trên Flow. Dừng chờ Flow và dùng video Muse cho ${running.length > 1 ? "các cảnh này" : "cảnh này"}?\n`
      + "(Nếu Flow vẫn làm xong lượt đó thì credit vẫn có thể bị trừ — chỉ là kết quả không được dùng.)")) return;
    setAttaching(true);
    let ok = 0;
    const failed: number[] = [];
    try {
      for (const f of assigned) {
        const done = await attachMuseVideo(f.scene as number, f.file);
        if (done) {
          ok += 1;
          URL.revokeObjectURL(f.url);
          setFiles((prev) => prev.filter((x) => x.key !== f.key));
        } else {
          failed.push(f.scene as number);
        }
      }
    } finally {
      setAttaching(false);
    }
    if (ok) toast.success(`Đã gắn ${ok} video Muse vào cảnh${failed.length ? "" : " — không tốn credit Flow"}.`);
    if (failed.length) toast.error(`Không gắn được video vào cảnh ${failed.join(", ")} — ${useQuicktoolStore.getState().error ?? "thử lại"}.`);
  }

  const sceneOptions = scenes.map((s) => s.index);

  return (
    <section ref={boxRef} className={`qt-card qt-muse${open ? " qt-muse--open" : ""}`}>
      <button type="button" className="qt-muse__head" onClick={toggleOpen} aria-expanded={open}>
        <span className="qt-muse__title">🎬 Làm video bằng Muse <small>(khi Flow chậm hoặc bỏ lượt)</small></span>
        <span className="qt-muse__summary">
          {needing.length ? `${needing.length} cảnh nên làm bằng Muse` : "Không tốn credit Flow · mỗi clip ~10 giây"}
          <span className="qt-muse__chev">{open ? "▴" : "▾"}</span>
        </span>
      </button>

      {open && (
        <div className="qt-muse__body">
          <p className="qt-card__hint">
            Muse (Meta) làm video từ chính ảnh cảnh của bạn. Muse không có API nên làm 3 bước, một lượt cho cả clip:
            chọn cảnh → gửi <strong>một tin nhắn</strong> kèm ảnh cho Muse → thả các video Muse trả về vào đây.
            Muse làm tối đa {MUSE_MAX_VIDEOS} video mỗi tin nhắn; tài khoản miễn phí có hạn mức theo tuần.
          </p>

          <div className="qt-muse__step">
            <div className="qt-muse__stepnum">1</div>
            <div className="qt-muse__stepbody">
              <strong>Chọn cảnh cần video</strong>
              <ul className="qt-muse__scenes">
                {scenes.map((s) => {
                  const st = stateOf(s);
                  const pos = chosen.findIndex((c) => c.index === s.index);
                  return (
                    <li key={s.image.id} className={`qt-muse__scene${selected.has(s.index) && st.usable ? " qt-muse__scene--on" : ""}`}>
                      <label>
                        <input type="checkbox" disabled={!st.usable} checked={selected.has(s.index) && st.usable}
                               onChange={(e) => setSelected((prev) => {
                                 const next = new Set(prev);
                                 if (e.target.checked) next.add(s.index); else next.delete(s.index);
                                 return next;
                               })} />
                        {hasMedia(s.image) ? <img src={mediaUrl(String(s.image.data.mediaId))} alt="" /> : <span className="qt-muse__noimg">—</span>}
                        <span className="qt-muse__scenetext">
                          <span><b>Cảnh {s.index}</b>{sceneTitle(s.image.data.title) ? ` · ${sceneTitle(s.image.data.title)}` : ""}</span>
                          <span className={`qt-muse__state qt-muse__state--${st.tone}`}>{st.text}</span>
                        </span>
                      </label>
                      {pos >= 0 && <span className="qt-muse__pos" title="Thứ tự ảnh trong tin nhắn">ảnh {pos + 1}</span>}
                      {st.usable && (
                        <span className="qt-muse__sceneacts">
                          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Copy ảnh, rồi Ctrl+V vào ô chat Muse"
                                  onClick={() => void copyStill(s.index)}>📋 Ảnh</button>
                          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Tải ảnh cảnh này" disabled={pos < 0 || downloading}
                                  onClick={() => void downloadStills(s.index)}>⬇</button>
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>

          <div className="qt-muse__step">
            <div className="qt-muse__stepnum">2</div>
            <div className="qt-muse__stepbody">
              <strong>Gửi cho Muse</strong>
              {chosen.length === 0 ? (
                <p className="qt-posts__need">Chọn ít nhất một cảnh có ảnh.</p>
              ) : (
                <>
                  <div className="qt-row qt-muse__acts">
                    {messages.map((_, i) => (
                      <button key={i} type="button" className="qt-btn qt-btn--accent" onClick={() => void copyMessage(i)}>
                        📋 Copy tin nhắn{parts.length > 1 ? ` ${i + 1}/${parts.length}` : ""} ({parts[i].length} video)
                      </button>
                    ))}
                    <button type="button" className="qt-btn" disabled={downloading} onClick={() => void downloadStills()}>
                      {downloading ? "Đang tải ảnh…" : `⬇ Tải ${chosen.length} ảnh cảnh`}
                    </button>
                    <a className="qt-btn qt-btn--ghost" href={MUSE_URL} target="_blank" rel="noreferrer">↗ Mở Muse</a>
                  </div>
                  <ol className="qt-muse__howto">
                    <li>Mở Muse, dán tin nhắn vào ô chat.</li>
                    <li>Đính kèm ảnh <b>đúng thứ tự</b>: {chosen.map((c, i) => `ảnh ${i + 1} = cảnh ${c.index}`).join(", ")} (file tải về tên <code>anh-1-canh-…</code>; hoặc bấm "📋 Ảnh" từng cảnh rồi Ctrl+V).</li>
                    <li>Gửi, chờ Muse trả video, tải từng video về theo thứ tự Video 1, Video 2…</li>
                  </ol>
                  <button type="button" className="qt-link" onClick={() => setShowText(!showText)}>
                    {showText ? "Ẩn tin nhắn" : "Xem tin nhắn sẽ gửi"}
                  </button>
                  {showText && messages.map((m, i) => (
                    <textarea key={i} className="qt-textarea qt-muse__text" readOnly rows={Math.min(16, m.split("\n").length + 1)} value={m}
                              onFocus={(e) => e.currentTarget.select()} />
                  ))}
                </>
              )}
            </div>
          </div>

          <div className="qt-muse__step">
            <div className="qt-muse__stepnum">3</div>
            <div className="qt-muse__stepbody">
              <strong>Thả video Muse vào đây</strong>
              <div
                className={`qt-muse__drop${dragOver ? " qt-muse__drop--over" : ""}`}
                role="button"
                tabIndex={0}
                onClick={() => fileRef.current?.click()}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileRef.current?.click(); } }}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); void addFiles(e.dataTransfer.files); }}
              >
                Kéo thả các video Muse vào đây, hoặc bấm để chọn (chọn được nhiều file một lần).
                <small>Video tự xếp vào cảnh theo thứ tự tên file / lúc tải về; sai thì đổi ở ô "Gắn vào".</small>
              </div>
              <input ref={fileRef} type="file" multiple hidden accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
                     onChange={(e) => { void addFiles(e.target.files); e.target.value = ""; }} />

              {files.length > 0 && (
                <ul className="qt-muse__files">
                  {files.map((f) => {
                    const target = f.scene === null ? null : scenes.find((s) => s.index === f.scene) ?? null;
                    return (
                      <li key={f.key} className="qt-muse__file">
                        <video src={f.url} muted playsInline controls preload="metadata" />
                        <div className="qt-muse__fileinfo">
                          <span className="qt-muse__filename" title={f.file.name}>{f.file.name}</span>
                          <small>
                            {f.duration ? `${f.duration.toFixed(1).replace(".", ",")} s` : "?"}
                            {f.width ? ` · ${f.width}×${f.height}` : ""} · {(f.file.size / 1024 / 1024).toFixed(1).replace(".", ",")} MB
                          </small>
                          {f.width > 0 && !isPortrait916(f.width, f.height) && (
                            <small className="qt-muse__warn">Không phải khung dọc 9:16 — khi ghép sẽ được cắt hoặc thêm viền đen cho vừa.</small>
                          )}
                          {f.file.size > MAX_FILE_BYTES && <small className="qt-muse__warn">File quá 200 MB.</small>}
                          <label className="qt-muse__assign">
                            Gắn vào
                            <select value={f.scene ?? ""} onChange={(e) => setScene(f.key, e.target.value ? Number(e.target.value) : null)}>
                              <option value="">— Bỏ qua —</option>
                              {sceneOptions.map((n) => {
                                const s = scenes.find((x) => x.index === n);
                                const note = s && isBusy(s.video) ? " · đang chạy Flow (sẽ dừng)" : s && hasMedia(s.video) ? " · thay video đang có" : "";
                                return <option key={n} value={n}>Cảnh {n}{note}</option>;
                              })}
                            </select>
                          </label>
                          {f.scene !== null && dupes.has(f.scene) && <small className="qt-muse__warn">Hai video cùng gắn vào cảnh {f.scene}.</small>}
                          {target && !hasMedia(target.image) && <small className="qt-muse__warn">Cảnh này chưa có ảnh cảnh.</small>}
                        </div>
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title="Bỏ file này" onClick={() => removeFile(f.key)}>✕</button>
                      </li>
                    );
                  })}
                </ul>
              )}
              {files.length > 0 && (
                <div className="qt-row qt-muse__acts">
                  <button type="button" className="qt-btn qt-btn--accent" disabled={!canAttach} onClick={() => void attach()}>
                    {attaching ? "Đang gắn video…" : `✓ Gắn ${assigned.length} video vào cảnh`}
                  </button>
                  {dupes.size > 0 && <small className="qt-muse__warn">Mỗi cảnh chỉ một video.</small>}
                  {tooBig.length > 0 && <small className="qt-muse__warn">{tooBig.length} file quá 200 MB.</small>}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
