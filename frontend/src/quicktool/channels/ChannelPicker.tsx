import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { listChannels, type Channel } from "../../api/channels";

let cache: { at: number; list: Channel[] } | null = null;

/** The channel list, shared by every picker on screen (30 s cache). */
export function useChannels(): [Channel[], () => Promise<void>] {
  const [list, setList] = useState<Channel[]>(cache?.list ?? []);
  async function load() {
    try {
      const rows = await listChannels();
      cache = { at: Date.now(), list: rows };
      setList(rows);
    } catch {
      /* no channels is a fine state */
    }
  }
  useEffect(() => {
    if (cache && Date.now() - cache.at < 30_000) { setList(cache.list); return; }
    void load();
  }, []);
  return [list, load];
}

export function invalidateChannels() {
  cache = null;
}

/**
 * "Kênh (không bắt buộc)" — one select used by the new-clip dialog, step 1,
 * the post writer and step 5. Shows a link to make the first channel.
 */
export function ChannelPicker({
  value, onChange, label = "Kênh / page", disabled = false, hint,
}: {
  value: number | null;
  onChange: (id: number | null) => void;
  label?: string;
  disabled?: boolean;
  hint?: ReactNode;
}) {
  const [channels] = useChannels();
  const picked = channels.find((c) => c.id === value) ?? null;
  return (
    <label className="qt-field">
      <span>{label} <small>(không bắt buộc)</small></span>
      {channels.length === 0 ? (
        <small className="qt-card__hint">Chưa có kênh nào — <Link to="/channels">tạo kênh</Link> để AI nhớ page của bạn bán gì, nói giọng gì.</small>
      ) : (
        <select value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
          <option value="">— Không gắn kênh —</option>
          {channels.map((c) => <option key={c.id} value={c.id}>{c.name}{c.brainstorm ? " · có định hướng" : ""}</option>)}
        </select>
      )}
      {picked && (hint ?? (picked.brainstorm
        ? <small className="qt-card__hint">AI bám theo định hướng của kênh: {picked.brainstorm.summary || picked.brainstorm.positioning}</small>
        : <small className="qt-card__hint">Kênh chưa có định hướng — sau {Math.max(0, 3 - picked.posts)} bài nữa AI sẽ brainstorm.</small>))}
    </label>
  );
}
