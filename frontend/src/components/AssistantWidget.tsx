import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { mediaUrl } from "../api/client";
import {
  cancelAssistantTask, clearAssistant, confirmAssistantTask, getAssistant, sendAssistant,
  type AssistantMessage, type AssistantState, type AssistantTask,
} from "../api/assistant";
import { toast } from "../store/toast";
import { announceRunning } from "./BackgroundTasks";
import "./assistant.css";

const SIZE = 56;
const MARGIN = 10;
const GAP = 12;
const POS_KEY = "dflow.assistant.pos";
const SUGGESTIONS = [
  "Viết tập tiếp theo của loạt truyện cho kênh của mình rồi lên lịch 20h tối nay",
  "Viết 3 bài khác nhau về sản phẩm mới nhất cho kênh của mình, mỗi bài 1 ảnh",
  "Tạo người mẫu nữ Việt Nam sang chảnh, tóc dài, lưu lại cho mình",
  "Thêm sản phẩm từ link này rồi tạo clip quảng cáo: ",
];

// "?assistant=1" asks for the chat open. Kept a few seconds at module level too, in case the app mounts again
// right after loading (it did until 30/10: App mounted the pages before the first board load, then again after).
let openAskedUntil = 0;

type Pos = { x: number; y: number };
/** Kept as offsets from the nearest corner, so the button stays put when the window is resized. */
type Anchor = { h: "l" | "r"; ox: number; v: "t" | "b"; oy: number };

function clamp(p: Pos): Pos {
  return {
    x: Math.min(Math.max(MARGIN, p.x), window.innerWidth - SIZE - MARGIN),
    y: Math.min(Math.max(MARGIN, p.y), window.innerHeight - SIZE - MARGIN),
  };
}
function toAnchor(p: Pos): Anchor {
  const right = p.x + SIZE / 2 > window.innerWidth / 2;
  const bottom = p.y + SIZE / 2 > window.innerHeight / 2;
  return { h: right ? "r" : "l", ox: right ? window.innerWidth - p.x - SIZE : p.x, v: bottom ? "b" : "t", oy: bottom ? window.innerHeight - p.y - SIZE : p.y };
}
function fromAnchor(a: Anchor): Pos {
  return clamp({ x: a.h === "r" ? window.innerWidth - a.ox - SIZE : a.ox, y: a.v === "b" ? window.innerHeight - a.oy - SIZE : a.oy });
}
function loadAnchor(): Anchor {
  try {
    const a = JSON.parse(window.localStorage.getItem(POS_KEY) || "null");
    if (a && (a.h === "l" || a.h === "r") && typeof a.ox === "number") return a as Anchor;
  } catch { /* private mode / bad value */ }
  // bottom right, one row above the "việc đang chạy" badge (.bgt sits at right 22 / bottom 22)
  return { h: "r", ox: 22, v: "b", oy: 22 + 58 };
}
function saveAnchor(p: Pos) {
  try { window.localStorage.setItem(POS_KEY, JSON.stringify(toAnchor(p))); } catch { /* private mode */ }
}

/** Never sit on the "việc đang chạy" badge (.bgt, bottom right): if they overlap, move up above it. */
function avoidBadge(p: Pos): Pos {
  const el = document.querySelector(".bgt");
  if (!el) return p;
  const r = el.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return p;
  const overlap = p.x < r.right + GAP && p.x + SIZE > r.left - GAP && p.y < r.bottom + GAP && p.y + SIZE > r.top - GAP;
  return overlap ? clamp({ x: p.x, y: r.top - SIZE - GAP }) : p;
}

/** A fresh Flow render is reported done a moment before its file is cached: retry a few times. */
function RetryImg({ src }: { src: string }) {
  const [attempt, setAttempt] = useState(0);
  const url = attempt ? `${src}?r=${attempt}` : src;
  return <img src={url} alt="" onError={() => { if (attempt < 8) window.setTimeout(() => setAttempt((a) => a + 1), 1500); }} />;
}

/** **bold** in the assistant's text, nothing else (no HTML from the model). */
function rich(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>);
}

function elapsed(iso: string | null, now: number): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * "🤖 Trợ lý DFlow": a round button bottom right (drag it anywhere — it keeps
 * clear of the "việc đang chạy" badge) that opens a chat. A reply can start a
 * background task (create_model today) that carries on when the page closes;
 * the chat follows it and says when it is done.
 */
export function AssistantWidget() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [pos, setPos] = useState<Pos>(() => fromAnchor(loadAnchor()));
  const [open, setOpen] = useState(() => Date.now() < openAskedUntil);
  const [state, setState] = useState<AssistantState | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [unread, setUnread] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [deciding, setDeciding] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const drag = useRef<{ x: number; y: number; origin: Pos; moved: boolean; toggle: boolean } | null>(null);
  const listEnd = useRef<HTMLDivElement>(null);
  const known = useRef<Map<number, AssistantTask["status"]>>(new Map());

  const running = (state?.tasks ?? []).some((t) => t.status === "running");

  const load = useCallback(async () => {
    try {
      const st = await getAssistant();
      // a task that finished while the chat was closed: say it, mark the button
      for (const t of st.tasks) {
        const before = known.current.get(t.id);
        if (before === "running" && t.status !== "running") {
          if (t.status === "done") toast.success(`Trợ lý: ${t.title} — xong.`, { duration: 7000 });
          else toast.error(`Trợ lý: ${t.title} — lỗi: ${t.error ?? ""}`);
          setUnread(true);
        }
        known.current.set(t.id, t.status);
      }
      setState(st);
    } catch { /* not signed in yet / agent restarting */ }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!open && !running) return;
    const t = window.setInterval(() => void load(), running ? 2000 : 15000);
    return () => window.clearInterval(t);
  }, [open, running, load]);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [running]);
  // "?assistant=1" (the running badge links here) opens the chat
  useEffect(() => {
    if (params.get("assistant")) {
      openAskedUntil = Date.now() + 3000;
      setOpen(true);
      const next = new URLSearchParams(params);
      next.delete("assistant");
      setParams(next, { replace: true });
    }
  }, [params, setParams]);
  useEffect(() => { if (open) { setUnread(false); void load(); } }, [open, load]);
  useEffect(() => { listEnd.current?.scrollIntoView({ block: "end" }); }, [state?.messages.length, pending, open]);
  // keep inside the window, and off the running badge when it shows up / grows
  useEffect(() => {
    const fit = () => setPos((p) => { const q = avoidBadge(clamp(p)); return q.x === p.x && q.y === p.y ? p : q; });
    const t = window.setInterval(fit, 1000);
    window.addEventListener("resize", fit);
    return () => { window.clearInterval(t); window.removeEventListener("resize", fit); };
  }, []);

  function onPointerDown(e: React.PointerEvent, toggle: boolean) {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button") && !toggle) return; // header buttons stay buttons
    drag.current = { x: e.clientX, y: e.clientY, origin: pos, moved: false, toggle };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    d.moved = true;
    setPos(clamp({ x: d.origin.x + dx, y: d.origin.y + dy }));
  }
  function onPointerUp() {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.moved) {
      setPos((p) => { const q = avoidBadge(clamp(p)); saveAnchor(q); return q; });
    } else if (d.toggle) {
      setOpen((o) => !o);
    }
  }

  async function send(text: string) {
    const msg = text.trim();
    if (!msg || sending) return;
    setSending(true);
    setPending(msg);
    setDraft("");
    try {
      const r = await sendAssistant(msg);
      if (r.task) {
        known.current.set(r.task.id, "running");
        announceRunning();
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      setDraft(msg);
    } finally {
      setPending(null);
      setSending(false);
    }
  }

  /** "✅ Làm luôn" / "Huỷ" on a plan that waits for the go-ahead. */
  async function decide(taskId: number, go: boolean) {
    setDeciding(taskId);
    try {
      if (go) {
        known.current.set(taskId, "running");
        await confirmAssistantTask(taskId);
        announceRunning();
      } else {
        await cancelAssistantTask(taskId);
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setDeciding(null);
    }
  }

  async function clearChat() {
    if (!confirmClear) { setConfirmClear(true); return; }
    setConfirmClear(false);
    try {
      await clearAssistant();
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }

  // the panel opens next to the button, on the side that has room
  const W = Math.min(390, window.innerWidth - 2 * MARGIN);
  const H = Math.min(580, window.innerHeight - 2 * MARGIN);
  const onRight = pos.x + SIZE / 2 > window.innerWidth / 2;
  const left = Math.min(Math.max(MARGIN, onRight ? pos.x + SIZE - W : pos.x), window.innerWidth - W - MARGIN);
  const above = pos.y - GAP - H >= MARGIN;
  const below = pos.y + SIZE + GAP + H <= window.innerHeight - MARGIN;
  const top = above ? pos.y - GAP - H : below ? pos.y + SIZE + GAP : MARGIN;

  const tasks = new Map((state?.tasks ?? []).map((t) => [t.id, t]));
  const messages = state?.messages ?? [];

  return (
    <>
      <button type="button" className={`dfa-launch${open ? " is-open" : ""}${running ? " is-busy" : ""}`}
              style={{ left: pos.x, top: pos.y }} aria-label="Trợ lý AI" title="Trợ lý AI — bấm để chat, kéo để dời chỗ"
              onPointerDown={(e) => onPointerDown(e, true)} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
              onClick={(e) => { if (e.detail === 0) setOpen((o) => !o); /* Enter / Space; a mouse click toggles in onPointerUp */ }}>
        {open ? (
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" /></svg>
        ) : (
          <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
            <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z" fill="currentColor" opacity="0.95" />
            <path d="M12 6.4l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9z" fill="#ff6a2b" />
          </svg>
        )}
        {unread && !open && <span className="dfa-launch__dot" />}
      </button>

      {open && (
        <section className="dfa-panel" style={{ left, top, width: W, height: H }} role="dialog" aria-label="Trợ lý DFlow">
          <header className="dfa-head" onPointerDown={(e) => onPointerDown(e, false)} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
                  title="Kéo để dời chỗ">
            <img src="/dflow-logo.png" alt="" className="dfa-head__logo" />
            <div className="dfa-head__title">
              <strong>Trợ lý DFlow</strong>
              <small>{running ? "đang làm việc nền…" : "nói việc cần làm, mình làm giúp"}</small>
            </div>
            <span className="dfa-head__tag">Premium</span>
            <button type="button" className="dfa-head__btn" onClick={() => void clearChat()} onBlur={() => setConfirmClear(false)}
                    title="Xoá cuộc trò chuyện (người mẫu đã tạo vẫn giữ)">{confirmClear ? "Xoá thật?" : "🗑"}</button>
            <button type="button" className="dfa-head__btn" onClick={() => setOpen(false)} aria-label="Thu gọn">—</button>
          </header>

          <div className="dfa-body">
            {messages.length === 0 && !pending && (
              <div className="dfa-hello">
                <strong>Chào bạn 👋</strong>
                <p>Mình là trợ lý của DFlow. Nói việc cần làm, mình chạy ngầm giúp: <b>viết bài Facebook</b> (cả tập tiếp của loạt truyện) kèm ảnh,
                  <b>lên lịch / tự đăng lên Page</b>, <b>thêm sản phẩm từ link</b>, <b>tạo clip quảng cáo</b> có kịch bản theo sản phẩm, <b>tạo người mẫu AI</b>.
                  Gõ sai tên kênh / loạt cũng không sao.</p>
                <div className="dfa-chips">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" className="dfa-chip"
                            onClick={() => (s.endsWith(": ") ? setDraft(s) : void send(s))}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m: AssistantMessage) => {
              const task = m.task_id ? tasks.get(m.task_id) : undefined;
              const showTask = task && task.status === "running" && m.role === "assistant" && !m.data.media_id && !m.data.links;
              const pics = m.data.media_ids?.length ? m.data.media_ids : m.data.media_id ? [m.data.media_id] : [];
              const links = m.data.links?.length ? m.data.links : m.data.link ? [{ label: m.data.link_label || "Mở", href: m.data.link }] : [];
              const waiting = m.data.confirm && task?.status === "pending";
              return (
                <div key={m.id} className={`dfa-msg dfa-msg--${m.role}${m.data.error ? " is-error" : ""}`}>
                  <div className="dfa-msg__text">{rich(m.text)}</div>
                  {(pics.length > 0 || links.length > 0) && (
                    <div className="dfa-result">
                      {pics.length > 0 && (
                        <div className={`dfa-pics${pics.length > 1 ? " dfa-pics--many" : ""}`}>
                          {pics.slice(0, 4).map((id) => <RetryImg key={id} src={mediaUrl(id)} />)}
                        </div>
                      )}
                      {links.length > 0 && (
                        <div className="dfa-links">
                          {links.map((lk, i) => (
                            <button key={lk.href} type="button" className={`dfa-link dfa-link--${i % 2 ? "b" : "a"}`} onClick={() => navigate(lk.href)}>
                              {lk.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {waiting && (
                    <div className="dfa-confirm">
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={deciding === task!.id}
                              onClick={() => void decide(task!.id, true)}>✅ Làm luôn</button>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={deciding === task!.id}
                              onClick={() => void decide(task!.id, false)}>Huỷ</button>
                    </div>
                  )}
                  {m.data.confirm && task?.status === "canceled" && <small className="dfa-note">Đã huỷ kế hoạch này.</small>}
                  {showTask && (
                    <div className="dfa-task">
                      <span className="dfa-spin" aria-hidden="true" />
                      <span>{task.step || "Đang làm…"}</span>
                      <time>{elapsed(task.started_at, now)}</time>
                    </div>
                  )}
                </div>
              );
            })}
            {pending && (
              <>
                <div className="dfa-msg dfa-msg--user"><div className="dfa-msg__text">{pending}</div></div>
                <div className="dfa-msg dfa-msg--assistant dfa-msg--typing"><span /><span /><span /></div>
              </>
            )}
            <div ref={listEnd} />
          </div>

          <form className="dfa-input" onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={2} disabled={sending}
                      placeholder="VD: viết tập 7 loạt hệ mặt trời cho kênh Chúng ta hay tò mò, lên lịch 20h tối nay"
                      onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(draft); } }} />
            <button type="submit" className="dfa-send" disabled={sending || !draft.trim()} aria-label="Gửi">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M4 12l15-7-5 15-3-6z" fill="currentColor" /></svg>
            </button>
          </form>
        </section>
      )}
    </>
  );
}
