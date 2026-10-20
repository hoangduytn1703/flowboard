import type { Edge } from "@xyflow/react";
import type { FlowNode } from "../store/board";

/**
 * The Quicktool wizard reads a plain board as a clip: the note is the
 * script, the character is the model, visual assets are the product
 * photos, image nodes are the scenes (top-to-bottom), each scene's
 * downstream video node is its clip, and an export node joins them.
 * Boards made from a template or a storyboard cut fit this shape; nothing
 * is tagged, so a hand-built canvas works too as long as it is wired the
 * same way.
 */
export interface Scene {
  index: number;
  image: FlowNode;
  video: FlowNode | null;
}

export interface ClipRoles {
  script: FlowNode | null;
  model: FlowNode | null;
  products: FlowNode[];
  storyboard: FlowNode | null;
  scenes: Scene[];
  export: FlowNode | null;
}

/** Rough Flow credits for one 8 s clip, for the "are you sure" prompts. */
export function creditsPerClip(model: string, quality?: string): number {
  if (model === "omni_flash") return 25;
  return quality && /quality|high/i.test(quality) ? 100 : 20;
}

export function hasMedia(n: FlowNode | null | undefined): boolean {
  return !!n && typeof n.data.mediaId === "string" && n.data.mediaId.length > 0;
}

export function isBusy(n: FlowNode | null | undefined): boolean {
  return !!n && (n.data.status === "queued" || n.data.status === "running"
    || n.data.autoPromptStatus === "pending");
}

function byPosition(a: FlowNode, b: FlowNode): number {
  return a.position.y - b.position.y || a.position.x - b.position.x;
}

export function deriveRoles(nodes: FlowNode[], edges: Edge[]): ClipRoles {
  const of = (type: string) => nodes.filter((n) => n.data.type === type).sort(byPosition);
  const videos = of("video");
  // A scene's clip is the first video node fed by that scene image.
  const videoFor = (image: FlowNode): FlowNode | null => {
    const targets = new Set(edges.filter((e) => e.source === image.id).map((e) => e.target));
    return videos.find((v) => targets.has(v.id)) ?? null;
  };
  const scenes = of("image").map((image, i) => ({ index: i + 1, image, video: videoFor(image) }));
  return {
    script: of("note")[0] ?? null,
    model: of("character")[0] ?? null,
    products: of("visual_asset"),
    storyboard: of("Storyboard")[0] ?? null,
    scenes,
    export: [...of("export"), ...of("merge")][0] ?? null,
  };
}

/** The wizard step the board has reached on its own (1-based). */
export function furthestStep(roles: ClipRoles): number {
  if (hasMedia(roles.export)) return 5;
  const clips = roles.scenes.map((s) => s.video).filter(hasMedia).length;
  if (roles.scenes.length > 0 && clips === roles.scenes.length) return 5;
  if (clips > 0) return 4;
  const images = roles.scenes.filter((s) => hasMedia(s.image)).length;
  if (roles.scenes.length > 0 && images === roles.scenes.length) return 4;
  if (images > 0 || hasMedia(roles.model)) return 3;
  return roles.scenes.length > 0 ? 2 : 1;
}

/** Whether step `n` is complete on its own terms (for the ✓ in the stepper),
 * independent of how far the clip has been taken. */
export function stepDone(roles: ClipRoles, n: number, isDrama = false): boolean {
  switch (n) {
    case 1: return roles.products.length > 0 && roles.products.every(hasMedia);
    case 2: return roles.scenes.length > 0;
    case 3: return roles.scenes.length > 0 && roles.scenes.every((s) => hasMedia(s.image));
    case 4: return isDrama ? stepDone(roles, 3) : roles.scenes.length > 0 && roles.scenes.every((s) => hasMedia(s.video));
    case 5: return hasMedia(roles.export);
    default: return false;
  }
}
