import {
  CHARACTER_COUNTRIES,
  CHARACTER_GENDERS,
  CHARACTER_VIBES,
  type CountryKey,
  type GenderKey,
  type VibeKey,
} from "../constants/character";

/**
 * The locked headshot prompt a character node renders with. Shared by the
 * Generate dialog and the Quicktool wizard so both produce the same
 * reference-grade portrait.
 */
// Flow silently drops every video made from a face it takes for a celebrity
// (22/10, 26/10). Idealised "beauty preset" faces converge on the same few
// idol looks, so each model gets two small traits of its own — an ordinary,
// distinctive face matches nobody famous.
const OWN_TRAITS = [
  "a small beauty mark on one cheek",
  "slightly uneven natural eyebrows",
  "a soft rounded jawline",
  "a few light freckles across the nose",
  "a slightly wider nose bridge",
  "a small dimple on one side when smiling",
  "naturally fuller cheeks",
  "a faint mole above the lip",
  "slightly hooded eyes",
  "a gently asymmetrical smile",
] as const;

export function ownTraits(): string {
  const pool = [...OWN_TRAITS];
  const pick = () => pool.splice(Math.floor(Math.random() * pool.length), 1)[0];
  return `${pick()} and ${pick()}`;
}

export function buildCharacterPrompt(
  gender: GenderKey | null,
  country: CountryKey | null,
  vibe: VibeKey,
  extras: string,
): string {
  const g = CHARACTER_GENDERS.find((x) => x.key === gender)?.tag;
  const c = CHARACTER_COUNTRIES.find((x) => x.key === country)?.tag;
  const subject = [c, g].filter(Boolean).join(" ") || "person";
  const preset = CHARACTER_VIBES.find((v) => v.key === vibe);
  const vibeTokens = (gender === "male" ? preset?.male : preset?.tokens) ?? [];
  const tail = extras.trim();
  // Pose anchor is front-loaded (right after subject) because diffusion
  // models weight earlier tokens more — vibe tokens like "editorial /
  // magazine beauty" otherwise pull toward fashion 3/4 turns. The trailing
  // negatives reinforce the lock so the headshot stays usable as a
  // character reference across every downstream shot.
  return [
    // Not "studio": the reference face feeds every scene, and a studio beauty
    // portrait makes the whole clip look staged (7/11).
    `Natural daylight head-and-shoulders portrait photo of a ${subject} character`,
    "subject directly faces the camera, head perfectly straight with zero tilt and zero turn",
    "shoulders square to camera, axially symmetric pose, nose centered, both eyes equally visible at the same height",
    `an ordinary, non-famous everyday person with their own distinctive face (${ownTraits()}), natural skin texture with visible pores, not resembling any celebrity, idol, actor or influencer`,
    ...vibeTokens,
    tail || null,
    "head and shoulders framing, centered composition, sharp focus on face",
    "strictly front-on orientation, no head tilt, no head turn, no profile angle, no three-quarter view, no over-the-shoulder pose",
    "no glasses, no hat, no mask, no occlusion, nothing covering the face",
    "photorealistic, natural candid quality, consistent character reference",
  ]
    .filter(Boolean)
    .join(", ");
}
