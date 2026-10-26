import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import "./backgroundTasks.css";

/** One piece of heavy work the agent is doing (`GET /api/running`). */
export interface RunningItem {
  key: string;
  /** dub | clean | clip | flow, or an in-page operation kind (services/op_tracker.TRACKED) */
  kind: string;
  title: string;
  detail: string;
  /** 0–100 when the job knows it */
  progress: number | null;
  started_at: string | null;
  /** the page to go back to */
  link: string;
}

interface DoneItem extends RunningItem {
  doneAt: number;
  /** how it ended (GET /api/running/outcome) */
  ok: boolean;
  message: string;
}

async function outcomeOf(item: RunningItem): Promise<{ ok: boolean; message: string }> {
  try {
    return await api<{ ok: boolean; message: string }>(`/api/running/outcome?key=${encodeURIComponent(item.key)}`);
  } catch {
    return { ok: true, message: "Đã xong — bấm để xem kết quả" };
  }
}

/** Pages starting heavy work fire this so the badge picks it up at once. */
export const RUNNING_EVENT = "flowboard:running";
export function announceRunning(): void {
  window.dispatchEvent(new Event(RUNNING_EVENT));
}

const POLL_ACTIVE_MS = 4000;
const POLL_IDLE_MS = 15000;
/** A finished task stays on the badge this long ("✓ … xong — mở"). */
const DONE_KEEP_MS = 3 * 60 * 1000;

const KIND_ICON: Record<string, string> = {
  dub: "🎙", clean: "🧽", clip: "🎬", flow: "🖼",
  // in-page operations (services/op_tracker.TRACKED)
  post_write: "✍️", post_batch: "✍️", ai: "✨", bundle: "🎁", channel: "📣", product: "🛍", clip_setup: "🎬",
  video: "🎞", publish: "🚀", upload: "⬆", media: "🗂",
};
const iconOf = (kind: string) => KIND_ICON[kind] ?? "⏳";
/** "AI đang viết bài" → "AI viết bài", "Đang đọc … link" → "Đọc … link": the name of a task that has ended. */
function doneTitle(title: string): string {
  const t = title.replace(/^AI đang /, "AI ").replace(/^Đang /, "");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** The newest in-page operation of a kind (`GET /api/running/latest`); `claim`
 * marks a finished one as taken so it is restored only once. */
export interface LatestOp {
  op_id?: string;
  status?: "running" | "done" | "error";
  message?: string;
  started_at?: string;
  result?: unknown;
}
export function latestOp(kind: string, claim = false): Promise<LatestOp> {
  return api<LatestOp>(`/api/running/latest?kind=${encodeURIComponent(kind)}${claim ? "&claim=true" : ""}`);
}

/** True when the task's page is the one on screen (then it needs no badge). */
function isHere(link: string, pathname: string, search: string): boolean {
  const [path, query = ""] = link.split("?");
  if (query) return pathname === path && new URLSearchParams(search).toString().includes(query);
  // /clips/12/videos → being anywhere inside clip 12 counts.
  const clip = /^\/clips\/(\d+)/.exec(path);
  if (clip) return pathname.startsWith(`/clips/${clip[1]}`);
  return pathname === path;
}

/**
 * The bottom-right "đang chạy" badge: while dubbing, subtitle erasing or Flow
 * renders run, leaving their page shows this badge; a click goes back. When a
 * task ends while you are elsewhere it turns into "✓ … xong" for a few
 * minutes, still clickable. Hidden when there is nothing to report or the
 * only task is on the current page.
 */
export function BackgroundTasks() {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const [items, setItems] = useState<RunningItem[]>([]);
  const [done, setDone] = useState<DoneItem[]>([]);
  const [open, setOpen] = useState(false);
  const prev = useRef<Map<string, RunningItem>>(new Map());
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const { items: now } = await api<{ items: RunningItem[] }>("/api/running");
      const keys = new Set(now.map((i) => i.key));
      const finished = [...prev.current.values()].filter((i) => !keys.has(i.key));
      if (finished.length) {
        const at = Date.now();
        const ended = await Promise.all(finished.map(async (f) => ({ ...f, doneAt: at, ...(await outcomeOf(f)) })));
        setDone((d) => [...ended, ...d.filter((x) => !finished.some((f) => f.key === x.key))]);
      }
      prev.current = new Map(now.map((i) => [i.key, i]));
      setItems(now);
    } catch {
      /* logged out / agent restarting: keep what we had */
    }
  }, []);

  // Poll fast while something runs, slowly otherwise; at once on page change
  // and when a page announces new work.
  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), items.length ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    return () => window.clearInterval(t);
  }, [load, items.length]);
  useEffect(() => { void load(); }, [load, pathname]);
  useEffect(() => {
    const on = () => window.setTimeout(() => void load(), 600);
    window.addEventListener(RUNNING_EVENT, on);
    return () => window.removeEventListener(RUNNING_EVENT, on);
  }, [load]);
  // Forget old "xong" entries.
  useEffect(() => {
    if (!done.length) return;
    const t = window.setInterval(() => setDone((d) => d.filter((x) => Date.now() - x.doneAt < DONE_KEEP_MS)), 15000);
    return () => window.clearInterval(t);
  }, [done.length]);
  // Close the list on an outside click.
  useEffect(() => {
    if (!open) return;
    const on = (e: MouseEvent) => { if (panel.current && !panel.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", on);
    return () => document.removeEventListener("mousedown", on);
  }, [open]);

  const away = items.filter((i) => !isHere(i.link, pathname, search));
  const doneAway = done.filter((i) => !isHere(i.link, pathname, search));
  // Seeing the page of a finished task counts as having seen it.
  useEffect(() => {
    setDone((d) => (d.some((x) => isHere(x.link, pathname, search)) ? d.filter((x) => !isHere(x.link, pathname, search)) : d));
  }, [pathname, search]);

  if (!away.length && !doneAway.length) return null;

  function go(item: RunningItem) {
    setOpen(false);
    setDone((d) => d.filter((x) => x.key !== item.key));
    navigate(item.link);
  }

  const total = away.length + doneAway.length;
  const first = away[0] ?? doneAway[0];
  const running = away.length > 0;
  const failedAway = doneAway.filter((d) => !d.ok);
  const summary = running
    ? (away.length === 1 ? first.title : `${away.length} việc đang chạy`)
    : failedAway.length
      ? (doneAway.length === 1 ? `${doneTitle(first.title)} — lỗi` : `${failedAway.length}/${doneAway.length} việc bị lỗi`)
      : (doneAway.length === 1 ? `${doneTitle(first.title)} — xong` : `${doneAway.length} việc đã xong`);
  const pct = running && away.length === 1 && first.progress !== null ? first.progress : null;

  return (
    <div className="bgt" ref={panel}>
      {open && (
        <div className="bgt__panel" role="dialog" aria-label="Việc đang chạy">
          <div className="bgt__head">
            <strong>Việc đang chạy nền</strong>
            <small>Rời trang không làm mất việc — bấm để quay lại</small>
          </div>
          <ul className="bgt__list">
            {away.map((i) => (
              <li key={i.key}>
                <button type="button" className="bgt__row" onClick={() => go(i)}>
                  <span className="bgt__ico" aria-hidden="true">{iconOf(i.kind)}</span>
                  <span className="bgt__text">
                    <span className="bgt__title">{i.title}</span>
                    <span className="bgt__detail">{i.detail}</span>
                    {i.progress !== null && <span className="bgt__bar"><span style={{ width: `${Math.max(3, i.progress)}%` }} /></span>}
                  </span>
                  <span className="bgt__go">Mở →</span>
                </button>
              </li>
            ))}
            {doneAway.map((i) => (
              <li key={i.key}>
                <button type="button" className={`bgt__row ${i.ok ? "bgt__row--done" : "bgt__row--failed"}`} onClick={() => go(i)}>
                  <span className="bgt__ico" aria-hidden="true">{i.ok ? "✓" : "!"}</span>
                  <span className="bgt__text">
                    <span className="bgt__title">{doneTitle(i.title)}</span>
                    <span className="bgt__detail" title={i.message}>{i.message || (i.ok ? "Đã xong" : "Bị lỗi")}</span>
                  </span>
                  <span className="bgt__go">{i.ok ? "Xem →" : "Mở →"}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <button
        type="button"
        className={`bgt__pill${running ? "" : failedAway.length ? " bgt__pill--failed" : " bgt__pill--done"}`}
        onClick={() => (total === 1 ? go(first) : setOpen((o) => !o))}
        title={total === 1
          ? `${first.title} — ${"message" in first && !running ? (first as DoneItem).message : first.detail}. Bấm để quay lại.`
          : "Xem các việc đang chạy"}
      >
        {running
          ? <span className="bgt__spin" aria-hidden="true" />
          : failedAway.length
            ? <span className="bgt__check bgt__check--failed" aria-hidden="true">!</span>
            : <span className="bgt__check" aria-hidden="true">✓</span>}
        <span className="bgt__label">{summary}</span>
        {pct !== null && <span className="bgt__pct">{pct}%</span>}
        {total > 1 && <span className="bgt__count">{total}</span>}
      </button>
    </div>
  );
}
