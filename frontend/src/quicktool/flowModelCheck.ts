import { createRequest, getRequest, patchNode } from "../api/client";
import { listCharacters, updateCharacterMeta, type FlowCheck } from "../api/characters";
import { useBoardStore, type FlowNode } from "../store/board";
import { useGenerationStore } from "../store/generation";
import { useCharactersStore } from "../store/references";

/**
 * "Does Flow accept videos of this model?"
 *
 * Flow's public-figure filter silently drops every video whose reference
 * shows a face it reads as a real / famous person: the job is accepted,
 * never rendered, credits refunded, and the app only learns of it from a
 * timeout. On 2026-10-22 it was the face, not the prompt, the scene or the
 * model family: the same prompt with another portrait as the only
 * ingredient rendered in 67 s, with this one it was dropped (Omni and Veo).
 *
 * So the check is one 8 s Omni clip with the portrait as its only
 * ingredient (~12 credits when it passes, 68 s; nothing when dropped), with
 * a short poll budget — a clip that is not back in ~2.5 minutes was dropped.
 * Not 4 s: the same passing portrait was dropped at 4 s (abra_r2v_4s) and
 * rendered at 8 s, so a short probe would condemn every face.
 */
const PROBE_PROMPT =
  "The person looks at the camera, blinks and smiles gently; subtle natural breathing. Locked-off camera, plain soft light.";
const PROBE_SECONDS = 8;
const PROBE_WAIT_S = 150;
const POLL_MS = 4000;

export async function probeModel(mediaId: string): Promise<FlowCheck> {
  const gen = useGenerationStore.getState();
  const projectId = await gen.ensureProjectId();
  if (!projectId) throw new Error("Chưa kết nối xong Google Flow — làm theo bảng hướng dẫn vừa mở rồi bấm lại.");
  const req = await createRequest({
    type: "gen_video_omni",
    params: {
      prompt: PROBE_PROMPT,
      media_provider: "flow",
      project_id: projectId,
      ref_media_ids: [mediaId],
      duration_s: PROBE_SECONDS,
      aspect_ratio: "VIDEO_ASPECT_RATIO_PORTRAIT",
      paygate_tier: gen.paygateTier ?? "PAYGATE_TIER_ONE",
      max_wait_s: PROBE_WAIT_S,
    },
  });
  const deadline = Date.now() + (PROBE_WAIT_S + 120) * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    const r = await getRequest(req.id);
    if (r.status === "done") return { status: "ok", at: Date.now(), requestId: req.id, mediaId };
    if (r.status === "timeout" || /FLOW_DROPPED_JOB/i.test(r.error ?? "")) {
      return { status: "blocked", at: Date.now(), requestId: req.id, mediaId };
    }
    if (r.status === "failed" || r.status === "canceled") {
      // Not a verdict on the face (no credits, extension gone, …).
      throw new Error(r.error || `Kiểm tra không chạy được (${r.status}).`);
    }
  }
  throw new Error("Kiểm tra quá lâu chưa có kết quả. Xem lại ở Lịch sử & credit.");
}

/** Probe the model node's photo, then remember the verdict on the node and
 * on the saved library model with the same photo (if any). */
export async function checkModelNode(node: FlowNode): Promise<FlowCheck> {
  const mediaId = node.data.mediaId as string;
  const board = useBoardStore.getState();
  board.updateNodeData(node.id, { flowCheck: { status: "running", at: Date.now(), mediaId } });
  let verdict: FlowCheck;
  try {
    verdict = await probeModel(mediaId);
  } catch (err) {
    board.updateNodeData(node.id, { flowCheck: undefined });
    throw err;
  }
  board.updateNodeData(node.id, { flowCheck: verdict });
  const dbId = parseInt(node.id, 10);
  if (!isNaN(dbId)) patchNode(dbId, { data: { flowCheck: verdict } }).catch(() => {});
  await rememberOnLibrary(mediaId, verdict).catch(() => {});
  return verdict;
}

async function rememberOnLibrary(mediaId: string, verdict: FlowCheck): Promise<void> {
  const saved = (await listCharacters()).find((c) => c.mediaId === mediaId);
  if (!saved) return;
  await updateCharacterMeta(saved.id, { ...saved.meta, flowCheck: verdict });
  void useCharactersStore.getState().load(true);
}

/** The verdict known for a photo: the node's own, else the library's. */
export function knownFlowCheck(node: FlowNode | null | undefined): FlowCheck | null {
  if (!node) return null;
  const mediaId = node.data.mediaId;
  const own = node.data.flowCheck as FlowCheck | undefined;
  // Only for the photo it was made on (older verdicts carry no mediaId).
  if (own?.status && (!own.mediaId || own.mediaId === mediaId)) return own;
  const saved = useCharactersStore.getState().items.find((c) => c.mediaId === mediaId);
  return saved?.meta.flowCheck ?? null;
}
