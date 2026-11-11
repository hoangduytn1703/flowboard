import { useEffect, useState } from "react";

/**
 * "Dừng" for work running on the agent. One press is enough: the button greys out and says "Đang dừng…" at once
 * (no second click needed, none possible) until the work is gone — the agent kills what it runs within a moment.
 * ``stopping`` = the agent's own word that a stop is under way (another tab pressed it, or the page was reloaded).
 */
export function StopButton({ onStop, stopping = false, label = "Dừng", busyLabel = "Đang dừng…", className = "qt-btn qt-btn--small qt-btn--danger", title }: {
  /** asks the agent to stop; a rejected promise re-enables the button */
  onStop: () => Promise<unknown> | void;
  stopping?: boolean;
  label?: string;
  busyLabel?: string;
  className?: string;
  title?: string;
}) {
  const [pressed, setPressed] = useState(false);
  // the stop did not take (the request failed, or the work went on for long): let the seller press again
  useEffect(() => {
    if (!pressed || stopping) return;
    const t = window.setTimeout(() => setPressed(false), 8000);
    return () => window.clearTimeout(t);
  }, [pressed, stopping]);
  const busy = pressed || stopping;
  return (
    <button type="button" className={className} disabled={busy} aria-busy={busy} title={busy ? "Đang dừng — chờ một chút" : title}
            onClick={() => {
              setPressed(true);
              void Promise.resolve().then(onStop).catch(() => setPressed(false));
            }}>
      {busy ? busyLabel : label}
    </button>
  );
}
