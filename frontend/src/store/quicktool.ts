import { create } from "zustand";
import {
  autoPrompt, createEdge, createNode, patchBoardData, patchNode, uploadImage, uploadReferenceVideo,
  writeNarrationApi, type ExportItem, type QuicktoolState,
} from "../api/client";

/** One entry of a drama clip's play order. */
export interface SequenceItem {
  node: FlowNode;
  kind: "image" | "video";
  keepAudio: boolean;
}
import { requestAutoBrief } from "../api/autoBrief";
import { buildCharacterPrompt } from "../lib/characterPrompt";
import { deriveRoles, hasMedia, isBusy, type ClipRoles } from "../quicktool/roles";
import { useBoardStore, type FlowNode } from "./board";
import { useGenerationStore } from "./generation";
import type { CountryKey, GenderKey, VibeKey } from "../constants/character";
import { toast } from "./toast";

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
  _createExportNode(): Promise<string | null>;
  /** A real photo onto a product / model node (Flow upload + vision brief). */
  uploadToNode(rfId: string, file: File): Promise<boolean>;
  /** Another product photo (back, texture, in hand…): a new photo node wired
   * to the same scenes as the main one, with `file` uploaded onto it. */
  addProductPhoto(file: File): Promise<boolean>;
  /** Remove an extra product photo (never the main one). */
  removeProductPhoto(rfId: string): Promise<void>;
  /** The user's own footage for a scene (step 4): a local video Asset
   * put on the scene's video node, in place of a Flow render. */
  uploadVideoToScene(sceneIndex: number, file: File): Promise<boolean>;
  exportClip(): Promise<boolean>;
  // Drama clips: the play order (beat stills + spliced-in footage).
  isDrama(): boolean;
  sequenceItems(): SequenceItem[];
  saveSequence(items: SequenceItem[]): void;
  moveSequenceItem(index: number, delta: number): void;
  removeSequenceItem(index: number): void;
  setSequenceKeepAudio(index: number, keep: boolean): void;
  restoreSequence(): void;
  insertClip(file: File, afterIndex: number): Promise<boolean>;
  exportItems(): ExportItem[];
  runAuto(): Promise<void>;
  stopAuto(): void;
  /** Library-level queue: auto-run several clips one after another. */
  queue: QueueState;
  runQueue(boardIds: number[]): Promise<void>;
  stopQueue(): void;
  clearError(): void;
}

export interface QueueState {
  /** Board ids still to run, in order (the current one excluded). */
  pending: number[];
  current: number | null;
  done: number[];
  failed: Record<number, string>;
  running: boolean;
}

const EMPTY_QUEUE: QueueState = { pending: [], current: null, done: [], failed: {}, running: false };

const IMAGE_AR = "IMAGE_ASPECT_RATIO_PORTRAIT";
/** Product photos per clip, main one included. Every one is fed to every
 * scene as a reference; past a few the item gets no sharper and the
 * request only gets heavier. */
export const MAX_PRODUCT_PHOTOS = 4;
const VIDEO_AR = "VIDEO_ASPECT_RATIO_PORTRAIT";

/** The export-node creation currently running, shared by concurrent callers. */
let exportNodeInFlight: Promise<string | null> | null = null;

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
  queue: EMPTY_QUEUE,

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
    // Step 5 mounts twice under StrictMode and both mounts asked for the
    // node before the first answer landed, leaving duplicate "Clip hoàn
    // chỉnh" nodes; one in-flight creation serves every caller.
    if (exportNodeInFlight) return exportNodeInFlight;
    exportNodeInFlight = (async () => {
      try {
        return await get()._createExportNode();
      } finally {
        exportNodeInFlight = null;
      }
    })();
    return exportNodeInFlight;
  },

  async _createExportNode() {
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

  async uploadVideoToScene(sceneIndex, file) {
    const scene = get().roles().scenes.find((s) => s.index === sceneIndex);
    if (!scene?.video || isBusy(scene.video)) return false;
    const video = scene.video;
    const dbId = parseInt(video.id, 10);
    try {
      // Stored like a reference video: a local Asset, never sent to Flow.
      const up = await uploadReferenceVideo(file);
      const patch = { mediaId: up.media_id, mediaIds: [up.media_id], variantCount: 1, status: "done" as const,
                      error: undefined, uploaded: true };
      useBoardStore.getState().updateNodeData(video.id, patch);
      if (!isNaN(dbId)) {
        patchNode(dbId, { status: "done", data: { ...patch, error: null, renderedAt: new Date().toISOString() } })
          .catch(() => {});
      }
      return true;
    } catch (err) {
      set({ error: `Không tải được video: ${err instanceof Error ? err.message : "lỗi"}` });
      return false;
    }
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

  // ── Drama clips: the play order of beat stills and spliced-in footage ──

  isDrama() {
    const { boardId, boards } = useBoardStore.getState();
    return (boards.find((b) => b.id === boardId)?.data?.quicktool as QuicktoolState | undefined)?.template_id === "drama";
  },

  sequenceItems() {
    const { boardId, boards, nodes } = useBoardStore.getState();
    const qt = (boards.find((b) => b.id === boardId)?.data?.quicktool ?? {}) as QuicktoolState;
    const byShort = new Map(nodes.map((n) => [n.data.shortId, n]));
    const saved = qt.sequence ?? [];
    const items: SequenceItem[] = [];
    for (const entry of saved) {
      const node = byShort.get(entry.node);
      if (!node) continue;
      const kind = node.data.type === "video" ? "video" : "image";
      items.push({ node, kind, keepAudio: entry.keepAudio ?? kind === "video" });
    }
    if (saved.length === 0) {
      // No order saved yet (an older board): the stills in canvas order.
      for (const s of get().roles().scenes) items.push({ node: s.image, kind: "image", keepAudio: false });
    }
    return items;
  },

  saveSequence(items) {
    const boardId = useBoardStore.getState().boardId;
    if (boardId === null) return;
    const sequence = items.map((it) => ({ node: it.node.data.shortId, keepAudio: it.keepAudio }));
    const current = (useBoardStore.getState().boards.find((b) => b.id === boardId)?.data?.quicktool ?? {}) as QuicktoolState;
    const next = { ...current, sequence };
    useBoardStore.setState((s) => ({
      boards: s.boards.map((b) => b.id === boardId ? { ...b, data: { ...(b.data ?? {}), quicktool: next } } : b),
    }));
    patchBoardData(boardId, { quicktool: next }).catch(() => {});
  },

  moveSequenceItem(index, delta) {
    const items = get().sequenceItems();
    const to = index + delta;
    if (to < 0 || to >= items.length) return;
    [items[index], items[to]] = [items[to], items[index]];
    get().saveSequence(items);
  },

  removeSequenceItem(index) {
    const items = get().sequenceItems();
    const [gone] = items.splice(index, 1);
    if (!gone) return;
    get().saveSequence(items);
    // Spliced-in footage has no other home on the board; a beat still stays
    // (step 3 keeps it, "restore" brings it back).
    if (gone.kind === "video") void useBoardStore.getState().deleteNodeByRfId(gone.node.id);
  },

  setSequenceKeepAudio(index, keep) {
    const items = get().sequenceItems();
    if (!items[index]) return;
    items[index] = { ...items[index], keepAudio: keep };
    get().saveSequence(items);
  },

  restoreSequence() {
    const items = get().sequenceItems();
    const listed = new Set(items.map((it) => it.node.id));
    for (const s of get().roles().scenes) {
      if (!listed.has(s.image.id)) items.push({ node: s.image, kind: "image", keepAudio: false });
    }
    get().saveSequence(items);
  },

  async insertClip(file, afterIndex) {
    const board = useBoardStore.getState();
    if (board.boardId === null) return false;
    try {
      // Registered like a reference video: a local video Asset, never sent to Flow.
      const up = await uploadReferenceVideo(file);
      const items = get().sequenceItems();
      const anchor = items[Math.min(Math.max(afterIndex, 0), items.length - 1)];
      const dto = await createNode({
        board_id: board.boardId,
        type: "video",
        x: Math.round((anchor?.node.position.x ?? 0) + 380),
        y: Math.round(anchor?.node.position.y ?? items.length * 320),
        data: {
          title: `Clip chèn — ${file.name}`.slice(0, 80),
          mediaId: up.media_id, mediaIds: [up.media_id], variantCount: 1, narration: "",
          renderedAt: new Date().toISOString(),
        },
      });
      // createNode has no status field; the clip is ready as soon as it exists.
      patchNode(dto.id, { status: "done" }).catch(() => {});
      await board.refreshBoardState();
      const node = useBoardStore.getState().nodes.find((n) => n.id === String(dto.id));
      if (!node) throw new Error("node không xuất hiện trên board");
      const refreshed = get().sequenceItems();
      const at = Math.min(Math.max(afterIndex + 1, 0), refreshed.length);
      refreshed.splice(at, 0, { node, kind: "video", keepAudio: true });
      get().saveSequence(refreshed);
      return true;
    } catch (err) {
      set({ error: `Chèn clip thất bại: ${err instanceof Error ? err.message : "lỗi"}` });
      return false;
    }
  },

  exportItems() {
    return get().sequenceItems()
      .filter((it) => hasMedia(it.node))
      .map((it) => ({
        media_id: it.node.data.mediaId as string,
        kind: it.kind,
        narration: typeof it.node.data.narration === "string" ? it.node.data.narration.trim() : "",
        caption: typeof it.node.data.caption === "string" ? it.node.data.caption.trim() : "",
        original_audio: it.kind === "video" ? (it.keepAudio ? "keep" : "duck") : undefined,
        // The still/clip's own voice (step 2), read by `dispatchExport`.
        voice: typeof it.node.data.voice === "string" && it.node.data.voice ? it.node.data.voice : null,
      }));
  },

  async exportClip() {
    const board = useBoardStore.getState();
    const roles = get().roles();
    const drama = get().isDrama();
    const items = drama ? get().exportItems() : null;
    const clips = drama
      ? get().sequenceItems().filter((it) => hasMedia(it.node)).map((it) => it.node)
      : roles.scenes.map((s) => s.video).filter(hasMedia) as FlowNode[];
    if (clips.length === 0) {
      set({ error: drama ? "Chưa có ảnh nào để ghép — tạo ảnh ở bước 3." : "Chưa có video nào để ghép." });
      return false;
    }
    const exportId = await get().ensureExportNode();
    if (exportId === null) return false;
    const wired = new Set(useBoardStore.getState().edges.filter((e) => e.target === exportId).map((e) => e.source));
    for (const v of clips) {
      if (!wired.has(v.id)) await board.addEdgeFromConnection(v.id, exportId);
    }
    useGenerationStore.getState().clearError();
    await useGenerationStore.getState().dispatchExport(exportId, items ?? undefined);
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

      // Drama clips have no videos to render: the export animates the stills.
      if (!get().isDrama()) {
        set({ auto: "videos", autoMessage: "Tạo video từng cảnh (1–3 phút mỗi clip)…" });
        await get().generateAllVideos();
        for (const s of get().roles().scenes) {
          if (s.video) await waitForNode(s.video.id, hasMedia);
        }
        if (!stillRunning(get)) return;
      }

      const missing = !get().isDrama()
        && get().roles().scenes.some((s) => s.video && !(typeof s.video.data.narration === "string" && s.video.data.narration.trim()));
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

  async runQueue(boardIds) {
    if (get().queue.running || stillRunning(get) || boardIds.length === 0) return;
    const ids = Array.from(new Set(boardIds));
    set({ queue: { pending: ids.slice(1), current: ids[0], done: [], failed: {}, running: true }, error: null });
    for (let i = 0; i < ids.length; i++) {
      const q = get().queue;
      if (!q.running) break;
      const id = ids[i];
      set({ queue: { ...q, current: id, pending: ids.slice(i + 1) } });
      try {
        // The auto run works on the board store's active board.
        if (useBoardStore.getState().boardId !== id) await useBoardStore.getState().switchBoard(id);
        if (useBoardStore.getState().boardId !== id) throw new Error("không mở được clip");
        await get().runAuto();
        const auto = get().auto;
        if (auto === "done") {
          set({ queue: { ...get().queue, done: [...get().queue.done, id] } });
        } else {
          const why = auto === "stopped" ? "đã dừng" : get().error ?? "lỗi";
          set({ queue: { ...get().queue, failed: { ...get().queue.failed, [id]: why } } });
          if (auto === "stopped") break;
        }
      } catch (err) {
        set({ queue: { ...get().queue, failed: { ...get().queue.failed, [id]: err instanceof Error ? err.message : String(err) } } });
      }
    }
    set({ queue: { ...get().queue, current: null, pending: [], running: false }, auto: "idle", autoMessage: null });
    // Said as a toast from here, not from the library page: the page may not be open any more.
    const { done, failed } = get().queue;
    const bad = Object.keys(failed).length;
    if (bad) toast.warning(`Hàng đợi xong: ${done.length} clip hoàn tất, ${bad} clip lỗi (xem trên thẻ clip trong "Clip của tôi").`);
    else if (done.length) toast.success(`Hàng đợi xong: ${done.length} clip đã tạo xong.`);
  },

  stopQueue() {
    set({ queue: { ...get().queue, pending: [], running: false } });
    if (stillRunning(get)) get().stopAuto();
  },

  clearError() {
    set({ error: null });
  },
}));
