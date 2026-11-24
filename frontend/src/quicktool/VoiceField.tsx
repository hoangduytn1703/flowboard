import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { VOICE_GROUPS, VOICES_CHANGED, fetchVoiceGroups, isGeminiVoice, previewVoice, warmVoice, type VoiceGroup } from "../api/client";
import { toast } from "../store/toast";

let cachedGroups: VoiceGroup[] | null = null;
/** The voice families the agent offers (the account's cloned voices, Edge, VieNeu, Gemini, FPT.AI) — the static
 * Edge + Gemini list until loaded; reloaded when a voice is cloned / renamed / deleted. */
export function useVoiceGroups(): VoiceGroup[] {
  const [groups, setGroups] = useState<VoiceGroup[]>(cachedGroups ?? VOICE_GROUPS);
  useEffect(() => {
    let live = true;
    const load = () => fetchVoiceGroups().then((g) => { cachedGroups = g; if (live) setGroups(g); }).catch(() => undefined);
    if (!cachedGroups) void load();
    const changed = () => { cachedGroups = null; void load(); };
    window.addEventListener(VOICES_CHANGED, changed);
    return () => { live = false; window.removeEventListener(VOICES_CHANGED, changed); };
  }, []);
  return groups;
}

// ── the short list: a voice picker opens on a handful of voices, not ~50 (24/11) ─────────────────────────────
const RECENT_KEY = "dflow.voices.recent";
/** good defaults while nothing was picked yet: the two free Edge voices and two VieNeu ones (free, on this machine) */
const STARTERS = ["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural", "vieneu:Hải Đăng", "vieneu:Ngọc Huyền"];
const SHORT_LIST = 6;
const SHOW_ALL = "__all_voices__";

function recentVoices(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** A voice the seller just picked goes to the top of the short list (this browser). */
export function rememberVoice(voice: string): void {
  if (!voice || voice.startsWith("__")) return;
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([voice, ...recentVoices().filter((v) => v !== voice)].slice(0, 10)));
  } catch { /* private window */ }
}

/** The short list: the voice in use, the ones picked lately, then good defaults — only voices this machine can use. */
function favouriteVoices(groups: VoiceGroup[], value: string): [string, string][] {
  const usable = new Map<string, string>();
  for (const g of groups) {
    if (g.id === "clone" || g.available === false) continue;
    for (const [k, label] of g.voices) usable.set(k, label);
  }
  const out: [string, string][] = [];
  for (const k of [value, ...recentVoices(), ...STARTERS]) {
    if (out.length >= SHORT_LIST) break;
    const label = usable.get(k);
    if (label && !out.some(([x]) => x === k)) out.push([k, label]);
  }
  return out;
}

/** `<optgroup>`s for a voice `<select>`: families the machine cannot use are disabled and say why. */
export function VoiceOptions({ groups, short = false }: { groups: VoiceGroup[]; short?: boolean }) {
  const SHORT: Record<string, string> = { clone: "🧬 Giọng nhân bản", edge: "Edge", vieneu: "VieNeu · trên máy", gemini: "Gemini", fpt: "FPT.AI" };
  return (
    <>
      {groups.map((g) => (
        <optgroup key={g.id} label={`${short ? SHORT[g.id] ?? g.id : g.label}${g.available === false && g.reason ? ` — ${g.reason}` : ""}`}>
          {g.voices.map(([k, label]) => <option key={k} value={k} disabled={g.available === false}>{label}</option>)}
        </optgroup>
      ))}
    </>
  );
}

// Only one sample plays at a time across every preview button on the page.
let playing: HTMLAudioElement | null = null;

/**
 * "▶ Nghe thử" for one voice. ``text`` is what it reads (a saved model's own
 * line); empty = the agent's fixed sample sentence. ``iconOnly`` keeps it to
 * a ▶ / ■ for tight rows.
 */
export function VoicePreview({ voice, style, text, iconOnly = true, disabled }: {
  voice: string;
  style?: string;
  text?: string;
  iconOnly?: boolean;
  disabled?: boolean;
}) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  function stop() {
    const a = audioRef.current;
    if (a) {
      if (playing === a) playing = null;
      a.pause();
      a.src = "";
      audioRef.current = null;
    }
    setState("idle");
  }
  useEffect(() => stop, [voice, style, text]);

  async function play() {
    if (state !== "idle") { stop(); return; }
    if (playing) { playing.pause(); playing = null; }
    setState("loading");
    try {
      const { url } = await previewVoice(voice, isGeminiVoice(voice) ? style : undefined, text);
      const audio = new Audio(url);
      audioRef.current = audio;
      playing = audio;
      audio.onended = () => { if (audioRef.current === audio) stop(); };
      audio.onerror = () => { if (audioRef.current === audio) { stop(); toast.error("Không phát được file nghe thử."); } };
      await audio.play();
      setState("playing");
    } catch (err) {
      stop();
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const label = iconOnly
    ? (state === "loading" ? "…" : state === "playing" ? "■" : "▶")
    : (state === "loading" ? "Đang tạo…" : state === "playing" ? "■ Dừng" : "▶ Nghe thử");
  return (
    <button type="button" className={`qt-btn qt-btn--ghost qt-btn--small${iconOnly ? " qt-voice-preview--icon" : ""}`}
            disabled={disabled || state === "loading"} onClick={() => void play()} aria-label="Nghe thử giọng"
            title={text ? "Nghe giọng này đọc câu của người mẫu (lần đầu mất vài giây)" : "Nghe một câu mẫu bằng giọng này"}>
      {label}
    </button>
  );
}

/** The picker's last option: opens "🧬 Giọng nhân bản" instead of choosing a voice. */
const CLONE_NEW = "__clone_new__";

/**
 * A voice `<select>` that opens on a short list (your own cloned voices, the voice in use, the ones you picked lately,
 * good free defaults) with "Xem tất cả giọng…" for the rest. ``emptyLabel`` adds a first "" option (e.g. "giọng chung").
 */
export function VoiceSelect({ value, onChange, disabled, emptyLabel, short = false, withClone = false, ariaLabel = "Giọng đọc" }: {
  value: string;
  onChange: (voice: string) => void;
  disabled?: boolean;
  emptyLabel?: string;
  short?: boolean;
  withClone?: boolean;
  ariaLabel?: string;
}) {
  const groups = useVoiceGroups();
  const navigate = useNavigate();
  const ref = useRef<HTMLSelectElement>(null);
  const [all, setAll] = useState(false);
  const favs = favouriteVoices(groups, value);
  const clones = groups.find((g) => g.id === "clone");
  const total = groups.reduce((n, g) => n + g.voices.length, 0);
  // the voice in use is always in the list, even when it is not a favourite (another machine's, a family turned off)
  const inShort = !value || favs.some(([k]) => k === value) || !!clones?.voices.some(([k]) => k === value);
  const showAll = all || !inShort;
  function pick(v: string) {
    if (v === SHOW_ALL) {
      setAll(true);
      window.setTimeout(() => { try { ref.current?.focus(); ref.current?.showPicker?.(); } catch { /* not every browser */ } }, 0);
      return;
    }
    if (v === CLONE_NEW) { navigate("/voices"); return; }
    rememberVoice(v);
    onChange(v);
  }
  return (
    <select ref={ref} value={value} disabled={disabled} aria-label={ariaLabel} onChange={(e) => pick(e.target.value)}>
      {emptyLabel !== undefined && <option value="">{emptyLabel}</option>}
      {showAll ? (
        <VoiceOptions groups={groups} short={short} />
      ) : (
        <>
          {clones && clones.voices.length > 0 && <VoiceOptions groups={[clones]} short={short} />}
          <optgroup label="⭐ Hay dùng">
            {favs.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </optgroup>
          <option value={SHOW_ALL}>Xem tất cả giọng ({total})…</option>
        </>
      )}
      {withClone && (
        <optgroup label="🧬 Giọng của chính bạn">
          <option value={CLONE_NEW}>＋ Nhân bản giọng của bạn (thu 10 giây)…</option>
        </optgroup>
      )}
    </select>
  );
}

/** A voice picker (cloned voices, Edge, VieNeu, Gemini, FPT.AI) with "▶ Nghe thử". */
export function VoiceField({
  value,
  onChange,
  style,
  sampleText,
  disabled,
  compact,
}: {
  value: string;
  onChange: (voice: string) => void;
  style?: string;
  sampleText?: string;
  disabled?: boolean;
  compact?: boolean;
}) {
  // a VieNeu voice on show: its model loads in the background now, so hearing it / dubbing with it starts at once
  useEffect(() => { if (!disabled) warmVoice(value); }, [value, disabled]);
  return (
    <div className={`qt-voice-field${compact ? " qt-voice-field--compact" : ""}`}>
      <VoiceSelect value={value} onChange={onChange} disabled={disabled} withClone />
      <VoicePreview voice={value} style={style} text={sampleText} iconOnly={!!compact} disabled={disabled} />
    </div>
  );
}
