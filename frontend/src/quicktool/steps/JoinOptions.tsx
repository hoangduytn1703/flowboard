import { useEffect, useState } from "react";
import { DEFAULT_VOICE, patchNode, VOICES } from "../../api/client";
import { getDubStatus } from "../../api/dub";
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
export function SubtitleField({ value, onChange, disabled }: { value: string; onChange: (key: string) => void; disabled?: boolean }) {
  const remotion = useRemotionReady();
  return (
    <label className="qt-field">
      <span>Phụ đề</span>
      <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {SUB_CHOICES.map((c) => (
          <option key={c.key} value={c.key} disabled={c.remotion && remotion === false}>
            {c.label}{c.remotion && remotion === false ? " (máy này chưa có Remotion)" : ""}
          </option>
        ))}
      </select>
      {value.startsWith("remotion") && (
        <small className="qt-hint">Remotion vẽ phụ đề sau khi ghép (thêm ~1 phút cho clip 30 s); lỗi thì tự in bằng ffmpeg.</small>
      )}
    </label>
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
export function JoinOptions({ roles }: { roles: ClipRoles }) {
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

  return (
    <div className="qt-joinopts" role="group" aria-label="Giọng đọc và phụ đề khi ghép">
      <div className="qt-joinopts__head">
        <strong>🎙 Giọng đọc & phụ đề khi ghép</strong>
        <small>chọn sẵn ở đây — Bước 5 và "⚡ Tạo video tự động" dùng luôn</small>
      </div>
      <div className="qt-joinopts__row">
        <label className="qt-field">
          <span>Giọng đọc <VoicePreview voice={voice} /></span>
          <select value={voice} disabled={busy} onChange={(e) => { void save({ voice: e.target.value }); setFavourite(e.target.value); }}>
            <VoiceOptions groups={groups} />
          </select>
        </label>
        <SubtitleField value={sub} disabled={busy} onChange={(key) => void save(subChoicePatch(key))} />
      </div>
    </div>
  );
}
