import { useState } from "react";
import type { FbStats } from "../../api/schedule";

/** 1284 → "1,3 N" (Vietnamese compact). */
function compact(n: number | undefined): string {
  return new Intl.NumberFormat("vi-VN", { notation: "compact", maximumFractionDigits: 1 }).format(n ?? 0);
}

function seconds(s: number | undefined): string {
  const v = s ?? 0;
  if (v < 60) return `${v.toLocaleString("vi-VN", { maximumFractionDigits: 1 })} s`;
  return `${Math.floor(v / 60)} ph ${Math.round(v % 60)} s`;
}

/** One line under a card: ▶ plays (Reel) or 👁 views, then ❤ 💬 🔁. `dense` (the narrow calendar cards)
 * keeps the lead and only the other figures that are not 0 — the tooltip still says all of them. */
export function StatsLine({ s, dense = false }: { s: FbStats | null | undefined; dense?: boolean }) {
  if (!s) return null;
  const reel = s.plays !== undefined;
  const lead = reel ? `▶️ ${compact(s.plays)}` : s.views !== undefined ? `👁️ ${compact(s.views)}` : null;
  const tip = [reel ? `${s.plays} lượt phát` : s.views !== undefined ? `${s.views} lượt xem` : null,
               `${s.reactions ?? 0} cảm xúc`, `${s.comments ?? 0} bình luận`, `${s.shares ?? 0} chia sẻ`].filter(Boolean).join(" · ");
  // the lead number (plays / views) stands out; each figure is a chip with a colour emoji, not muted text
  return (
    <span className="qt-fbstats" title={`Trên Facebook: ${tip}`}>
      {lead && <span className="qt-fbstats__lead">{lead}</span>}
      {(!dense || (s.reactions ?? 0) > 0) && <span>❤️ {compact(s.reactions)}</span>}
      {(!dense || (s.comments ?? 0) > 0) && <span>💬 {compact(s.comments)}</span>}
      {(!dense || (s.shares ?? 0) > 0) && <span>🔁 {compact(s.shares)}</span>}
    </span>
  );
}

/** The numbers of one post on Facebook, as stat tiles; a Reel adds its watch time and the "still watching" curve. */
export function StatsPanel({ s }: { s: FbStats | null | undefined }) {
  if (!s) return <p className="qt-card__hint">Chưa có số liệu — bấm 🔄 Đồng bộ từ Facebook.</p>;
  const reel = s.plays !== undefined;
  const tiles: [string, string][] = reel
    ? [["Lượt phát", compact(s.plays)], ["Xem trung bình", seconds(s.avg_watch_s)], ["Xem lại", compact(s.replays)],
       ["Theo dõi mới", compact(s.followers)], ["Cảm xúc", compact(s.reactions)], ["Bình luận", compact(s.comments)], ["Chia sẻ", compact(s.shares)]]
    : [...(s.views !== undefined ? [["Lượt xem", compact(s.views)], ["Người xem", compact(s.viewers)], ["Lượt bấm", compact(s.clicks)]] as [string, string][] : []),
       ["Cảm xúc", compact(s.reactions)], ["Bình luận", compact(s.comments)], ["Chia sẻ", compact(s.shares)]];
  return (
    <div className="qt-fbpanel">
      <div className="qt-fbpanel__tiles">
        {tiles.map(([label, value]) => (
          <div key={label} className="qt-fbpanel__tile"><small>{label}</small><strong>{value}</strong></div>
        ))}
      </div>
      {!reel && s.views === undefined && <p className="qt-card__hint">Lượt xem cần quyền read_insights của token Page.</p>}
      {reel && (s.retention?.length ?? 0) > 1 && <RetentionChart points={s.retention!} lengthS={s.length_s ?? 0} />}
      {s.at && <small className="qt-fbpanel__at">Số liệu lúc {new Date(s.at).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })} · cập nhật mỗi lần đồng bộ</small>}
    </div>
  );
}

const W = 300;
const H = 120;
const PAD = { l: 34, r: 8, t: 8, b: 20 };

/** "Còn bao nhiêu % người xem" over the Reel: Facebook's 41 points (0 → 100 % of the video), one line. */
export function RetentionChart({ points, lengthS }: { points: number[]; lengthS: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = points.length - 1;
  const x = (i: number) => PAD.l + (i / n) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - Math.max(0, Math.min(1, v))) * (H - PAD.t - PAD.b);
  const at = (i: number) => (lengthS > 0 ? `${Math.round((i / n) * lengthS)} s` : `${Math.round((i / n) * 100)} %`);
  const pct = (v: number) => `${Math.round(v * 100)} %`;
  const line = points.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(n).toFixed(1)},${y(0).toFixed(1)} L${x(0).toFixed(1)},${y(0).toFixed(1)} Z`;
  // the headline: who is still there a few seconds in, and at the end
  const early = lengthS > 0 ? Math.min(n, Math.max(1, Math.round((3 / lengthS) * n))) : Math.round(n * 0.1);
  const summary = `Ở ${at(early)} còn ${pct(points[early])} người xem; tới cuối video còn ${pct(points[n])}.`;
  function pick(clientX: number, rect: DOMRect) {
    const sx = ((clientX - rect.left) / rect.width) * W;
    setHover(Math.max(0, Math.min(n, Math.round(((sx - PAD.l) / (W - PAD.l - PAD.r)) * n))));
  }
  const h = hover;
  return (
    <figure className="qt-retention">
      <figcaption><strong>Còn bao nhiêu % người xem</strong> <small>theo độ dài Reel{lengthS > 0 ? ` (${seconds(lengthS)})` : ""}</small></figcaption>
      <div className="qt-retention__plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Biểu đồ giữ chân người xem. ${summary}`} tabIndex={0}
             onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())} onPointerLeave={() => setHover(null)}
             onFocus={() => setHover((v) => v ?? early)} onBlur={() => setHover(null)}
             onKeyDown={(e) => {
               if (e.key === "ArrowRight") setHover((v) => Math.min(n, (v ?? 0) + 1));
               if (e.key === "ArrowLeft") setHover((v) => Math.max(0, (v ?? 0) - 1));
             }}>
          {[1, 0.5, 0].map((v) => (
            <g key={v}>
              <line className="qt-retention__grid" x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} />
              <text className="qt-retention__tick" x={PAD.l - 5} y={y(v) + 3.5} textAnchor="end">{pct(v)}</text>
            </g>
          ))}
          {[0, Math.round(n / 2), n].map((i) => (
            <text key={i} className="qt-retention__tick" x={x(i)} y={H - 5} textAnchor={i === 0 ? "start" : i === n ? "end" : "middle"}>{at(i)}</text>
          ))}
          <path className="qt-retention__area" d={area} />
          <path className="qt-retention__line" d={line} />
          {h !== null && (
            <g>
              <line className="qt-retention__cross" x1={x(h)} x2={x(h)} y1={PAD.t} y2={y(0)} />
              <circle className="qt-retention__dot" cx={x(h)} cy={y(points[h])} r={4} />
            </g>
          )}
        </svg>
        {h !== null && (
          <div className="qt-retention__tip" style={{ left: `${Math.min(80, Math.max(20, (x(h) / W) * 100))}%` }}>
            <strong>{pct(points[h])}</strong> <span>còn xem ở {at(h)}</span>
          </div>
        )}
      </div>
      <p className="qt-retention__sum">{summary}</p>
      <details className="qt-retention__table">
        <summary>Xem dạng bảng</summary>
        <table>
          <thead><tr><th>Thời điểm</th><th>Còn xem</th></tr></thead>
          <tbody>
            {points.map((v, i) => (i % 4 === 0 ? <tr key={i}><td>{at(i)}</td><td>{pct(v)}</td></tr> : null))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
