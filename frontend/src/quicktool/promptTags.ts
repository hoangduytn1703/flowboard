import type { SavedPrompt } from "../api/promptLibrary";

/**
 * Labels on saved prompts that say what they fit: the industry (ngành hàng,
 * keyed by product category) and the kind of scene in the script. They are
 * plain strings in `SavedPrompt.tags`, the same words the shipped samples
 * use (agent prompt_seeds.json), so the user can also type them by hand.
 */
export const INDUSTRY_TAG: Record<string, string> = {
  fashion: "thời trang",
  cosmetics: "mỹ phẩm",
  food: "đồ ăn",
  grocery: "tạp hoá",
  home: "gia dụng",
  other: "khác",
};
/** A prompt that fits every industry. */
export const ANY_INDUSTRY = "mọi ngành";
export const INDUSTRY_TAGS = [ANY_INDUSTRY, ...Object.values(INDUSTRY_TAG)];

/** Kinds of scene: where in the script a prompt belongs. */
export const SCENE_TAGS = ["hook", "chi tiết", "demo", "mở hộp", "chốt đơn", "chỉ tay", "hội thoại"] as const;
export type SceneTag = (typeof SCENE_TAGS)[number];

export function industryOf(tags: string[]): string[] {
  return tags.filter((t) => INDUSTRY_TAGS.includes(t));
}

/** Template scene titles ("Cảnh 2 - Chất liệu") → a scene tag. */
const SCENE_WORDS: [RegExp, SceneTag][] = [
  [/mở hộp|unbox/i, "mở hộp"],
  [/(^|\s)kết(?!\s*cấu)|kêu gọi|chốt|giá|cta/i, "chốt đơn"],
  [/dùng thử|dùng thật|lắp|thưởng thức|miếng đầu|giải pháp|demo|trải nghiệm/i, "demo"],
  [/chi tiết|chất liệu|kết cấu|xem kỹ|cận|dáng/i, "chi tiết"],
  [/hook|giới thiệu|vấn đề|nỗi đau|lên bàn|hero|trên tay|sản phẩm|mở đầu/i, "hook"],
];

/** The kind of scene a step-2 row is: from its title, else from its place
 * in the script (first = hook, last = chốt đơn, between = chi tiết). */
export function sceneTagOf(title: string | undefined, index: number, count: number): SceneTag {
  const name = (title ?? "").split(/\s[-–]\s/).slice(1).join(" - ") || (title ?? "");
  for (const [re, tag] of SCENE_WORDS) if (re.test(name)) return tag;
  if (index <= 1) return "hook";
  if (index >= count) return "chốt đơn";
  return "chi tiết";
}

/** Tags a prompt saved from a clip gets: the clip's industry and the scene. */
export function tagsForContext(ctx: PromptContext): string[] {
  const out: string[] = [];
  if (ctx.category && INDUSTRY_TAG[ctx.category]) out.push(INDUSTRY_TAG[ctx.category]);
  if (ctx.scene) out.push(ctx.scene);
  return out;
}

export interface PromptContext {
  /** Product category of the clip (fashion, food …); null = not known. */
  category: string | null;
  /** Kind of scene the field belongs to. */
  scene: SceneTag | null;
}

export interface PromptGroups {
  /** Same industry (or "mọi ngành") and same kind of scene. */
  best: SavedPrompt[];
  /** Same industry (or "mọi ngành"), another kind of scene. */
  industry: SavedPrompt[];
  /** No industry label: cannot tell. */
  untagged: SavedPrompt[];
  /** Labelled for another industry only. */
  other: SavedPrompt[];
}

/** Sort saved prompts by how well they fit the clip. Within a group, the
 * exact industry beats "mọi ngành", then the most used come first. */
export function groupPrompts(items: SavedPrompt[], ctx: PromptContext): PromptGroups {
  const mine = ctx.category ? INDUSTRY_TAG[ctx.category] : null;
  const groups: PromptGroups = { best: [], industry: [], untagged: [], other: [] };
  for (const p of items) {
    const ind = industryOf(p.tags);
    if (!ind.length) groups.untagged.push(p);
    else if (!mine || ind.includes(mine) || ind.includes(ANY_INDUSTRY)) {
      (ctx.scene && p.tags.includes(ctx.scene) ? groups.best : groups.industry).push(p);
    } else groups.other.push(p);
  }
  const score = (p: SavedPrompt) => (mine && p.tags.includes(mine) ? 1000 : 0) + p.uses;
  for (const g of Object.values(groups)) g.sort((a: SavedPrompt, b: SavedPrompt) => score(b) - score(a));
  return groups;
}
