import { createRequest, getRequest } from "../api/client";
import { useGenerationStore } from "../store/generation";
import { useSettingsStore } from "../store/settings";

const POLL_MS = 2500;
const TIMEOUT_MS = 4 * 60_000;

/**
 * One image from a prompt, outside any clip (e.g. a new model made on the
 * /models page): a `gen_image` request with no node, polled until done.
 * Same parameters a board node would send. Returns the media id.
 * ``refMediaIds`` (e.g. the product photo) are sent as references so the
 * image shows the real product.
 */
export async function generateStandaloneImage(
  prompt: string,
  aspectRatio = "IMAGE_ASPECT_RATIO_PORTRAIT",
  refMediaIds: string[] = [],
): Promise<string> {
  const projectId = await useGenerationStore.getState().ensureProjectId();
  if (!projectId) throw new Error("Chưa có Flow project — ghim một project trong Cài đặt.");
  const settings = useSettingsStore.getState();
  const tier = useGenerationStore.getState().paygateTier;
  const req = await createRequest({
    type: "gen_image",
    params: {
      prompt,
      media_provider: settings.mediaProvider,
      project_id: projectId,
      aspect_ratio: aspectRatio,
      variant_count: 1,
      image_model: settings.imageModel,
      image_provider: settings.imageProvider,
      ...(refMediaIds.length ? { ref_media_ids: refMediaIds } : {}),
      ...(tier ? { paygate_tier: tier } : {}),
    },
  });
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    const r = await getRequest(req.id);
    if (r.status === "done") {
      const ids = (r.result?.media_ids as string[] | undefined) ?? [];
      if (ids[0]) return ids[0];
      throw new Error("Flow trả về kết quả nhưng không có ảnh.");
    }
    if (r.status === "failed" || r.status === "canceled" || r.status === "timeout") {
      throw new Error(r.error || `Tạo ảnh thất bại (${r.status}).`);
    }
  }
  throw new Error("Tạo ảnh quá 4 phút chưa xong. Xem lại ở Lịch sử & credit.");
}

const VIDEO_TIMEOUT_MS = 8 * 60_000;

/**
 * One short video outside any clip (a post's "🎬 Video kèm"): Omni Flash
 * 8 s animating ``sourceMediaId`` (Flow needs an image ingredient), polled
 * until done — ~12 credits, 1–3 minutes. Returns the video's media id.
 */
export async function generateStandaloneVideo(
  prompt: string,
  sourceMediaId: string,
  aspectRatio: "VIDEO_ASPECT_RATIO_PORTRAIT" | "VIDEO_ASPECT_RATIO_LANDSCAPE" = "VIDEO_ASPECT_RATIO_PORTRAIT",
): Promise<string> {
  const gen = useGenerationStore.getState();
  const projectId = await gen.ensureProjectId();
  if (!projectId) throw new Error("Chưa có Flow project — ghim một project trong Cài đặt.");
  const req = await createRequest({
    type: "gen_video_omni",
    params: {
      prompt,
      media_provider: "flow",
      project_id: projectId,
      ref_media_ids: [sourceMediaId],
      duration_s: 8,
      aspect_ratio: aspectRatio,
      ...(gen.paygateTier ? { paygate_tier: gen.paygateTier } : {}),
    },
  });
  const deadline = Date.now() + VIDEO_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 4000));
    const r = await getRequest(req.id);
    if (r.status === "done") {
      const ids = ((r.result?.media_ids as (string | null)[] | undefined) ?? []).filter(Boolean) as string[];
      if (ids[0]) return ids[0];
      throw new Error("Flow trả về kết quả nhưng không có video.");
    }
    if (r.status === "timeout" || /FLOW_DROPPED_JOB/i.test(r.error ?? "")) {
      throw new Error("Flow bỏ lượt video này (thường do ảnh có gương mặt bị chặn). Thử ảnh khác, credit được hoàn.");
    }
    if (r.status === "failed" || r.status === "canceled") throw new Error(r.error || `Tạo video thất bại (${r.status}).`);
  }
  throw new Error("Tạo video quá 8 phút chưa xong. Xem lại ở Lịch sử & credit.");
}
