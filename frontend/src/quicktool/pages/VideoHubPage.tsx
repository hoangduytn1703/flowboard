import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { linksIn, uploadDubVideo } from "../../api/dub";
import { editPath, importEditClips, importEditFiles, MAX_EDIT_TOGETHER } from "../../api/edit";
import { useFeature } from "../../lib/features";
import { toast } from "../../store/toast";
import { ClipPickDialog, type PickedClip } from "../dub/ClipPickDialog";
import { giveHandoff } from "../sources/handoff";
import { VideoToolsTabs } from "../VideoToolsTabs";
import "../videohub.css";

/**
 * "🎞 Xử lý video" → "📥 Thêm video" (/tools): the one door for videos you already have. Bring them in once — links,
 * files from this machine, clips of "Clip của tôi" — then say what to do: dub, subtitles only, cut into short videos,
 * edit (frame, background, text…) or wipe text / a logo. The tool opens with the videos already filled in.
 * /tools?do=edit|dub|sub|cut|clean pre-selects what to do (the tabs and the old menu entries land here).
 */
type Action = "dub" | "sub" | "cut" | "edit" | "clean";

interface Video { key: string; name: string; media_id?: string; board_id?: number; state: "up" | "ready" | "error"; error?: string }

const MAX_DUB_LINKS = 5;
const MAX_DUB_VIDEOS = 10;
const MAX_CUT = 10;
const isVideoFile = (f: File) => f.type.startsWith("video/") || /\.(mp4|mov|webm|mkv|m4v)$/i.test(f.name);
const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
const stem = (name: string) => name.replace(/\.[a-z0-9]{2,4}$/i, "");

const ACTIONS: { key: Action; icon: string; title: string; text: string }[] = [
  { key: "dub", icon: "🎙", title: "Lồng tiếng Việt", text: "Bỏ tiếng gốc, đọc lại bằng giọng Việt, có phụ đề." },
  { key: "sub", icon: "💬", title: "Chỉ thêm phụ đề", text: "Giữ tiếng gốc, thêm phụ đề tiếng Việt hoặc đúng lời gốc." },
  { key: "cut", icon: "✂️", title: "Cắt thành video ngắn", text: "AI hoặc bạn chọn đoạn hay — mỗi đoạn thành một video." },
  { key: "edit", icon: "✏️", title: "Chỉnh sửa", text: "Khung 9:16, nền, chữ, che logo, tốc độ, âm lượng — một hay nhiều video cùng kiểu." },
  { key: "clean", icon: "🧽", title: "Xoá chữ / logo", text: "Khoanh vùng hoặc nhờ AI xoá phụ đề cứng — từng video một." },
];

export function VideoHubPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const dubOn = useFeature("dub");
  const cutOn = useFeature("cut");
  const cleanOn = useFeature("clean");
  const grabOn = useFeature("grab");
  const want = params.get("do") as Action | null;
  const [links, setLinks] = useState<string[]>([""]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [pickOpen, setPickOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [going, setGoing] = useState<Action | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const linkInputs = useRef<(HTMLInputElement | null)[]>([]);
  useEffect(() => { document.title = "Xử lý video · DFlow"; }, []);

  const cleanLinks = links.map((l) => l.trim()).filter(Boolean);
  const ready = videos.filter((v) => v.state === "ready" && v.media_id);
  const uploading = videos.some((v) => v.state === "up");
  const total = cleanLinks.length + ready.length;

  // ── links: one per row; several pasted at once split into rows ─────────────
  function setLink(i: number, v: string) {
    setLinks((ls) => ls.map((x, k) => (k === i ? v : x)));
  }
  function addRow(after = links.length - 1) {
    if (links.length >= MAX_CUT) { toast.warning(`Tối đa ${MAX_CUT} link một lượt.`); return; }
    setLinks((ls) => [...ls.slice(0, after + 1), "", ...ls.slice(after + 1)]);
    window.setTimeout(() => linkInputs.current[after + 1]?.focus(), 0);
  }
  function removeRow(i: number) {
    setLinks((ls) => (ls.length > 1 ? ls.filter((_, k) => k !== i) : [""]));
  }
  function onPaste(i: number, e: ClipboardEvent<HTMLInputElement>) {
    const found = linksIn(e.clipboardData.getData("text"));
    if (found.length < 2) return;
    e.preventDefault();
    setLinks((ls) => {
      const merged: string[] = [];
      for (const x of [...ls.slice(0, i), ...found, ...ls.slice(i + 1)]) {
        const v = x.trim();
        if (v && !merged.includes(v)) merged.push(v);
      }
      if (merged.length > MAX_CUT) toast.warning(`Dán ${found.length} link — giữ ${MAX_CUT} link đầu.`);
      return merged.slice(0, MAX_CUT);
    });
  }
  function onKey(i: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); addRow(i); }
    if (e.key === "Backspace" && !links[i] && links.length > 1) {
      e.preventDefault();
      removeRow(i);
      window.setTimeout(() => linkInputs.current[Math.max(0, i - 1)]?.focus(), 0);
    }
  }

  // ── files from this machine: uploaded at once (the tools only take videos already here) ─────────────
  async function addFiles(list: File[]) {
    const files = list.filter(isVideoFile);
    if (!files.length) { toast.warning("Không thấy file video nào (mp4, mov, webm, mkv)."); return; }
    const room = MAX_EDIT_TOGETHER - videos.length;
    if (files.length > room) toast.warning(`Một lượt nhận tối đa ${MAX_EDIT_TOGETHER} video.`);
    const items = files.slice(0, Math.max(0, room)).map((f, k) => ({ file: f, v: { key: `f${Date.now()}-${k}`, name: stem(f.name), state: "up" } as Video }));
    setVideos((vs) => [...vs, ...items.map((x) => x.v)]);
    for (const { file, v } of items) {
      try {
        const r = await uploadDubVideo(file);
        setVideos((vs) => vs.map((x) => (x.key === v.key ? { ...x, state: "ready", media_id: r.media_id } : x)));
      } catch (e) {
        setVideos((vs) => vs.map((x) => (x.key === v.key ? { ...x, state: "error", error: errMessage(e) } : x)));
      }
    }
  }
  function addClips(clips: PickedClip[]) {
    setPickOpen(false);
    setVideos((vs) => {
      const have = new Set(vs.map((v) => v.board_id).filter(Boolean));
      const add = clips.filter((c) => !have.has(c.board_id))
        .map((c) => ({ key: `c${c.board_id}`, name: c.name, media_id: c.media_id, board_id: c.board_id, state: "ready" as const }));
      return [...vs, ...add];
    });
  }
  function onDrop(e: DragEvent<HTMLDivElement>) {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    setDragOver(false);
    void addFiles(Array.from(e.dataTransfer.files));
  }

  // ── what each tool takes ─────────────────────────────────────────────────
  function why(a: Action): string | null {
    if (uploading) return "Đợi các file tải lên xong";
    if (!total) return "Thêm video ở bước ① trước";
    if (a === "dub" || a === "sub") {
      if (cleanLinks.length && ready.length) return "Lồng tiếng nhận link HOẶC video có sẵn trong một lượt — bỏ bớt một loại";
      if (cleanLinks.length > MAX_DUB_LINKS) return `Tối đa ${MAX_DUB_LINKS} link một lượt`;
      if (ready.length > MAX_DUB_VIDEOS) return `Tối đa ${MAX_DUB_VIDEOS} video một lượt`;
    }
    if (a === "cut" && total > MAX_CUT) return `Tối đa ${MAX_CUT} video một lượt`;
    if ((a === "edit" || a === "clean") && cleanLinks.length) return "Chưa nhận link — chọn file từ máy hoặc video trong Clip của tôi (link thì dùng Cắt video trước)";
    if (a === "clean" && ready.length !== 1) return "Xoá chữ / logo làm từng video một — chỉ giữ 1 video";
    return null;
  }
  const shown = ACTIONS.filter((a) => (a.key === "dub" || a.key === "sub" ? dubOn : a.key === "cut" ? cutOn : a.key === "clean" ? cleanOn : dubOn || cutOn));

  async function go(a: Action) {
    if (why(a) || going) return;
    const handVideos = ready.map((v) => ({ media_id: v.media_id!, name: v.name, board_id: v.board_id }));
    if (a === "dub" || a === "sub") {
      giveHandoff({ to: "dub", links: cleanLinks, videos: handVideos, mode: a });
      navigate("/tools/dub");
    } else if (a === "cut") {
      giveHandoff({ to: "cut", links: cleanLinks, videos: handVideos });
      navigate("/tools/cut");
    } else if (a === "clean") {
      giveHandoff({ to: "clean", links: [], videos: handVideos.slice(0, 1) });
      navigate("/tools/clean");
    } else {
      setGoing("edit");
      try {
        const files = ready.filter((v) => !v.board_id).map((v) => ({ media_id: v.media_id!, name: v.name }));
        const boards = ready.filter((v) => v.board_id).map((v) => v.board_id!);
        const ids: string[] = [];
        if (files.length) {
          const r = await importEditFiles(files);
          for (const x of r.errors) toast.error(`${x.name}: ${x.error}`);
          ids.push(...r.job_ids);
        }
        if (boards.length) {
          const r = await importEditClips(boards);
          for (const x of r.errors) toast.warning(`${x.name}: ${x.error}`);
          ids.push(...r.job_ids);
        }
        if (!ids.length) return;
        navigate(editPath(ids), { state: { back: "/clips" } });
      } catch (e) {
        toast.error(errMessage(e));
      } finally {
        setGoing(null);
      }
    }
  }

  return (
    <>
      <header className="qt-header"><span className="qt-header__crumb">🎞 Xử lý video</span></header>
      <VideoToolsTabs />
      <div className={`qt-home vh${dragOver ? " is-dropping" : ""}`}
           onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragOver(true); } }}
           onDragLeave={(e) => { if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false); }}
           onDrop={onDrop}>
        {dragOver && <div className="vh__dropmask"><div>📂 Thả video vào đây</div></div>}
        <input ref={fileInput} type="file" accept="video/*,.mkv" multiple hidden
               onChange={(e) => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />

        <section className="qt-card vh__step">
          <div className="qt-card__eyebrow">① Video nào?</div>
          <h3 className="qt-card__title">Dán link, chọn file, hoặc lấy video đã có</h3>
          <div className="vh__links">
            {links.map((l, i) => (
              <div key={i} className="vh__linkrow">
                <input ref={(el) => { linkInputs.current[i] = el; }} className="qt-input" value={l} aria-label={`Link video ${i + 1}`}
                       placeholder={i === 0 ? "Dán link TikTok / Douyin / YouTube / Facebook / Instagram (dán nhiều link một lúc cũng được)" : "Link tiếp theo…"}
                       onChange={(e) => setLink(i, e.target.value)} onPaste={(e) => onPaste(i, e)} onKeyDown={(e) => onKey(i, e)} />
                {(links.length > 1 || l) && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" aria-label={`Bỏ link ${i + 1}`} onClick={() => removeRow(i)}>×</button>
                )}
              </div>
            ))}
          </div>
          <div className="vh__sources">
            <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => addRow()}>＋ Thêm link</button>
            <button type="button" className="qt-btn" onClick={() => fileInput.current?.click()}>📁 Chọn file từ máy…</button>
            <button type="button" className="qt-btn" onClick={() => setPickOpen(true)}>🎬 Chọn từ Clip của tôi</button>
            {grabOn && <button type="button" className="qt-btn qt-btn--ghost" onClick={() => navigate("/tools/grab")}
                               title="Quét kênh TikTok / YouTube / Douyin, lọc video nhiều view rồi gửi sang đây">📡 Lấy từ kênh…</button>}
          </div>
          {videos.length > 0 && (
            <ul className="vh__videos" aria-live="polite">
              {videos.map((v) => (
                <li key={v.key} className={`is-${v.state}`}>
                  <span className="vh__vname" title={v.name}>{v.board_id ? "🎬" : "📁"} {v.name}</span>
                  <small>{v.state === "up" ? "đang tải lên…" : v.state === "error" ? `⚠ ${v.error ?? "lỗi"}` : v.board_id ? "trong Clip của tôi" : "sẵn sàng"}</small>
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" aria-label={`Bỏ ${v.name}`}
                          onClick={() => setVideos((vs) => vs.filter((x) => x.key !== v.key))}>×</button>
                </li>
              ))}
            </ul>
          )}
          <p className="qt-card__hint">Kéo thả file video vào trang này cũng được.</p>
        </section>

        <section className="qt-card vh__step">
          <div className="qt-card__eyebrow">② Làm gì?</div>
          <h3 className="qt-card__title">{total ? `Với ${total} video này` : "Chọn việc cần làm"}</h3>
          <div className="vh__actions">
            {shown.map((a) => {
              const reason = why(a.key);
              return (
                <button key={a.key} type="button" disabled={!!reason || !!going}
                        className={`vh__action${want === a.key ? " vh__action--want" : ""}`}
                        onClick={() => void go(a.key)} title={reason ?? undefined}>
                  <span className="vh__aicon" aria-hidden="true">{a.icon}</span>
                  <span className="vh__atext">
                    <strong>{going === a.key ? "Đang mở…" : a.title}</strong>
                    <small>{a.text}</small>
                    {reason && total > 0 && <em>{reason}</em>}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      </div>
      {pickOpen && (
        <ClipPickDialog everyClip max={MAX_EDIT_TOGETHER} initial={[]} onClose={() => setPickOpen(false)} onPick={addClips} />
      )}
    </>
  );
}
