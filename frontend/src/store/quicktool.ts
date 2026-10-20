import { create } from "zustand";
import { autoPrompt, createEdge, createNode, patchBoardData, patchNode, uploadImage, writeNarrationApi, type QuicktoolState } from "../api/client";
import { requestAutoBrief } from "../api/autoBrief";
import { buildCharacterPrompt } from "../lib/characterPrompt";
import { deriveRoles, hasMedia, isBusy, type ClipRoles } from "../quicktool/roles";
import { useBoardStore, type FlowNode } from "./board";
import { useGenerationStore } from "./generation";
import type { CountryKey, GenderKey, VibeKey } from "../constants/character";

/**
 * The Quicktool wizard's driver. It owns no media state of its own: every
 * generation goes through `useGenerationStore.dispatchGeneration`, the
 * worker writes results onto the nodes, and the board store's polling
 * brings them back. This store only sequences the steps, keeps the
 * wizard's position on the board, and runs the "do everything" loop.
 */

export type AutoPhase = "idle" | "model" | "scenes" | "videos" | "narration" | "export" | "done" | "stopped" | "failed";

interface QuicktoolStore {
  step: number;
  auto: AutoPhase;
  autoMessage: string | null;
  error: string | null;
  setStep(step: number): void;
  /** Re-read `Board.data.quicktool.step` for the active board. */
  syncFromBoard(): void;
  roles(): ClipRoles;
  generateModel(): Promise<boolean>;
  generateScene(sceneIndex: number): Promise<boolean>;
  generateAllScenes(): Promise<void>;
  generateVideo(sceneIndex: number): Promise<boolean>;
  generateAllVideos(): Promise<void>;
  writeNarrations(): Promise<boolean>;
  /** The board's export node, created when missing. Returns its rfId. */
  ensureExportNode(): Promise<string | null>;
  /** A real photo onto a product / model node (Flow upload + vision brief). */
  uploadToNode(rfId: string, file: File): Promise<boolean>;
  /** Another product photo (back, texture, in hand…): a new photo node wired
   * to the same scenes as the main one, with `file` uploaded onto it. */
  addProductPhoto(file: File): Promise<boolean>;
  /** Remove an extra product photo (never the main one). */
  removeProductPhoto(rfId: string): Promise<void>;
  exportClip(): Promise<boolean>;
  runAuto(): Promise<void>;
  stopAuto(): void;
  clearError(): void;
}

const IMAGE_AR = "IMAGE_ASPECT_RATIO_PORTRAIT";
/** Product photos per clip, main one included. Every one is fed to every
 * scene as a reference; past a few the item gets no sharper and the
 * request only gets heavier. */
export const MAX_PRODUCT_PHOTOS = 4;
const VIDEO_AR = "VIDEO_ASPECT_RATIO_PORTRAIT";

function nodeById(id: string): FlowNode | undefined {
  return useBoardStore.getState().nodes.find((n) => n.id === id);
}

function persistStep(step: number) {
  const boardId = useBoardStore.getState().boardId;
  if (boardId === null) return;
  const current = (useBoardStore.getState().boards.find((b) => b.id === boardId)?.data?.quicktool
    ?? {}) as QuicktoolState;
  const next = { ...current, step };
  useBoardStore.setState((s) => ({
    boards: s.boards.map((b) => b.id === boardId ? { ...b, data: { ...(b.data ?? {}), quicktool: next } } : b),
  }));
  patchBoardData(boardId, { quicktool: next }).catch(() => {});
}

/** Resolve when `pred` holds for the node, or reject when it errors / the
 * board changes. Polls the board store, which the generation poll keeps
 * current. */
function waitForNode(id: string, pred: (n: FlowNode) => boolean, timeoutMs = 15 * 60_000): Promise<void> {
  const boardId = useBoardStore.getState().boardId;
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      if (useBoardStore.getState().boardId !== boardId) return reject(new Error("đã chuyển board"));
      const n = nodeById(id);
      if (!n) return reject(new Error("node đã bị xoá"));
      if (pred(n)) return resolve();
      if (n.data.status === "error" && !isBusy(n)) {
        return reject(new Error(String(n.data.error || "lỗi khi tạo")));
      }
      if (Date.now() - started > timeoutMs) return reject(new Error("quá thời gian chờ"));
      setTimeout(tick, 1500);
    };
    tick();
  });
}

function stillRunning(get: () => QuicktoolStore): boolean {
  const a = get().auto;
  return a !== "stopped" && a !== "failed" && a !== "idle";
}

export const useQuicktoolStore = create<QuicktoolStore>((set, get) => ({
  step: 1,
  auto: "idle",
  autoMessage: null,
  error: null,

  setStep(step) {
    set({ step });
    persistStep(step);
  },

  syncFromBoard() {
    const { boardId, boards } = useBoardStore.getState();
    const saved = (boards.find((b) => b.id === boardId)?.data?.quicktool ?? {}) as QuicktoolState;
    set({ step: saved.step && saved.step >= 1 && saved.step <= 5 ? saved.step : 1, auto: "idle", autoMessage: null, error: null });
  },

  roles() {
    const { nodes, edges } = useBoardStore.getState();
    return deriveRoles(nodes, edges);
  },

  async generateModel() {
    const model = get().roles().model;
    if (!model) return true; // templates without a model (none today) just skip
    if (hasMedia(model) || isBusy(model)) return true;
    const d = model.data;
    const prompt = buildCharacterPrompt(
      (d.charGender as GenderKey | undefined) ?? "female",
      (d.charCountry as CountryKey | undefined) ?? "vn",
      (d.charVibe as VibeKey | undefined) ?? "clean",
      typeof d.charExtras === "string" ? d.charExtras : "",
    );
    const ok = await useGenerationStore.getState().dispatchGeneration(model.id, {
      prompt, aspectRatio: IMAGE_AR, variantCount: 1,
    });
    if (!ok) set({ error: useGenerationStore.getState().error ?? "không tạo được người mẫu" });
    return ok;
  },

  async generateScene(sceneIndex) {
    const scene = get().roles().scenes.find((s) => s.index === sceneIndex);
    if (!scene || isBusy(scene.image)) return false;
    let prompt = typeof scene.image.data.prompt === "string" ? scene.image.data.prompt.trim() : "";
    const dbId = parseInt(scene.image.id, 10);
    if (!prompt && !isNaN(dbId)) {
      useBoardStore.getState().updateNodeData(scene.image.id, { autoPromptStatus: "pending" });
      try {
        prompt = (await autoPrompt(dbId)).prompt;
        useBoardStore.getState().updateNodeData(scene.image.id, { autoPromptStatus: "done" });
      } catch (err) {
        useBoardStore.getState().updateNodeData(scene.image.id, { autoPromptStatus: "failed" });
        set({ error: `Cảnh ${sceneIndex}: không tự viết được prompt (${err instanceof Error ? err.message : "lỗi"})` });
        return false;
      }
    }
    const ok = await useGenerationStore.getState().dispatchGeneration(scene.image.id, {
      prompt, aspectRatio: IMAGE_AR, kind: "image", variantCount: 1,
    });
    if (!ok) set({ error: useGenerationStore.getState().error ?? `Cảnh ${sceneIndex}: không gửi được` });
    return ok;
  },

  async generateAllScenes() {
    for (const s of get().roles().scenes) {
      if (!hasMedia(s.image) && !isBusy(s.image)) await get().generateScene(s.index);
    }
  },

  async generateVideo(sceneIndex) {
    const scene = get().roles().scenes.find((s) => s.index === sceneIndex);
    if (!scene?.video || !hasMedia(scene.image) || isBusy(scene.video)) return false;
    const video = scene.video;
    let prompt = typeof video.data.prompt === "string" ? video.data.prompt.trim() : "";
    const dbId = parseInt(video.id, 10);
    if (!prompt && !isNaN(dbId)) {
      useBoardStore.getState().updateNodeData(video.id, { autoPromptStatus: "pending" });
      try {
        prompt = (await autoPrompt(dbId, { camera: "static" })).prompt;
        useBoardStore.getState().updateNodeData(video.id, { autoPromptStatus: "done" });
        patchNode(dbId, { data: { prompt } }).catch(() => {});
      } catch (err) {
        useBoardStore.getState().updateNodeData(video.id, { autoPromptStatus: "failed" });
        set({ error: `Video ${sceneIndex}: không tự viết được prompt (${err instanceof Error ? err.message : "lỗi"})` });
        return false;
      }
    }
    // Omni Flash (the default) takes every upstream image as an ingredient
    // and ignores sourceMediaId; Veo needs the scene as its start frame.
    const ok = await useGenerationStore.getState().dispatchGeneration(video.id, {
      prompt, aspectRatio: VIDEO_AR, kind: "video",
      sourceMediaId: scene.image.data.mediaId as string, variantCount: 1,
    });
    if (!ok) set({ error: useGenerationStore.getState().error ?? `Video ${sceneIndex}: không gửi được` });
    return ok;
  },

  async generateAllVideos() {
    for (const s of get().roles().scenes) {
      if (s.video && hasMedia(s.image) && !hasMedia(s.video) && !isBusy(s.video)) {
        await get().generateVideo(s.index);
      }
    }
  },

  async writeNarrations() {
    const boardId = useBoardStore.getState().boardId;
    const ids = get().roles().scenes
      .map((s) => s.video)
      .filter((v): v is FlowNode => !!v)
      .map((v) => parseInt(v.id, 10))
      .filter((n) => !isNaN(n));
    if (boardId === null || ids.length === 0) return false;
    try {
      const res = await writeNarrationApi(boardId, ids);
      for (const [nodeId, line] of Object.entries(res.narrations)) {
        useBoardStore.getState().updateNodeData(String(nodeId), { narration: line });
      }
      return true;
    } catch (err) {
      set({ error: `Không viết được lời thoại: ${err instanceof Error ? err.message : "lỗi"}` });
      return false;
    }
  },

  async ensureExportNode() {
    const board = useBoardStore.getState();
    const existing = get().roles().export;
    if (existing) return existing.id;
    // One export node per board, wired from every clip in scene order; it
    // is created on first use so a template board stays uncluttered.
    const right = Math.max(0, ...board.nodes.map((n) => n.position.x)) + 380;
    const id = await board.addNodeOfType("export", { x: right, y: 0 });
    if (id === null) {
      set({ error: board.error ?? "Không tạo được node Xuất video" });
      return null;
    }
    const dbId = parseInt(id, 10);
    const title = "Clip hoàn chỉnh";
    useBoardStore.getState().updateNodeData(id, { title });
    if (!isNaN(dbId)) patchNode(dbId, { data: { title } }).catch(() => {});
    return id;
  },

  async addProductPhoto(file) {
    const { boardId, edges } = useBoardStore.getState();
    const products = get().roles().products;
    const main = products[0];
    if (boardId === null || !main) return false;
    if (products.length >= MAX_PRODUCT_PHOTOS) {
      set({ error: `Tối đa ${MAX_PRODUCT_PHOTOS} ảnh sản phẩm cho một clip.` });
      return false;
    }
    const targets = edges.filter((e) => e.source === main.id).map((e) => e.target);
    try {
      const dto = await createNode({
        board_id: boardId, type: "visual_asset",
        x: Math.round(main.position.x), y: Math.round(main.position.y + 320 * products.length),
        data: { title: `Sản phẩm — ảnh ${products.length + 1}` },
      });
      await Promise.all(targets.map((t) => createEdge({ board_id: boardId, source_id: dto.id, target_id: parseInt(t, 10) })));
      await useBoardStore.getState().refreshBoardState();
      return await get().uploadToNode(String(dto.id), file);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "không thêm được ảnh" });
      return false;
    }
  },

  async removeProductPhoto(rfId) {
    const products = get().roles().products;
    if (products[0]?.id === rfId) return;
    await useBoardStore.getState().deleteNodeByRfId(rfId);
  },

  async uploadToNode(rfId, file) {
    const projectId = await useGenerationStore.getState().ensureProjectId();
    if (!projectId) {
      set({ error: "Chưa có Flow project — ghim một project trong Settings." });
      return false;
    }
    const dbId = parseInt(rfId, 10);
    try {
      const resp = await uploadImage(file, projectId, isNaN(dbId) ? undefined : dbId);
      const patch = { mediaId: resp.media_id, mediaIds: [resp.media_id], variantCount: 1,
                      aspectRatio: resp.aspect_ratio, status: "done" as const };
      useBoardStore.getState().updateNodeData(rfId, { ...patch, aiBrief: undefined });
      if (!isNaN(dbId)) {
        patchNode(dbId, { status: "done", data: { ...patch, aiBrief: null, renderedAt: new Date().toISOString() } })
          .catch(() => {});
      }
      requestAutoBrief(rfId, resp.media_id);
      return true;
    } catch (err) {
      set({ error: `Upload thất bại: ${err instanceof Error ? err.message : "lỗi"}` });
      return false;
    }
  },

  async exportClip() {
    const board = useBoardStore.getState();
    const roles = get().roles();
    const clips = roles.scenes.map((s) => s.video).filter(hasMedia) as FlowNode[];
    if (clips.length === 0) {
      set({ error: "Chưa có video nào để ghép." });
      return false;
    }
    const exportId = await get().ensureExportNode();
    if (exportId === null) return false;
    const wired = new Set(useBoardStore.getState().edges.filter((e) => e.target === exportId).map((e) => e.source));
    for (const v of clips) {
      if (!wired.has(v.id)) await board.addEdgeFromConnection(v.id, exportId);
    }
    useGenerationStore.getState().clearError();
    await useGenerationStore.getState().dispatchExport(exportId);
    const err = useGenerationStore.getState().error;
    if (err) {
      set({ error: err });
      return false;
    }
    return true;
  },

  async runAuto() {
    if (stillRunning(get)) return;
    set({ auto: "model", autoMessage: "Tạo người mẫu…", error: null });
    try {
      const r0 = get().roles();
      if (r0.model && !hasMedia(r0.model)) {
        if (!(await get().generateModel())) throw new Error(get().error ?? "người mẫu");
        await waitForNode(r0.model.id, hasMedia);
      }
      if (!stillRunning(get)) return;

      set({ auto: "scenes", autoMessage: "Tạo ảnh các cảnh…" });
      await get().generateAllScenes();
      for (const s of get().roles().scenes) await waitForNode(s.image.id, hasMedia);
      if (!stillRunning(get)) return;

      set({ auto: "videos", autoMessage: "Tạo video từng cảnh (1–3 phút mỗi clip)…" });
      await get().generateAllVideos();
      for (const s of get().roles().scenes) {
        if (s.video) await waitForNode(s.video.id, hasMedia);
      }
      if (!stillRunning(get)) return;

      const missing = get().roles().scenes.some((s) => s.video && !(typeof s.video.data.narration === "string" && s.video.data.narration.trim()));
      if (missing) {
        set({ auto: "narration", autoMessage: "Viết lời thoại…" });
        await get().writeNarrations();
      }
      if (!stillRunning(get)) return;

      set({ auto: "export", autoMessage: "Ghép clip + lồng tiếng…" });
      if (!(await get().exportClip())) throw new Error(get().error ?? "xuất video");
      const exp = get().roles().export;
      if (exp) await waitForNode(exp.id, hasMedia);
      set({ auto: "done", autoMessage: "Xong — clip đã sẵn sàng ở bước 5.", step: 5 });
      persistStep(5);
    } catch (err) {
      if (get().auto === "stopped") return;
      set({ auto: "failed", autoMessage: null, error: err instanceof Error ? err.message : String(err) });
    }
  },

  stopAuto() {
    set({ auto: "stopped", autoMessage: "Đã dừng. Việc đang chạy trên Flow vẫn hoàn tất; bấm từng bước để tiếp tục." });
  },

  clearError() {
    set({ error: null });
  },
}));
