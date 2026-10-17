import type { Edge } from "@xyflow/react";
import type { FlowNode } from "../store/board";

/**
 * The clips an "Xuất video" node joins, in order: every upstream video (or
 * export / merge) node that has media, top-to-bottom then left-to-right on
 * the canvas. Canvas position is the ordering control — stack the videos
 * vertically in the order you want them joined.
 */
export interface ExportSource {
  rfId: string;
  shortId: string;
  title: string;
  mediaId: string;
}

const CLIP_TYPES = new Set(["video", "export", "merge"]);

export function exportSources(rfId: string, nodes: FlowNode[], edges: Edge[]): ExportSource[] {
  const upstream = edges
    .filter((e) => e.target === rfId)
    .map((e) => nodes.find((n) => n.id === e.source))
    .filter((n): n is FlowNode => n !== undefined && CLIP_TYPES.has(n.data.type));
  // Distinct, position-sorted.
  const seen = new Set<string>();
  return upstream
    .filter((n) => (seen.has(n.id) ? false : (seen.add(n.id), true)))
    .sort((a, b) => a.position.y - b.position.y || a.position.x - b.position.x)
    .map((n) => ({
      rfId: n.id,
      shortId: n.data.shortId,
      title: n.data.title,
      mediaId: typeof n.data.mediaId === "string" ? n.data.mediaId : "",
    }));
}
