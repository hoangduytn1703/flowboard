import { useEffect, useRef, useState } from "react";
import { DEFAULT_VOICE, getSmooth60, patchNode, VOICES, warmSmooth60, type Smooth60Status } from "../../api/client";
import { getDubStatus, normReveal, SUB_REVEALS } from "../../api/dub";
import { useBoardStore, type FlowboardNodeData } from "../../store/board";
import { useQuicktoolStore } from "../../store/quicktool";
import { useSettingsStore } from "../../store/settings";
import { isBusy, type ClipRoles } from "../roles";
import { useVoiceGroups, VoiceOptions, VoicePreview } from "../VoiceField";

/** How the joined clip gets its subtitles — mirrors services/video_export.subtitle_choice + tts.SUB_STYLES +
 * dub_remotion.STYLES. Stored on the export node as ``subtitles`` / ``subEngine`` / ``subStyle``. */
export const SUB_CHOICES: { key: string; label: string; remotion?: boolean }[] = [
  { key: "off", label: "Không thêm phụ đề" },
  { key: "ass:outline", label: "ffmpeg · Chữ trắng viền đen (nhanh)" },
  { key: "ass:box_yellow", label: "ffmpeg · Hộp vàng chữ đen" },
  { key: "ass:box_white", label: "ffmpeg · Hộp trắng chữ đen" },
  { key: "remotion:rm_box", label: "Remotion · Hộp vàng bo góc, font Việt", remotion: true },
  { key: "remotion:rm_karaoke", label: "Remotion · Bật sáng từng chữ (kiểu TikTok)", remotion: true },
  { key: "remotion:rm_outline", label: "Remotion · Chữ trắng viền, font Việt", remotion: true },
];

export function subChoiceOf(data: FlowboardNodeData | undefined): string {
  if (data?.subtitles === false) return "off";
  const engine = data?.subEngine === "remotion" ? "remotion" : "ass";
  const key = `${engine}:${data?.subStyle || (engine === "remotion" ? "rm_box" : "outline")}`;
  return SUB_CHOICES.some((c) => c.key === key) ? key : "ass:outline";
}

export function subChoicePatch(key: string): Partial<FlowboardNodeData> {
  if (key === "off") return { subtitles: false };
  const [engine, style] = key.split(":");
  return { subtitles: true, subEngine: engine === "remotion" ? "remotion" : "ass", subStyle: style };
}

// Remotion runs on this machine (node + the npm packages): asked once per page load.
let remotionReady: Promise<boolean> | null = null;
function useRemotionReady(): boolean | null {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    remotionReady ??= getDubStatus().then((s) => !!s.remotion).catch(() => false);
    let alive = true;
    void remotionReady.then((v) => { if (alive) setOk(v); });
    return () => { alive = false; };
  }, []);
  return ok;
}

/** The subtitle look of the joined clip: none, ffmpeg (burned per clip) or Remotion (drawn on the joined clip). */
export function SubtitleField({ value, onChange, disabled, reveal, onReveal }: {
  value: string;
  onChange: (key: string) => void;
  disabled?: boolean;
  /** "Hiện chữ" of the ffmpeg styles (the export node's ``subReveal``) */
  reveal?: string;
  onReveal?: (reveal: string) => void;
}) {
  const remotion = useRemotionReady();
  return (
    <>
    <label className="qt-field">
      <span>Phụ đề</span>
      <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {SUB_CHOICES.map((c) => (
          <option key={c.key} value={c.key} disabled={c.remotion && remotion === false}>
            {c.label}{c.remotion && remotion === false ? " (chưa cài gói Remotion)" : ""}
          </option>
        ))}
      </select>
      {remotion === false && (
        <small className="qt-hint">Muốn dùng phụ đề Remotion: cài “Gói Remotion” ở Cài đặt → 🖥 Máy này (một lần).</small>
      )}
      {value.startsWith("remotion") && (
        <small className="qt-hint">Remotion vẽ phụ đề sau khi ghép (thêm ~1 phút cho clip 30 s); lỗi thì tự in bằng ffmpeg.</small>
      )}
    </label>
    {onReveal && value.startsWith("ass:") && (
      <label className="qt-field" title="Chữ hiện theo giọng đọc — in bằng ffmpeg nên vẫn nhanh">
        <span>Hiện chữ</span>
        <select value={normReveal(reveal)} disabled={disabled} onChange={(e) => onReveal(e.target.value)}>
          {SUB_REVEALS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
        </select>
      </label>
    )}
    </>
  );
}

/** Is the clip joined at 60 fps: its export node says so, else (no export node yet) the account's last choice. */
export function smooth60Of(data: FlowboardNodeData | undefined, favourite: boolean): boolean {
  return typeof data?.smooth60 === "boolean" ? data.smooth60 : favourite;
}

/** The 60 fps copies made in the background (services/smooth_prewarm): polled while some are still being made. */
function useSmooth60Status(boardId: number | null, on: boolean): Smooth60Status | null {
  const [status, setStatus] = useState<Smooth60Status | null>(null);
  const kicked = useRef<number | null>(null);
  useEffect(() => {
    if (!on || boardId === null) { setStatus(null); return; }
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      const s = await getSmooth60(boardId).catch(() => null);
      if (!alive) return;
      setStatus(s);
      // clips that landed before 60 fps was on (or before an agent restart): warmed once when the box is seen on
      if (s && s.ready + s.running < s.total && kicked.current !== boardId) {
        kicked.current = boardId;
        void warmSmooth60(boardId).then((w) => { if (alive) setStatus(w); }).catch(() => undefined);
      }
      if (s && s.ready < s.total) timer = window.setTimeout(() => void tick(), 5000);
    };
    void tick();
    return () => { alive = false; if (timer) window.clearTimeout(timer); };
  }, [boardId, on]);
  return status;
}

/** "Mượt 60 fps", step 4 and step 5: the scenes are smoothed in the background as soon as they land (and when it is
 * turned on), so the join itself does not wait; the choice is remembered for the next clip. */
export function Smooth60Field({ data, disabled, onChange }: {
  data: FlowboardNodeData | undefined;
  disabled?: boolean;
  onChange: (patch: Partial<FlowboardNodeData>) => void | Promise<void>;
}) {
  const boardId = useBoardStore((s) => s.boardId);
  const favourite = useSettingsStore((s) => s.smooth60);
  const setFavourite = useSettingsStore((s) => s.setSmooth60);
  const on = smooth60Of(data, favourite);
  const status = useSmooth60Status(boardId, on);

  async function toggle(next: boolean) {
    await onChange({ smooth60: next });
    setFavourite(next);
    if (next && boardId !== null) void warmSmooth60(boardId).catch(() => undefined);
  }

  let note = "Thêm ~2–3 phút lúc ghép clip 4 cảnh nếu chưa làm sẵn; bật sớm thì tool làm mượt ngầm từng cảnh khi video về.";
  if (on && status) {
    if (status.total === 0) note = "Mỗi cảnh được làm mượt ngầm ngay khi video về — lúc ghép không phải chờ.";
    else if (status.ready >= status.total) note = `✓ Đã làm mượt sẵn cả ${status.total} cảnh — ghép sẽ nhanh.`;
    else note = `Đang làm mượt sẵn: ${status.ready}/${status.total} cảnh xong (chạy ngầm, ~2 phút mỗi lượt) — ghép lúc này thì phần còn lại làm luôn.`;
  }
  return (
    <div className="qt-smooth60">
      <label className="qt-check">
        <input type="checkbox" checked={on} disabled={disabled} onChange={(e) => void toggle(e.target.checked)} />
        Mượt 60 fps
      </label>
      <small className={`qt-hint${on && status && status.total > 0 && status.ready >= status.total ? " qt-smooth60__done" : ""}`}>{note}</small>
    </div>
  );
}

/** The voice the clip is read with: the export node's, else the account's favourite dubbing voice. */
export function joinVoice(data: FlowboardNodeData | undefined, favourite: string): string {
  if (data && typeof data.voice === "string" && data.voice in VOICES) return data.voice;
  return favourite && favourite in VOICES ? favourite : DEFAULT_VOICE;
}

/**
 * Step 4: the voice and the subtitles of the joined clip, picked ahead (saved on the export node — step 5 and
 * "⚡ Tạo video tự động" use them). The voice picked here is also remembered as the favourite for the next clip.
 */
export function JoinOptions({ roles, voiceless = false }: { roles: ClipRoles; voiceless?: boolean }) {
  const exp = roles.export;
  const ensureExportNode = useQuicktoolStore((s) => s.ensureExportNode);
  const favourite = useSettingsStore((s) => s.dubVoice);
  const setFavourite = useSettingsStore((s) => s.setDubVoice);
  const groups = useVoiceGroups();
  const voice = joinVoice(exp?.data, favourite);
  const sub = subChoiceOf(exp?.data);
  const busy = isBusy(exp);

  async function save(patch: Partial<FlowboardNodeData>) {
    const id = exp?.id ?? (await ensureExportNode());
    if (!id) return;
    useBoardStore.getState().updateNodeData(id, patch);
    const dbId = parseInt(id, 10);
    if (!isNaN(dbId)) patchNode(dbId, { data: patch }).catch(() => {});
  }

  if (voiceless) {
    // "🔇 Không lời": nothing to read aloud or caption — the clips keep their own sound.
    return (
      <div className="qt-joinopts" role="group" aria-label="Khi ghép clip không lời">
        <div className="qt-joinopts__head">
          <strong>🔇 Clip không lời</strong>
          <small>không giọng đọc, không phụ đề — ghép giữ tiếng động thật của từng video; thêm nhạc nền ở Bước 5 nếu muốn</small>
        </div>
        <Smooth60Field data={exp?.data} disabled={busy} onChange={save} />
      </div>
    );
  }

  return (
    <div className="qt-joinopts" role="group" aria-label="Giọng đọc và phụ đề khi ghép">
      <div className="qt-joinopts__head">
        <strong>🎙 Giọng đọc, phụ đề & độ mượt khi ghép</strong>
        <small>chọn sẵn ở đây — Bước 5 và "⚡ Tạo video tự động" dùng luôn</small>
      </div>
      <div className="qt-joinopts__row">
        <label className="qt-field">
          <span>Giọng đọc <VoicePreview voice={voice} /></span>
          <select value={voice} disabled={busy} onChange={(e) => { void save({ voice: e.target.value }); setFavourite(e.target.value); }}>
            <VoiceOptions groups={groups} />
          </select>
        </label>
        <SubtitleField value={sub} disabled={busy} onChange={(key) => void save(subChoicePatch(key))}
                       reveal={exp?.data.subReveal} onReveal={(r) => void save({ subReveal: r })} />
      </div>
      <Smooth60Field data={exp?.data} disabled={busy} onChange={save} />
    </div>
  );
}
