import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { createPortal } from "react-dom";
import {
  deleteDubLinks, importDubLinks, isTextFile, listDubLinks, queueDubLinks, unqueueDubLinks,
  type DubLink, type DubLinkLibrary, type DubLinkQueue, type DubLinkStatus,
} from "../../api/dub";
import { toast } from "../../store/toast";
import { PageEmpty, PageLoading } from "../PageState";
import { pageList } from "./DubJobsDialog";
import { VoiceField } from "../VoiceField";

const PER_PAGE = 12;
const MAX_FILE_BYTES = 2 * 1024 * 1024;
type Filter = "all" | "new" | "queue" | "done" | "review" | "error" | "other";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "new", label: "Chưa lồng tiếng" },
  { key: "queue", label: "Trong hàng đợi" },
  { key: "done", label: "Đã lồng tiếng" },
  { key: "review", label: "Chờ sửa" },
  { key: "error", label: "Lỗi" },
  { key: "other", label: "Không phải video" },
];

function matches(l: DubLink, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "queue") return l.status === "waiting" || l.status === "running";
  return l.status === f;
}

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function site(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^(www|m)\./, "");
    if (/douyin/.test(host)) return "Douyin";
    if (/tiktok/.test(host)) return "TikTok";
    if (/youtu/.test(host)) return "YouTube";
    if (/bilibili|b23\.tv/.test(host)) return "Bilibili";
    if (/xiaohongshu|xhslink/.test(host)) return "Xiaohongshu";
    if (/kuaishou/.test(host)) return "Kuaishou";
    if (/facebook|fb\./.test(host)) return "Facebook";
    if (/instagram/.test(host)) return "Instagram";
    return host;
  } catch {
    return "Link";
  }
}

/** Notepad's "Unicode" saves UTF-16 with a BOM; everything else is read as UTF-8. */
async function readText(f: File): Promise<string> {
  const buf = new Uint8Array(await f.arrayBuffer());
  if (buf[0] === 0xff && buf[1] === 0xfe) return new TextDecoder("utf-16le").decode(buf);
  if (buf[0] === 0xfe && buf[1] === 0xff) return new TextDecoder("utf-16be").decode(buf);
  return new TextDecoder("utf-8").decode(buf);
}

function StatusPill({ l }: { l: DubLink }) {
  const j = l.job;
  switch (l.status) {
    case "done":
      return <span className="qt-dubjobs__pill is-done">✓ Đã lồng tiếng{l.done_count > 1 ? ` ×${l.done_count}` : ""}</span>;
    case "review":
      return <span className="qt-dubjobs__pill is-review">Chờ sửa bản dịch</span>;
    case "error":
      return <span className="qt-dubjobs__pill is-error" title={l.error ?? ""}>Lỗi</span>;
    case "waiting":
      return <span className="qt-dubjobs__pill is-waiting">⏳ Chờ trong hàng đợi</span>;
    case "running":
      return j?.status === "running" && j.progress > 0 && j.phase && !/^Chờ/.test(j.phase)
        ? <span className="qt-dubjobs__pill is-working">Đang lồng tiếng {j.progress}%</span>
        : <span className="qt-dubjobs__pill is-working">{j?.phase || "Chờ đến lượt"}</span>;
    case "other":
      return <span className="qt-dubjobs__pill is-other">Không phải video</span>;
    default:
      return <span className="qt-dubjobs__pill is-new">Chưa lồng tiếng</span>;
  }
}

const statusHint: Record<DubLinkStatus, string> = {
  new: "", waiting: "", running: "", review: "Đã dịch — mở để xem lại bản dịch rồi render", done: "", error: "", other: "",
};

/**
 * "📚 Thư viện link": import .txt / .md files (anything in them — only the links count), see for every
 * link whether its video was already dubbed, and queue the ones still to do: they run one video at a
 * time with the settings of the page's form (voice, music, look preset, channel).
 */
export function DubLinksDialog({ settings, settingsLabel, onVoice, importFiles, onOpenJob, onOpenClip, onQueued, onClose }: {
  /** the page form's dub settings, used for every link queued from here */
  settings: Omit<DubLinkQueue, "ids">;
  /** pick the voice right here (it is the page's voice, remembered as the default) */
  onVoice?: (voice: string) => void;
  settingsLabel: string;
  /** files dropped on the page: imported as soon as the dialog opens */
  importFiles?: File[] | null;
  onOpenJob: (jobId: string) => void;
  onOpenClip: (boardId: number) => void;
  onQueued: () => void;
  onClose: () => void;
}) {
  const [lib, setLib] = useState<DubLinkLibrary | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<"" | "import" | "queue" | "delete" | "unqueue">("");
  const [confirm, setConfirm] = useState<"" | "delete" | "redo">("");
  const [dragOver, setDragOver] = useState(false);
  const [lastImport, setLastImport] = useState<string>("");
  const fileInput = useRef<HTMLInputElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const imported = useRef(false);

  const refresh = () => listDubLinks().then(setLib).catch((e) => toast.error(errMessage(e)));
  useEffect(() => { void refresh(); search.current?.focus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (importFiles?.length && !imported.current) { imported.current = true; void importFrom(importFiles); }
  }, [importFiles]); // eslint-disable-line react-hooks/exhaustive-deps
  // the queue moves on its own: keep the states fresh while anything waits or runs
  const moving = !!lib?.links.some((l) => l.status === "waiting" || l.status === "running");
  useEffect(() => {
    if (!moving) return;
    const t = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(t);
  }, [moving]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (confirm) setConfirm("");
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, confirm]);
  useEffect(() => setPage(1), [query, filter]);

  const links = lib?.links ?? [];
  // rows that left the library leave the selection too
  useEffect(() => {
    setPicked((p) => {
      const alive = new Set(links.map((l) => l.id));
      const next = new Set([...p].filter((id) => alive.has(id)));
      return next.size === p.size ? p : next;
    });
  }, [lib]); // eslint-disable-line react-hooks/exhaustive-deps

  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.key, links.filter((l) => matches(l, f.key)).length])) as Record<Filter, number>, [links]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return links.filter((l) => matches(l, filter) && (!q || `${l.label} ${l.url} ${l.source} ${l.job?.title ?? ""}`.toLowerCase().includes(q)));
  }, [links, filter, query]);
  const pages = Math.max(1, Math.ceil(shown.length / PER_PAGE));
  const current = Math.min(page, pages);
  const rows = shown.slice((current - 1) * PER_PAGE, current * PER_PAGE);
  const pickable = (l: DubLink) => l.status !== "running";
  const pageIds = rows.filter(pickable).map((l) => l.id);
  const pageAll = pageIds.length > 0 && pageIds.every((id) => picked.has(id));
  const todo = links.filter((l) => l.status === "new" && l.video).map((l) => l.id);
  const pickedLinks = links.filter((l) => picked.has(l.id));
  const pickedDone = pickedLinks.filter((l) => l.status === "done" || l.status === "review");
  const pickedWaiting = pickedLinks.filter((l) => l.status === "waiting");
  const pickedOdd = pickedLinks.filter((l) => !l.video);
  const toQueue = pickedLinks.filter((l) => l.status !== "waiting" && l.video);

  const toggle = (id: number) => {
    setConfirm("");
    setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };
  const togglePage = () => {
    setConfirm("");
    setPicked((p) => { const n = new Set(p); for (const id of pageIds) { if (pageAll) n.delete(id); else n.add(id); } return n; });
  };

  async function importFrom(list: FileList | File[]) {
    const files = [...list];
    const text = files.filter(isTextFile);
    if (!text.length) { toast.warning("Chỉ nhận file chữ .txt / .md."); return; }
    const big = text.filter((f) => f.size > MAX_FILE_BYTES);
    if (big.length) toast.warning(`Bỏ qua ${big.map((f) => f.name).join(", ")} — file chữ lớn hơn 2 MB.`);
    const ok = text.filter((f) => f.size <= MAX_FILE_BYTES);
    if (!ok.length) return;
    setBusy("import");
    try {
      const payload = await Promise.all(ok.map(async (f) => ({ name: f.name, text: await readText(f) })));
      const r = await importDubLinks(payload);
      const names = r.files.map((f) => `${f.name}: ${f.links} link`).join(" · ");
      if (!r.found) {
        setLastImport(`${names} — không thấy link nào trong file.`);
        toast.warning("Không thấy link nào trong file.");
      } else {
        const old = r.existing.length;
        setLastImport(`${names} → ${r.added.length} link mới${old ? `, ${old} link đã có trong thư viện` : ""}.`);
        toast.success(`Đã thêm ${r.added.length} link mới vào thư viện${old ? ` (${old} link đã có sẵn)` : ""}.`);
      }
      const fresh = await listDubLinks();
      setLib(fresh);
      // the new links (video sites only) come pre-picked: one click puts them in the queue
      const added = new Set(r.added);
      const pre = fresh.links.filter((l) => added.has(l.id) && l.video && l.status === "new").map((l) => l.id);
      if (pre.length) { setPicked(new Set(pre)); setFilter("all"); setQuery(""); }
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }

  async function startQueue(ids: number[]) {
    if (!ids.length) return;
    setBusy("queue");
    setConfirm("");
    try {
      const r = await queueDubLinks({ ...settings, ids });
      if (r.queued) toast.success(`Đã đưa ${r.queued} link vào hàng đợi — lồng tiếng lần lượt từng video, xong video này tự sang video kế.`);
      if (r.skipped.length) toast.warning(`${r.skipped.length} link bỏ qua: ${[...new Set(r.skipped.map((s) => s.reason))].join("; ")}`);
      setPicked(new Set());
      onQueued();
      await refresh();
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }

  function onStart() {
    const redo = toQueue.filter((l) => l.status === "done" || l.status === "review");
    if (redo.length && confirm !== "redo") { setConfirm("redo"); return; }
    void startQueue(toQueue.map((l) => l.id));
  }

  async function remove() {
    setBusy("delete");
    try {
      const r = await deleteDubLinks([...picked]);
      toast.success(`Đã xoá ${r.deleted} link khỏi thư viện — video đã lồng tiếng và clip vẫn còn.`);
      setPicked(new Set());
      setConfirm("");
      await refresh();
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }

  async function unqueue() {
    setBusy("unqueue");
    try {
      const r = await unqueueDubLinks(pickedWaiting.map((l) => l.id));
      toast.info(`Đã bỏ ${r.unqueued} link khỏi hàng đợi.`);
      await refresh();
    } catch (e) {
      toast.error(errMessage(e));
    } finally {
      setBusy("");
    }
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    if (e.dataTransfer.files?.length) void importFrom(e.dataTransfer.files);
  }

  const waiting = lib?.counts.waiting ?? 0;
  const running = lib?.counts.running ?? 0;
  const done = lib?.counts.done ?? 0;

  return createPortal(
    <div className="project-modal-backdrop" onClick={onClose}>
      <div className={`project-modal qt-dubjobs qt-dublinks${dragOver ? " is-drag" : ""}`} role="dialog" aria-modal="true" aria-label="Thư viện link lồng tiếng"
           onClick={(e) => e.stopPropagation()}
           onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); e.stopPropagation(); setDragOver(true); } }}
           onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false); }}
           onDrop={onDrop}>
        <div className="qt-dubjobs__head">
          <div>
            <h3 className="project-modal__title">📚 Thư viện link lồng tiếng</h3>
            <small className="qt-card__hint">
              {lib ? `${lib.total} link · ${done} đã lồng tiếng · ${lib.counts.new ?? 0} chưa${waiting + running ? ` · ${waiting + running} trong hàng đợi` : ""}` : "Đang tải…"}
            </small>
          </div>
          <button type="button" className="qt-dubjobs__close" aria-label="Đóng" onClick={onClose}>×</button>
        </div>

        <div className="qt-dublinks__drop" onClick={() => fileInput.current?.click()} role="button" tabIndex={0}
             onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.current?.click(); } }}>
          <span className="qt-dublinks__dropicon" aria-hidden="true">{busy === "import" ? "⏳" : "📥"}</span>
          <span className="qt-dublinks__droptext">
            <strong>{busy === "import" ? "Đang đọc file…" : "Thả file .txt / .md vào đây, hoặc bấm để chọn"}</strong>
            <small>Trong file có gì cũng được (ghi chú, danh sách chép từ chat, đoạn share Douyin…) — tool lấy ra mọi link, link đã có trong thư viện không thêm lại. Chọn được nhiều file một lúc.</small>
          </span>
          <input ref={fileInput} type="file" accept=".txt,.md,.markdown,.text,text/plain,text/markdown" multiple hidden
                 onChange={(e) => { const fs = e.target.files ? [...e.target.files] : []; e.target.value = ""; if (fs.length) void importFrom(fs); }} />
        </div>
        {lastImport && <div className="qt-dublinks__last">✓ {lastImport}</div>}

        <div className="qt-dubjobs__tools">
          <input ref={search} className="qt-dubjobs__search" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="🔍 Tìm theo link, ghi chú, tên file…" aria-label="Tìm link" />
          <div className="qt-dubjobs__filters" role="tablist" aria-label="Lọc theo trạng thái">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" role="tab" aria-selected={filter === f.key}
                      className={`qt-chip${filter === f.key ? " qt-chip--on" : ""}`} disabled={f.key !== "all" && !counts[f.key]}
                      onClick={() => setFilter(f.key)}>
                {f.label} <span className="qt-dubjobs__count">{counts[f.key]}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="qt-dubjobs__body">
          {!lib ? (
            <PageLoading compact text="Đang tải thư viện link…" />
          ) : rows.length ? (
            <table className="qt-dubjobs__table">
              <thead>
                <tr>
                  <th className="qt-dubjobs__check">
                    <input type="checkbox" checked={pageAll} disabled={!pageIds.length} onChange={togglePage}
                           aria-label="Chọn cả trang này" title="Chọn cả trang này" />
                  </th>
                  <th>Link</th><th>Trạng thái</th><th>Từ file</th><th aria-label="Thao tác" />
                </tr>
              </thead>
              <tbody>
                {rows.map((l) => (
                  <tr key={l.id} className={picked.has(l.id) ? "is-picked" : undefined}>
                    <td className="qt-dubjobs__check">
                      <input type="checkbox" checked={picked.has(l.id)} disabled={!pickable(l)} onChange={() => toggle(l.id)}
                             aria-label={`Chọn ${l.url}`} title={pickable(l) ? "Chọn" : "Đang lồng tiếng"} />
                    </td>
                    <td className="qt-dubjobs__name qt-dublinks__link">
                      <strong title={l.job?.title || l.label || l.url}>{l.job?.title || l.label || site(l.url)}</strong>
                      <small>
                        <span className="qt-dublinks__site">{site(l.url)}</span>
                        <a href={l.url} target="_blank" rel="noreferrer noopener" title={l.url} onClick={(e) => e.stopPropagation()}>{l.url}</a>
                      </small>
                      {!l.video && <small className="qt-dublinks__odd">⚠ không lồng tiếng được — chỉ nhận link TikTok / Douyin / YouTube / Instagram / Facebook / X</small>}
                    </td>
                    <td>
                      <StatusPill l={l} />
                      {statusHint[l.status] && <small className="qt-dublinks__hint">{statusHint[l.status]}</small>}
                      {l.status === "error" && l.error && <small className="qt-dublinks__err" title={l.error}>{l.error}</small>}
                    </td>
                    <td className="qt-dubjobs__num qt-dublinks__src" title={l.source}>{l.source}</td>
                    <td className="qt-dubjobs__act">
                      <div className="qt-dubjobs__btns">
                        {l.job?.job_id && l.status !== "waiting" ? (
                          <button type="button" className="qt-btn qt-btn--small" onClick={() => onOpenJob(l.job!.job_id!)}>Mở</button>
                        ) : l.job?.board_id ? (
                          <button type="button" className="qt-btn qt-btn--small" onClick={() => onOpenClip(l.job!.board_id!)}>Mở clip</button>
                        ) : null}
                        <button type="button" className="qt-dubjobs__trash" disabled={l.status === "running"}
                                title={l.status === "running" ? "Đang lồng tiếng" : "Xoá khỏi thư viện (video đã lồng tiếng vẫn giữ)"}
                                aria-label={`Xoá ${l.url} khỏi thư viện`}
                                onClick={() => { setPicked(new Set([l.id])); setConfirm("delete"); }}>🗑</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <PageEmpty compact icon={links.length ? "🔍" : "📚"} title={links.length ? "Không có link nào khớp" : "Thư viện chưa có link nào"}>
              {links.length ? "Đổi từ khoá hoặc bộ lọc trạng thái." : "Thả một file .txt / .md có link video vào khung phía trên."}
            </PageEmpty>
          )}
        </div>

        {lib && (picked.size > 0 || todo.length > 0) && (
          <div className={`qt-dubjobs__bar qt-dublinks__bar${confirm ? " is-confirm" : ""}${confirm === "redo" ? " is-redo" : ""}`} role="region" aria-label="Lồng tiếng các link đã chọn">
            {confirm === "delete" ? (
              <>
                <span>Xoá <b>{picked.size}</b> link khỏi thư viện? Chỉ xoá dòng link — video đã lồng tiếng và clip vẫn giữ nguyên.</span>
                <div className="qt-dubjobs__barbtns">
                  <button type="button" className="qt-btn qt-btn--small" disabled={!!busy} onClick={() => setConfirm("")}>Huỷ</button>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={!!busy} onClick={() => void remove()}>
                    {busy === "delete" ? "Đang xoá…" : `🗑 Xoá ${picked.size} link`}
                  </button>
                </div>
              </>
            ) : confirm === "redo" ? (
              <>
                <span>
                  <b>{pickedDone.length}</b> link đã lồng tiếng rồi (hoặc đang chờ sửa) — làm lại sẽ tạo thêm video / clip mới cho chúng.
                </span>
                <div className="qt-dubjobs__barbtns">
                  <button type="button" className="qt-btn qt-btn--small" disabled={!!busy} onClick={() => setConfirm("")}>Huỷ</button>
                  {toQueue.length > pickedDone.length && (
                    <button type="button" className="qt-btn qt-btn--small" disabled={!!busy}
                            onClick={() => void startQueue(toQueue.filter((l) => l.status !== "done" && l.status !== "review").map((l) => l.id))}>
                      Chỉ chạy {toQueue.length - pickedDone.length} link chưa làm
                    </button>
                  )}
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!!busy} onClick={() => void startQueue(toQueue.map((l) => l.id))}>
                    Vẫn làm lại cả {toQueue.length} link
                  </button>
                </div>
              </>
            ) : (
              <>
                <span>
                  {picked.size ? <>Đã chọn <b>{picked.size}</b></> : <>Chưa chọn link nào</>}
                  {todo.length > 0 && !(todo.length === picked.size && todo.every((id) => picked.has(id))) && (
                    <button type="button" className="qt-link" onClick={() => { setPicked(new Set(todo)); setConfirm(""); }}>Chọn cả {todo.length} link chưa lồng tiếng</button>
                  )}
                  {picked.size > 0 && <button type="button" className="qt-link" onClick={() => setPicked(new Set())}>Bỏ chọn</button>}
                  {pickedOdd.length > 0 && <small className="qt-dublinks__odd">{pickedOdd.length} link không phải TikTok / Douyin / YouTube / IG / FB / X — chỉ xoá được, không lồng tiếng</small>}
                </span>
                <div className="qt-dubjobs__barbtns">
                  {pickedWaiting.length > 0 && (
                    <button type="button" className="qt-btn qt-btn--small" disabled={!!busy} onClick={() => void unqueue()}>Bỏ {pickedWaiting.length} link khỏi hàng đợi</button>
                  )}
                  {picked.size > 0 && (
                    <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={!!busy} onClick={() => setConfirm("delete")}>🗑 Xoá khỏi thư viện</button>
                  )}
                  <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!!busy || !toQueue.length} onClick={onStart}>
                    {busy === "queue" ? "Đang xếp hàng…" : `🎙 Lồng tiếng ${toQueue.length || ""} link`.replace("  ", " ")}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
        {lib && !confirm && onVoice && (settings.mode ?? "dub") === "dub" && (
          <div className="qt-dublinks__voice">
            <span className="qt-dublinks__voicelabel" title="Giọng chọn ở đây thành giọng mặc định cho lần sau (cả form Lồng tiếng, theo tài khoản)">
              🎙 Giọng đọc cho link xếp hàng <small>· tool nhớ làm mặc định</small>
            </span>
            <VoiceField value={settings.voice} onChange={onVoice} disabled={!!busy} compact
                        sampleText="Các bạn ơi, hôm nay mình kể cho các bạn nghe một chuyện cực kỳ thú vị." />
          </div>
        )}
        {lib && toQueue.length > 0 && !confirm && (
          <small className="qt-dublinks__settings">Cài đặt dùng cho các link này (lấy từ form Lồng tiếng): {settingsLabel}</small>
        )}

        {pages > 1 && (
          <nav className="qt-pager qt-dubjobs__pager" aria-label="Phân trang link">
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current <= 1} onClick={() => setPage(current - 1)}>← Trước</button>
            {pageList(current, pages).map((n, i) => (n === "gap"
              ? <span key={`g${i}`} className="qt-pager__info">…</span>
              : <button key={n} type="button" aria-current={n === current ? "page" : undefined}
                        className={`qt-pager__num${n === current ? " qt-pager__num--active" : ""}`} onClick={() => setPage(n)}>{n}</button>))}
            <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" disabled={current >= pages} onClick={() => setPage(current + 1)}>Sau →</button>
            <span className="qt-pager__info">{(current - 1) * PER_PAGE + 1}–{Math.min(current * PER_PAGE, shown.length)} / {shown.length}</span>
          </nav>
        )}
        {dragOver && <div className="qt-dublinks__dragmask">Thả file .txt / .md để lấy link</div>}
      </div>
    </div>,
    document.body,
  );
}
