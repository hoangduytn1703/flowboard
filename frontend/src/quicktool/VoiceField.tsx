import { useEffect, useRef, useState } from "react";
import { VOICE_GROUPS, isGeminiVoice, previewVoice } from "../api/client";
import { toast } from "../store/toast";

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

/** A voice picker (Edge / Gemini groups) with "▶ Nghe thử". */
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
  return (
    <div className={`qt-voice-field${compact ? " qt-voice-field--compact" : ""}`}>
      <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} aria-label="Giọng đọc">
        {VOICE_GROUPS.map((g) => (
          <optgroup key={g.id} label={g.label}>
            {g.voices.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </optgroup>
        ))}
      </select>
      <VoicePreview voice={value} style={style} text={sampleText} iconOnly={!!compact} disabled={disabled} />
    </div>
  );
}
