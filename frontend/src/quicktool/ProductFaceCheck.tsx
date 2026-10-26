import { useEffect, useState } from "react";
import { api, patchNode } from "../api/client";
import { requestAutoBrief } from "../api/autoBrief";
import { useBoardStore, type FlowNode } from "../store/board";
import { toast } from "../store/toast";
import { generateStandaloneImage } from "./standaloneImage";

const faceCache = new Map<string, number | null>();

/** Faces in an image (agent-side YuNet, cached per media id). */
export function useFaces(mediaId: string | null): number | null {
  const [faces, setFaces] = useState<number | null>(mediaId ? faceCache.get(mediaId) ?? null : null);
  useEffect(() => {
    if (!mediaId) { setFaces(null); return; }
    if (faceCache.has(mediaId)) { setFaces(faceCache.get(mediaId) ?? null); return; }
    let live = true;
    api<{ faces: number | null }>(`/api/media/${mediaId}/faces`)
      .then((r) => { faceCache.set(mediaId, r.faces); if (live) setFaces(r.faces); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [mediaId]);
  return faces;
}

/** The clean "product alone" shot, drawn from the shop photo by Flow. Kept in
 * English like every image prompt; the product's own name goes in verbatim. */
export function cleanShotPrompt(name: string): string {
  const what = name.trim() || "the product";
  return [
    `Product-only packshot of: ${what}.`,
    "Show exactly the same item as in the reference photo — identical colour, material, pattern, shape, cut and every detail —",
    "alone and fully visible, centred: clothing on an invisible ghost mannequin or neatly laid flat, other products standing on a plain surface.",
    "Soft even studio light, plain light neutral background.",
    "No person, no face, no hands, no body parts, no text, no logo, no watermark, no price tag.",
  ].join(" ");
}

/**
 * Step 1, under a product photo with people in it: shop photos are a real
 * model, Flow drops clips made from a real person's face, and the photo is
 * the reference for every scene image — so the face spreads to every scene.
 * One click draws a product-only shot from it (one Flow image, ~25 s) and
 * puts it in place (the clip's photo, and first in the product's photos so
 * the next clips start clean). The old photo can be put back.
 */
export function ProductFaceCheck({ node, productId, productName }: {
  node: FlowNode;
  productId: number | null;
  productName: string;
}) {
  const mediaId = typeof node.data.mediaId === "string" ? node.data.mediaId : null;
  const faces = useFaces(mediaId);
  const [busy, setBusy] = useState(false);
  const prev = typeof node.data.prevMediaId === "string" ? node.data.prevMediaId : null;

  function setPhoto(next: string, prevId: string | null) {
    const dbId = parseInt(node.id, 10);
    const patch = { mediaId: next, mediaIds: [next], variantCount: 1, status: "done" as const, prevMediaId: prevId ?? undefined };
    useBoardStore.getState().updateNodeData(node.id, { ...patch, aiBrief: undefined });
    if (!isNaN(dbId)) {
      patchNode(dbId, { status: "done", data: { ...patch, prevMediaId: prevId, aiBrief: null } }).catch(() => {});
    }
    requestAutoBrief(node.id, next);
  }

  async function clean() {
    if (!mediaId) return;
    setBusy(true);
    try {
      const fresh = await generateStandaloneImage(cleanShotPrompt(productName), "IMAGE_ASPECT_RATIO_SQUARE", [mediaId]);
      faceCache.set(fresh, 0);
      setPhoto(fresh, mediaId);
      if (productId) {
        try {
          const p = await api<{ media_ids: string[] }>(`/api/products/${productId}`);
          await api(`/api/products/${productId}`, {
            method: "PATCH",
            body: JSON.stringify({ media_ids: [fresh, ...(p.media_ids ?? []).filter((m) => m !== fresh)].slice(0, 12) }),
          });
        } catch { /* the clip has the clean photo; the product list is a bonus */ }
      }
      toast.success("Đã thay bằng ảnh chỉ có sản phẩm. Ảnh cảnh tạo từ giờ sẽ không mang mặt người mẫu của shop.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không tạo được ảnh sản phẩm.");
    } finally {
      setBusy(false);
    }
  }

  if (faces && faces > 0) {
    return (
      <div className="qt-facewarn">
        <strong>⚠ Ảnh có {faces} gương mặt người thật</strong>
        <span>Flow hay chặn video làm từ ảnh người thật (coi là "giống người nổi tiếng"), và mặt này sẽ lọt vào mọi ảnh cảnh.</span>
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy} onClick={() => void clean()}>
          {busy ? "Đang tạo ảnh… (~25 s)" : "✨ Tạo ảnh chỉ có sản phẩm"}
        </button>
      </div>
    );
  }
  if (prev) {
    return (
      <button type="button" className="qt-link" onClick={() => setPhoto(prev, null)} title="Quay lại ảnh shop ban đầu">
        ↺ Dùng lại ảnh gốc
      </button>
    );
  }
  return null;
}
