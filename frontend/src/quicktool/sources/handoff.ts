// "📥 Thêm video" (/tools) gathers the videos once — links, files from this machine, clips of "Clip của tôi" — and
// hands them to the tool the seller picks (dub, cut, clean). The tool reads them once when it opens.
// sessionStorage: a reload of the tool page does not bring the same videos back twice.

export type HandoffTarget = "dub" | "cut" | "clean";

/** a file already uploaded, or a clip's final video */
export interface HandoffVideo { media_id: string; name: string; board_id?: number }

export interface Handoff {
  to: HandoffTarget;
  links: string[];
  videos: HandoffVideo[];
  /** the dubbing page: a voice-over or subtitles only */
  mode?: "dub" | "sub";
}

const KEY = "dflow.video.handoff";

export function giveHandoff(h: Handoff): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(h));
  } catch { /* private window: the tool opens empty */ }
}

/** The videos sent to this tool, once (read and forgotten). */
export function takeHandoff(to: HandoffTarget): Handoff | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const h = JSON.parse(raw) as Handoff;
    if (h.to !== to) return null;
    sessionStorage.removeItem(KEY);
    return { to: h.to, links: Array.isArray(h.links) ? h.links : [], videos: Array.isArray(h.videos) ? h.videos : [], mode: h.mode };
  } catch {
    return null;
  }
}
