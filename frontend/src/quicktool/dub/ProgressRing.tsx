import { StopButton } from "../../components/StopButton";
/** The dubbing job's progress as one big ring around the logo: the arc grows with the percentage and the
 *  colour walks orange → green → blue with it; an error turns everything red. Purely presentational —
 *  the job itself is polled and stopped by DubPage as before. */

const SIZE = 248;
const STROKE = 12;
const R = (SIZE - STROKE) / 2;
const CIRC = 2 * Math.PI * R;

/** orange (0 %) → green (50 %) → blue (100 %), through the hue wheel so it never goes muddy. */
export function ringColor(percent: number, error = false): string {
  if (error) return "hsl(0 80% 60%)";
  const p = Math.max(0, Math.min(100, percent));
  const hue = p <= 50 ? 20 + (142 - 20) * (p / 50) : 142 + (217 - 142) * ((p - 50) / 50);
  return `hsl(${hue.toFixed(0)} 86% 56%)`;
}

export function ProgressRing({
  percent, error, waiting, title, hint, phase, message, onStop, stopping,
}: {
  percent: number;
  error?: boolean;
  /** queued: nothing to measure yet, so the arc just keeps turning */
  waiting?: boolean;
  title: string;
  hint?: string;
  phase?: string;
  message?: string;
  onStop?: () => Promise<unknown> | void;
  /** "Dừng" already pressed (the agent says so) */
  stopping?: boolean;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(percent)));
  const color = ringColor(pct, !!error);
  const shown = error ? 100 : waiting ? 18 : Math.max(pct, 2);
  const state = error ? "error" : waiting ? "waiting" : "running";
  return (
    <section className={`qt-card qt-dubring is-${state}`} style={{ ["--ring" as string]: color }}>
      <div className="qt-dubring__stage" role="progressbar" aria-valuemin={0} aria-valuemax={100}
           aria-valuenow={error || waiting ? undefined : pct} aria-label={phase || title}>
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} aria-hidden="true">
          <circle className="qt-dubring__track" cx={SIZE / 2} cy={SIZE / 2} r={R} strokeWidth={STROKE} fill="none" />
          <g className="qt-dubring__spin">
            <circle className="qt-dubring__arc" cx={SIZE / 2} cy={SIZE / 2} r={R} strokeWidth={STROKE} fill="none"
                    strokeLinecap="round" strokeDasharray={CIRC} strokeDashoffset={CIRC * (1 - shown / 100)}
                    transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`} />
          </g>
        </svg>
        <div className="qt-dubring__logo" aria-hidden="true">
          {error ? "!" : (
            <svg viewBox="0 0 24 24" width="58" height="58" fill="#fff">
              <path d="M13.2 2 4.6 13.4c-.4.5 0 1.2.6 1.2h4.6l-1 7.1c-.1.8.9 1.2 1.4.6l8.6-11.4c.4-.5 0-1.2-.6-1.2h-4.6l1-7.1c.1-.8-.9-1.2-1.4-.6Z" />
            </svg>
          )}
        </div>
      </div>
      <div className="qt-dubring__pct">
        {error ? "Lỗi" : waiting ? "Đang chờ" : <>{pct}<small>%</small></>}
      </div>
      <h3 className="qt-dubring__title">{title}</h3>
      {hint && <small className="qt-dubring__hint">{hint}</small>}
      <div className="qt-dubring__phase">
        {error ? <span className="qt-dubring__err">{message || "Có lỗi xảy ra"}</span> : phase || (waiting ? "Chờ đến lượt…" : "Đang xử lý…")}
      </div>
      {onStop && <StopButton stopping={stopping} onStop={onStop} />}
    </section>
  );
}
