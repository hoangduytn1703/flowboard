// The Quicktool model library: saved models are `Reference` rows of kind
// "character" (agent/flowboard/routes/references.py) whose `meta` keeps
// the character-builder form, so a model made for one product can be put
// on the next product's clip with its photo *and* its settings.
//
// Thin wrappers over the references routes. Kept apart from the generic
// `ReferenceItem` surface in ./client because that one has no `meta`.
import { DEFAULT_VOICE, VOICES, api, mediaUrl } from "./client";
import {
  CHARACTER_GENDERS,
  countryLabel,
  vibeLabel,
} from "../constants/character";

export interface CharacterMeta {
  /** Character-builder keys (`charGender` / `charCountry` / `charVibe`). */
  gender?: string;
  country?: string;
  vibe?: string;
  /** Free-text extras (`charExtras`). */
  extras?: string;
  /** The prompt the photo was rendered from, for reference. */
  prompt?: string;
  /** Name of the product / clip the model was first made for. */
  product?: string;
  /** The model's own voice (a `VOICES` id); see `voiceOf()` for the default. */
  voice?: string;
  /** Gemini voices only: how the voice reads ("vui vẻ, nói nhanh"). */
  voiceStyle?: string;
  /** Optional line the model says: put in front of scene 1's voice line
   * when the model is used on a clip, and read by "Nghe thử". */
  line?: string;
}

export interface SavedCharacter {
  id: number;
  mediaId: string;
  label: string;
  aiBrief: string | null;
  aspectRatio: string | null;
  pinned: boolean;
  sourceBoardId: number | null;
  sourceNodeShortId: string | null;
  meta: CharacterMeta;
  createdAt: string;
}

export interface SaveCharacterInput {
  media_id: string;
  label: string;
  meta: CharacterMeta;
  ai_brief?: string | null;
  aspect_ratio?: string | null;
  source_board_id?: number | null;
  source_node_short_id?: string | null;
}

interface CharacterRowWire {
  id: number;
  media_id: string;
  label: string;
  kind: string;
  ai_brief: string | null;
  aspect_ratio: string | null;
  pinned: boolean;
  source_board_id: number | null;
  source_node_short_id: string | null;
  meta: Record<string, unknown> | null;
  created_at: string;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v ? v : undefined;
}

function mapRow(row: CharacterRowWire): SavedCharacter {
  const m = row.meta ?? {};
  return {
    id: row.id,
    mediaId: row.media_id,
    label: row.label,
    aiBrief: row.ai_brief,
    aspectRatio: row.aspect_ratio,
    pinned: row.pinned,
    sourceBoardId: row.source_board_id,
    sourceNodeShortId: row.source_node_short_id,
    meta: {
      gender: str(m.gender),
      country: str(m.country),
      vibe: str(m.vibe),
      extras: str(m.extras),
      prompt: str(m.prompt),
      product: str(m.product),
      voice: str(m.voice),
      voiceStyle: str(m.voiceStyle),
      line: str(m.line),
    },
    createdAt: row.created_at,
  };
}

export async function listCharacters(): Promise<SavedCharacter[]> {
  const rows = await api<CharacterRowWire[]>("/api/references?kind=character&limit=200");
  return rows.map(mapRow);
}

/** Idempotent on media_id: saving a photo already in the library returns
 * the existing row (its name and meta untouched). */
export async function saveCharacter(input: SaveCharacterInput): Promise<SavedCharacter> {
  const row = await api<CharacterRowWire>("/api/references", {
    method: "POST",
    body: JSON.stringify({ ...input, kind: "character" }),
  });
  return mapRow(row);
}

export async function renameCharacter(id: number, label: string): Promise<SavedCharacter> {
  const row = await api<CharacterRowWire>(`/api/references/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ label }),
  });
  return mapRow(row);
}

export async function updateCharacterMeta(id: number, meta: CharacterMeta): Promise<SavedCharacter> {
  const row = await api<CharacterRowWire>(`/api/references/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ meta }),
  });
  return mapRow(row);
}

/** Edit a saved model: name, form/voice/line (whole meta dict), and
 * optionally a new photo. */
export async function updateCharacter(id: number, patch: {
  label?: string;
  meta?: CharacterMeta;
  media_id?: string;
  aspect_ratio?: string | null;
}): Promise<SavedCharacter> {
  const row = await api<CharacterRowWire>(`/api/references/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  return mapRow(row);
}

export async function deleteCharacter(id: number): Promise<void> {
  // 204 No Content: api<T>() would choke on the empty body.
  const res = await fetch(`/api/references/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) {
    throw new Error(`deleteCharacter: ${res.status} ${res.statusText}`);
  }
}

/** Default voice for a model of ``gender``: Edge Nam Minh for men, Hoài My otherwise. */
export function defaultVoiceFor(gender: string | undefined): string {
  return gender === "male" ? "vi-VN-NamMinhNeural" : DEFAULT_VOICE;
}

/** The voice a saved model speaks with: its own pick, else the default for its gender. */
export function voiceOf(c: Pick<SavedCharacter, "meta">): string {
  return c.meta.voice && c.meta.voice in VOICES ? c.meta.voice : defaultVoiceFor(c.meta.gender);
}

export function characterPhotoUrl(c: Pick<SavedCharacter, "mediaId">): string {
  return mediaUrl(c.mediaId);
}

export function genderLabel(key: string | undefined): string | null {
  if (!key) return null;
  return CHARACTER_GENDERS.find((g) => g.key === key)?.label ?? null;
}

/** "Nữ · Việt Nam · Clean Girl" — the default name of a saved model. */
export function defaultCharacterLabel(meta: CharacterMeta): string {
  const parts = [genderLabel(meta.gender), countryLabel(meta.country), vibeLabel(meta.vibe)]
    .filter((p): p is string => !!p);
  return parts.length ? parts.join(" · ") : "Người mẫu";
}

/** The badges shown under a saved model: gender, country, vibe. */
export function characterBadges(meta: CharacterMeta): string[] {
  return [genderLabel(meta.gender), countryLabel(meta.country), vibeLabel(meta.vibe)]
    .filter((p): p is string => !!p);
}
