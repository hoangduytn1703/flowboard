export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    // Session gone (logged out elsewhere, agent restarted with auth on):
    // the auth gate listens for this and shows the login page.
    if (res.status === 401) window.dispatchEvent(new Event("flowboard:unauthorized"));
    // the agent's own words (`detail`), made readable — not "502 Bad Gateway"
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<T>;
}

// Turn the agent's / Flow's error tokens into a sentence a seller can act on (Vietnamese, no env-variable names).
// Returns null when the token is unrecognised, so the caller falls through to the raw message.
export function humanizeBackendError(token: string): string | null {
  const t = token.toLowerCase();
  if (t.startsWith("paygate_tier_invalid")) {
    return "DFlow chưa biết tài khoản Google Flow của bạn là gói Pro hay Ultra. Mở Cài đặt → 🖥 Máy này → chọn đúng gói rồi thử lại.";
  }
  if (t.includes("no_flow_project")) {
    return "Chưa chọn dự án Flow. Mở flow.google.com, bấm “+ Dự án mới”, rồi vào Hôm nay → Thiết lập → “Dùng dự án đang mở”.";
  }
  if (t.includes("extension_disconnected") || t.includes("extension not connected")) {
    return "Chrome chưa kết nối với DFlow: mở Chrome (có extension DFlow Bridge) và một tab flow.google.com rồi thử lại.";
  }
  if (t.includes("extension_outdated")) {
    return "Extension DFlow Bridge là bản cũ: vào chrome://extensions bấm nút tải lại (↻) ở ô DFlow Bridge, rồi F5 tab Flow.";
  }
  if (t.includes("unsupported_on_batch_api")) {
    return "Google Flow hiện không còn hỗ trợ thao tác này — thử lại cũng không được.";
  }
  if (t.includes("no_at_token")) {
    return "Tab Flow đang mở nhưng chưa tải xong. Tải lại tab flow.google.com (F5), chờ trang hiện đầy đủ rồi thử lại.";
  }
  if (t.includes("no_flow_tab") || t.includes("flow_tab_discarded")) {
    return "Cần một tab flow.google.com đã đăng nhập và để mở trong Chrome. Mở tab đó rồi thử lại.";
  }
  if (t === "no_media_id_in_upload_response") {
    return "Google Flow nhận ảnh nhưng không giữ — thường do bộ lọc nội dung (logo, watermark, hình có bản quyền). Thử ảnh khác.";
  }
  if (t.includes("captcha_failed: no current window")) {
    return "Chrome không có cửa sổ nào đang mở. Mở một cửa sổ Chrome rồi thử lại.";
  }
  if (t.startsWith("captcha_failed")) {
    return "Google Flow chưa xác minh được trình duyệt (captcha). Tải lại tab flow.google.com (F5) rồi thử lại sau vài giây.";
  }
  if (t.includes("flow_dropped_job") || t.includes("timeout_waiting_video")) {
    return "Flow bỏ lượt này (thường do gương mặt người mẫu hoặc nội dung bị lọc) — credit được hoàn. Thử tạo lại hoặc đổi ảnh.";
  }
  if (t.includes("returned no media url")) {
    return "Flow không trả ảnh — thường do bộ lọc nội dung. Sửa mô tả ảnh (bỏ từ nhạy cảm) rồi tạo lại.";
  }
  if (t.startsWith("public_error_")) {
    return "Flow từ chối: " + token.replace(/^PUBLIC_ERROR_/i, "").replace(/_/g, " ").toLowerCase();
  }
  if (/^(502|503|504)/.test(t) || t === "failed to fetch" || t.includes("networkerror")) {
    return "DFlow chưa trả lời được (đang khởi động hoặc mất kết nối). Chờ vài giây rồi thử lại.";
  }
  return null;
}

export async function extractErrorMessage(res: Response): Promise<string> {
  let detail: unknown;
  try {
    detail = await res.json();
  } catch {
    try {
      detail = await res.text();
    } catch {
      return `${res.status} ${res.statusText}`;
    }
  }
  const inner =
    typeof detail === "object" && detail !== null && "detail" in detail
      ? (detail as { detail: unknown }).detail
      : detail;
  if (typeof inner === "string" && inner) {
    return humanizeBackendError(inner) ?? inner;
  }
  if (inner && typeof inner === "object") {
    const obj = inner as Record<string, unknown>;
    if (typeof obj.message === "string" && obj.message) {
      return humanizeBackendError(obj.message) ?? obj.message;
    }
    try {
      return JSON.stringify(inner);
    } catch {
      // fall through
    }
  }
  return `${res.status} ${res.statusText}`;
}

export interface WsStats {
  connected: boolean;
  flow_key_present: boolean;
  token_age_s: number | null;
  pending: number;
  request_count: number;
  success_count: number;
  failed_count: number;
  last_error: string | null;
}

export interface HealthResponse {
  ok: boolean;
  extension_connected: boolean;
  ws_stats?: WsStats;
}

export function getHealth() {
  return api<HealthResponse>("/api/health");
}

// ── DTOs ────────────────────────────────────────────────────────────────────

export type NodeType = "character" | "image" | "video" | "prompt" | "note" | "visual_asset" | "Storyboard" | "merge" | "export";
export type NodeStatus = "idle" | "queued" | "running" | "done" | "error";

export interface Board {
  id: number;
  name: string;
  created_at: string;
  /** Board settings; the Quicktool wizard keeps its state under `quicktool`. */
  data?: Record<string, unknown>;
}

/** What the Quicktool wizard stores on a board (`Board.data.quicktool`). */
export interface QuicktoolState {
  template_id?: string | null;
  product_id?: number | null;
  /** The channel (page) the clip is made for. */
  channel_id?: number | null;
  inputs?: Record<string, string>;
  /** 1 setup · 2 script · 3 images · 4 videos · 5 export */
  step?: number;
  /** Hands-only clip (no model): who the hands belong to and how they look. */
  hands?: { gender: "hands_female" | "hands_male"; country: string; look: string } | null;
  /** What a link / video clip was analysed as. */
  reference?: { category?: string | null } | null;
  /** Drama clips: the play order — beat stills and spliced-in footage, by node short id. */
  sequence?: { node: string; keepAudio?: boolean }[];
  drama?: { title?: string; hook?: string | null; tone?: string | null } | null;
  source_url?: string | null;
  /** "🔇 Không lời": no voice-over, no subtitles — the pictures and the clips' real sounds. */
  voiceless?: boolean;
}

/** The model picked on the review screen of a link / video clip, or on
 * step 1 of the wizard. `gender` "none" = no person at all. */
export interface CharacterPick {
  gender: "female" | "male" | "hands_female" | "hands_male" | "none";
  country?: string;
  vibe?: string;
  hand_look?: string;
}

/** Switch an existing clip between a model and hands-only. */
export async function setBoardModelMode(
  boardId: number,
  body: { mode: "person" | "hands"; gender: "female" | "male"; country?: string; vibe?: string; hand_look?: string },
): Promise<{ hands: QuicktoolState["hands"] }> {
  const res = await fetch(`/api/boards/${boardId}/model-mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export interface BoardSummary extends Board {
  summary: {
    scenes: number;
    scenes_done: number;
    clips: number;
    clips_done: number;
    /** Scenes / clips whose last generation failed. */
    errors: number;
    clip_errors: number;
    exported: boolean;
    /** Media id of the finished clip, if any. */
    export_media: string | null;
    /** When the finished clip was downloaded (ms), via the zip or step 5. */
    downloaded_at: number | null;
    thumbnail: string | null;
  };
}

/** The picture of a clip card: its first scene image, else a still taken from its finished video
 * (`/api/media/{id}/poster` — a dubbed / uploaded / CapCut clip has no scene images), else none. */
export function clipThumbUrl(s: BoardSummary["summary"]): string | null {
  if (s.thumbnail) return mediaUrl(s.thumbnail);
  if (s.export_media) return `/api/media/${encodeURIComponent(s.export_media.replace(/^media\//, ""))}/poster`;
  return null;
}

/** One .zip with the finished clips of these boards (marks them downloaded). */
export function exportsZipUrl(boardIds: number[]): string {
  return `/api/exports/zip?ids=${boardIds.join(",")}`;
}

export function listBoardSummaries(): Promise<BoardSummary[]> {
  return api<BoardSummary[]>("/api/boards?summary=true");
}

/** Shallow-merge `data` into the board's settings (a null value removes a key). */
/** How many of a clip's scenes already have their 60 fps copy, made in the background (services/smooth_prewarm). */
export interface Smooth60Status {
  total: number;
  ready: number;
  running: number;
}

export function getSmooth60(boardId: number): Promise<Smooth60Status> {
  return api<Smooth60Status>(`/api/boards/${boardId}/smooth60`);
}

/** "Mượt 60 fps" turned on: the clip's scenes are smoothed in the background now, so "Ghép" does not wait. */
export function warmSmooth60(boardId: number): Promise<Smooth60Status> {
  return api<Smooth60Status>(`/api/boards/${boardId}/smooth60`, { method: "POST" });
}

export function patchBoardData(id: number, data: Record<string, unknown>): Promise<Board> {
  return api<Board>(`/api/boards/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ data }),
  });
}

export interface NodeDTO {
  id: number;
  board_id: number;
  short_id: string;
  type: NodeType;
  x: number;
  y: number;
  w: number;
  h: number;
  data: Record<string, unknown>;
  status: NodeStatus;
  created_at: string;
}

export interface EdgeDTO {
  id: number;
  board_id: number;
  source_id: number;
  target_id: number;
  kind: string;
  // null when the upstream is single-variant (or the edge hasn't been
  // pinned yet — natural fallback to source.mediaId at dispatch time).
  // 0-based index into the source node's `data.mediaIds[]` when the
  // user has explicitly picked a variant.
  source_variant_idx: number | null;
}

export interface BoardDetail {
  board: Board;
  nodes: NodeDTO[];
  edges: EdgeDTO[];
}

// ── API methods ──────────────────────────────────────────────────────────────

export function listBoards(): Promise<Board[]> {
  return api<Board[]>("/api/boards");
}

export function createBoard(name: string): Promise<Board> {
  return api<Board>("/api/boards", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function getBoard(id: number): Promise<BoardDetail> {
  return api<BoardDetail>(`/api/boards/${id}`);
}

export function patchBoard(id: number, name: string): Promise<Board> {
  return api<Board>(`/api/boards/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export function deleteBoard(id: number): Promise<{ deleted: number }> {
  return api<{ deleted: number }>(`/api/boards/${id}`, { method: "DELETE" });
}

export function createNode(input: {
  board_id: number;
  type: NodeType;
  x: number;
  y: number;
  data?: object;
}): Promise<NodeDTO> {
  return api<NodeDTO>("/api/nodes", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/**
 * Shallow-merge patch for `node.data` — the backend (see
 * agent/flowboard/routes/nodes.py::update_node) merges this dict into
 * the existing JSON column instead of replacing it.
 *
 * Conventions:
 *   - Keys present in the patch override existing values.
 *   - Keys absent from the patch are PRESERVED (this is what the type
 *     guarantees over a wholesale replace).
 *   - A value of `null` is the explicit "delete this key" sentinel.
 *     Use it instead of `undefined` to clear fields like `aiBrief`
 *     after a regen — `undefined` gets dropped by JSON.stringify and
 *     would leave the stale value in place after the merge.
 *   - Merge depth is ONE LEVEL. Nested dict values are wholesale-
 *     replaced, not deep-merged. None of FlowboardNodeData's current
 *     fields nest, so this is a non-issue today; revisit if a future
 *     field stores objects.
 *
 * Pre-merge call sites that built the full `data` from scratch and
 * forgot a sibling field caused a real data-loss regression
 * (`aspectRatio` was wiped on every image gen by the auto-brief
 * patch). Sticking to deltas-only with this type as the contract
 * prevents that whole class of bug.
 */
export type DataPatch = Record<string, unknown>;

// The agent merges a PATCH into the node's stored data (read → merge →
// write), so two PATCHes of one node in flight at once lose one of them:
// quick clicks in step 5 (order, cut, skip) saved stale values (2026-10-24,
// worse since each call is ~200 ms on Neon). Calls for the same node wait
// for the previous one; different nodes still go in parallel.
const nodePatchQueue = new Map<number, Promise<unknown>>();

export function patchNode(
  id: number,
  patch: Partial<
    Pick<Omit<NodeDTO, "data">, "x" | "y" | "w" | "h" | "status">
  > & { data?: DataPatch },
): Promise<NodeDTO> {
  const prev = nodePatchQueue.get(id) ?? Promise.resolve();
  const next = prev.catch(() => {}).then(() => api<NodeDTO>(`/api/nodes/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  }));
  nodePatchQueue.set(id, next);
  void next.finally(() => { if (nodePatchQueue.get(id) === next) nodePatchQueue.delete(id); }).catch(() => {});
  return next;
}

export function deleteNode(id: number): Promise<{ ok: true; deleted_edges: number[] }> {
  return api<{ ok: true; deleted_edges: number[] }>(`/api/nodes/${id}`, {
    method: "DELETE",
  });
}

export function createEdge(input: {
  board_id: number;
  source_id: number;
  target_id: number;
  kind?: string;
  source_variant_idx?: number | null;
}): Promise<EdgeDTO> {
  return api<EdgeDTO>("/api/edges", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/**
 * Update an edge's variant pin without recreating it. Pass
 * `source_variant_idx: null` explicitly to clear the pin (revert to
 * the source's active mediaId at dispatch time). Omit the field to
 * leave it untouched.
 */
export function patchEdge(
  id: number,
  patch: { source_variant_idx?: number | null },
): Promise<EdgeDTO> {
  return api<EdgeDTO>(`/api/edges/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteEdge(id: number): Promise<{ ok: true }> {
  return api<{ ok: true }>(`/api/edges/${id}`, {
    method: "DELETE",
  });
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export type ChatRole = "user" | "assistant" | "system";

export interface ChatAttachmentDTO {
  id: number;
  asset_id: number;
  mime: string;
  url: string;
}

export interface ChatMessageDTO {
  id: number;
  board_id: number;
  role: ChatRole;
  content: string;
  mentions: string[];
  attachments: ChatAttachmentDTO[];
  created_at: string;
}

export interface PlanDTO {
  id: number;
  board_id: number;
  spec: {
    nodes: Array<{ tmp_id?: string; type: string; params?: Record<string, unknown> }>;
    edges: Array<{ from: string; to: string; kind?: string }>;
    layout_hint?: string;
  };
  status: "draft" | "approved" | "running" | "done" | "failed";
  created_at: string;
}

// Dock flow: POST returns fast with the user message + run id; the agent
// loop runs server-side and the client polls the active run.
export interface ChatSendResponse {
  user: ChatMessageDTO;
  run_id: number;
}

export interface ChatRunDTO {
  id: number;
  board_id: number;
  user_message_id: number;
  status: "running" | "done" | "failed";
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export function listChatMessages(boardId: number) {
  return api<ChatMessageDTO[]>(`/api/boards/${boardId}/chat`);
}

export function sendChatMessage(
  boardId: number,
  message: string,
  mentions: string[],
  attachmentIds: number[] = [],
) {
  return api<ChatSendResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      board_id: boardId,
      message,
      mentions,
      attachment_ids: attachmentIds,
    }),
  });
}

export function getActiveChatRun(boardId: number) {
  return api<ChatRunDTO | null>(`/api/boards/${boardId}/chat/runs/active`);
}

export interface ChatUploadResult {
  assets: Array<{ id: number; mime: string; url: string }>;
}

// Multipart upload for chat attachments. Uses raw fetch (not api())
// because api() pins Content-Type: application/json, which would break
// the multipart boundary the browser sets on FormData.
export async function uploadChatAttachments(
  boardId: number,
  files: File[],
): Promise<ChatUploadResult> {
  const form = new FormData();
  form.set("board_id", String(boardId));
  for (const f of files) form.append("files", f, f.name);
  const res = await fetch("/api/chat/attachments", {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `uploadChatAttachments: ${res.status}${detail ? ` ${detail}` : ""}`,
    );
  }
  return res.json() as Promise<ChatUploadResult>;
}

// ── Generation ───────────────────────────────────────────────────────────────

export interface BoardProject {
  flow_project_id: string;
  created: boolean;
}

export interface RequestDTO {
  id: number;
  node_id: number | null;
  type: string;
  params: Record<string, unknown>;
  // 'canceled' = user cancelled the request from the activity bell.
  // 'timeout' = backend's 5-minute video-gen budget elapsed; the row
  // self-transitions out of running. Both are terminal states.
  status: "queued" | "running" | "done" | "failed" | "canceled" | "timeout";
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export function ensureBoardProject(boardId: number) {
  return api<BoardProject>(`/api/boards/${boardId}/project`, { method: "POST" });
}

export function getBoardProject(boardId: number) {
  return api<BoardProject>(`/api/boards/${boardId}/project`).catch(() => null);
}

// ── Auth / profile ───────────────────────────────────────────────────────

export interface AuthMe {
  // Identity rode on the Bearer token the extension sniffed off
  // aisandbox-pa. Since Flow moved to flow.google.com no Bearer is minted,
  // so these stay null and `identity_available` is false — genuinely
  // unavailable, not pending. Don't poll waiting for them.
  email: string | null;
  name: string | null;
  picture: string | null;
  verified_email: boolean | null;
  identity_available: boolean;
  // The tier generation will actually use. Same story as identity — it came
  // from /v1/credits with that token — so it is declared in the agent's
  // config now rather than discovered.
  paygate_tier: "PAYGATE_TIER_ONE" | "PAYGATE_TIER_TWO" | null;
  // "extension" when a live signal was available (an older extension that
  // still captures a token), "configured" otherwise — the normal case.
  paygate_tier_source: "extension" | "configured";
  // Set when the configured tier is not a value Flow recognises. Generation
  // will refuse until it is fixed, so surface it rather than waiting for a
  // dispatch to fail.
  paygate_tier_error: string | null;
  // Subscription SKU from /v1/credits — e.g. "WS_ULTRA" / "WS_PRO".
  // Available alongside paygate_tier; null until the credits fetch lands.
  sku: string | null;
  // Subscription credits remaining — bonus info from /v1/credits.
  // Frontend can display under the tier badge if desired.
  credits: number | null;
}

export function getAuthMe() {
  return api<AuthMe>("/api/auth/me").catch(() => null);
}

export interface AuthLogoutResult {
  ok: boolean;
  // Whether the agent could push a `logout` message to the extension
  // over its open WebSocket. False when no extension is connected —
  // agent-side caches were still cleared so the dashboard reflects
  // the logged-out state immediately.
  extension_notified: boolean;
}

export function logoutExtension() {
  return api<AuthLogoutResult>("/api/auth/logout", { method: "POST" });
}

export interface AuthScanResult {
  // True when the extension WebSocket is currently connected to the
  // agent. False means the user must install / enable / open Chrome.
  extension_connected: boolean;
  has_user_info: boolean;
  has_paygate_tier: boolean;
  // True when the agent had to ask the extension to re-fetch userinfo
  // (i.e. WS open but cache empty). Backend sets this only in that
  // narrow case; otherwise false.
  userinfo_nudged: boolean;
  // True when the agent successfully resolved tier from /v1/credits
  // during this scan call. False if the call failed (token expired,
  // network error, etc.) or if tier was already cached.
  tier_fetched: boolean;
}

export function scanExtension() {
  return api<AuthScanResult>("/api/auth/scan", { method: "POST" });
}

export function createRequest(body: {
  type: string;
  node_id?: number;
  params: Record<string, unknown>;
}) {
  return api<RequestDTO>("/api/requests", {
    method: "POST",
    body: JSON.stringify(body),
  }).then((r) => {
    // components/BackgroundTasks listens (RUNNING_EVENT) to show the "đang chạy" badge at once.
    window.dispatchEvent(new Event("flowboard:running"));
    return r;
  });
}

export function getRequest(id: number) {
  return api<RequestDTO>(`/api/requests/${id}`);
}

/**
 * One row of `GET /api/boards/{id}/requests`. Deliberately thinner than
 * `RequestDTO` — no `result` / `error`, because the caller is about to poll
 * each row anyway and shipping every finished result would make a board
 * load carry its whole generation history.
 *
 * `params` IS included: a page that reloaded mid-generation has to rebuild
 * the poll's options (prompt, aspect ratio) from it, since the
 * `dispatchGeneration` call that originally held them died with the old page.
 */
export interface BoardRequestItem {
  id: number;
  type: string;
  status: RequestDTO["status"];
  node_id: number | null;
  node_short_id: string | null;
  created_at: string;
  params: Record<string, unknown>;
}

/** The two families of in-flight request a reloading board can pick up.
 * They need different handling, so the caller names the ones it can
 * actually act on rather than filtering after the fact:
 * - `worker`: media-producing generations, driven by `attachPoll`.
 * - `sidecar`: the synchronous LLM activities (vision / auto-prompt),
 *   whose result is text and which `attachSidecarPoll` handles.
 * Backend rejects anything else — see `REQUEST_KINDS` in routes/boards.py. */
export type BoardRequestKind = "worker" | "sidecar";

/** Requests attached to this board's nodes. `active` narrows to the ones
 * still in flight (queued / running) — what a reloading board wants —
 * and `kinds` says which of those the caller can handle. Omitting
 * `kinds` gets `worker` only, which is the safe default: handing a
 * sidecar row to the generation poll is what wiped nodes' images. */
export function listBoardRequests(
  boardId: number,
  opts?: { active?: boolean; kinds?: BoardRequestKind[] },
) {
  const params = new URLSearchParams();
  if (opts?.active) params.set("active", "true");
  if (opts?.kinds && opts.kinds.length > 0) {
    params.set("kinds", opts.kinds.join(","));
  }
  const qs = params.toString();
  return api<{ items: BoardRequestItem[] }>(
    `/api/boards/${boardId}/requests${qs ? `?${qs}` : ""}`,
  );
}

// ── Plans + Pipeline runs ────────────────────────────────────────────────────

export interface PipelineRunDTO {
  id: number;
  plan_id: number;
  status: "pending" | "running" | "done" | "failed";
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export function getPlan(planId: number) {
  return api<PlanDTO>(`/api/plans/${planId}`);
}

export function runPlan(planId: number) {
  return api<PipelineRunDTO>(`/api/plans/${planId}/run`, { method: "POST" });
}

export function getPipelineRun(runId: number) {
  return api<PipelineRunDTO>(`/api/pipeline-runs/${runId}`);
}

// ── Media ────────────────────────────────────────────────────────────────────

export interface MediaStatus {
  available: boolean;
  has_url: boolean;
  mime?: string;
  reason?: string;
}

export function getMediaStatus(mediaId: string): Promise<MediaStatus> {
  const clean = mediaId.replace(/^media\//, "");
  return api<MediaStatus>(`/api/media/${encodeURIComponent(clean)}/status`);
}

export function mediaUrl(mediaId: string): string {
  const clean = mediaId.replace(/^media\//, "");
  return `/media/${encodeURIComponent(clean)}`;
}

// ── Upload ───────────────────────────────────────────────────────────────────

export interface UploadResponse {
  media_id: string;
  mime: string;
  size: number;
  // Detected by the agent from the image bytes; one of
  // IMAGE_ASPECT_RATIO_{SQUARE,PORTRAIT,LANDSCAPE}. Optional because legacy
  // responses (or formats we couldn't sniff) skip the field.
  aspect_ratio?: string;
  width?: number;
  height?: number;
}

export async function uploadImage(
  file: File,
  projectId: string,
  nodeId?: number,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("project_id", projectId);
  if (nodeId !== undefined) form.append("node_id", String(nodeId));
  form.append("file", file);

  // Don't set Content-Type — the browser sets it with the correct boundary.
  const res = await fetch("/api/upload", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<UploadResponse>;
}

export interface VisionDescribeResponse {
  media_id: string;
  description: string;
}

export interface AutoPromptResponse {
  node_id: number;
  prompt: string;
}

export interface AutoPromptBatchResponse {
  node_id: number;
  prompts: string[];
}

export async function autoPromptBatch(
  nodeId: number,
  count: number,
  opts?: { camera?: string },
): Promise<AutoPromptBatchResponse> {
  const res = await fetch("/api/prompt/auto-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_id: nodeId, count, camera: opts?.camera }),
  });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<AutoPromptBatchResponse>;
}

export async function autoPrompt(
  nodeId: number,
  opts?: { camera?: string },
): Promise<AutoPromptResponse> {
  const res = await fetch("/api/prompt/auto", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_id: nodeId, camera: opts?.camera }),
  });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<AutoPromptResponse>;
}

/** `nodeId` is optional on the wire but should always be passed from the
 * board: it is what lets the backend write `aiBrief` onto the node itself
 * (agent/flowboard/services/vision.py), so the brief survives a reload
 * that kills this promise, and it is what puts the activity row on a
 * board so `listBoardRequests` can find it again. */
export async function describeMedia(
  mediaId: string,
  nodeId?: number,
): Promise<VisionDescribeResponse> {
  const res = await fetch("/api/vision/describe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_id: mediaId, node_id: nodeId }),
  });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<VisionDescribeResponse>;
}

export async function uploadImageFromUrl(
  url: string,
  projectId: string,
  nodeId?: number,
): Promise<UploadResponse> {
  const res = await fetch("/api/upload-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, project_id: projectId, node_id: nodeId }),
  });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<UploadResponse>;
}


// ── LLM provider Settings ─────────────────────────────────────────────────
// Per-feature model: each of the 3 features (auto_prompt / vision /
// planner) independently pins a provider + model + effort. The old
// single-provider invariant ("all 3 features must point at the same
// name") is gone — `configured` now only means every feature has a
// provider pinned; model/effort stay optional.

export type LLMProviderName = "claude" | "gemini" | "openai" | "muse";
// chat_agent is optional: null provider = the dock uses the planner's pin.
export type LLMFeature = "auto_prompt" | "vision" | "planner" | "chat_agent";
export type LLMProviderMode = "cli" | "api" | "assistant" | "none";
export type LLMLastError =
  | "not_installed"
  | "not_authenticated"
  | "no_key"
  | "unreachable"
  | "unknown";

/** One entry of a provider's model catalog. `id` is what travels back
 * in the config / test payloads; `label` is display-only. */
export interface LLMModelInfo {
  id: string;
  label: string;
}

export interface LLMProviderInfo {
  name: LLMProviderName;
  supportsVision: boolean;
  available: boolean;
  configured: boolean;
  requiresKey: boolean;
  mode: LLMProviderMode;
  // Effort vocabularies differ per provider (claude: low…max, agy:
  // low/medium/high, codex: whatever it reports), so the UI must render
  // the options from `efforts` and never hardcode a list.
  supportsEffort: boolean;
  efforts: string[];
  // Legitimately [] when the catalog couldn't be fetched (offline, CLI
  // mid-upgrade, auth expired). The UI falls back to a free-text model
  // field in that case so a stale catalog can't block the user.
  models: LLMModelInfo[];
  defaultModel: string | null;
  lastError?: LLMLastError;
  lastTest?: { ok: boolean; latencyMs?: number; error?: string };
}

/** One feature's pin. Every field is independently nullable:
 * `provider` null = feature not set up yet; `model` / `effort` null =
 * "whatever the provider defaults to". */
export interface LLMFeatureConfig {
  provider: LLMProviderName | null;
  model: string | null;
  effort: string | null;
}

export interface LLMConfig {
  auto_prompt: LLMFeatureConfig;
  vision: LLMFeatureConfig;
  planner: LLMFeatureConfig;
  chat_agent: LLMFeatureConfig;
  // True once every required feature (not chat_agent) has a provider. Drives the forced-setup
  // gate. A feature with a provider but no model still counts as
  // configured — the backend falls back to that provider's default.
  configured: boolean;
}

/** PUT body — feature keys and the fields inside them are all
 * optional, so a caller can patch one feature without re-sending the
 * other two. */
export type LLMConfigUpdate = Partial<
  Record<LLMFeature, Partial<LLMFeatureConfig>>
>;

export async function getLlmProviders(): Promise<LLMProviderInfo[]> {
  // Backend returns snake-case keys mapped from Python — but the route
  // already emits camelCase for the public surface. Re-typed here so
  // the spread/destructure pattern in the UI components stays clean.
  const res = await fetch("/api/llm/providers");
  if (!res.ok) throw new Error(`getLlmProviders: ${res.status}`);
  return res.json() as Promise<LLMProviderInfo[]>;
}

export interface LlmModelCatalog {
  models: LLMModelInfo[];
  /** True when the backend answered from its catalog cache rather than
   * re-asking the CLI — surfaced so the refresh button can tell the
   * user whether anything was actually re-fetched. */
  cached: boolean;
}

export async function getLlmProviderModels(
  name: LLMProviderName,
  force = false,
): Promise<LlmModelCatalog> {
  // `force=true` bypasses the backend's catalog cache. Wired to the
  // per-row refresh button for the case where the user installs a new
  // model / upgrades the CLI while the dialog is open.
  const qs = force ? "?force=true" : "";
  const res = await fetch(`/api/llm/providers/${name}/models${qs}`);
  if (!res.ok) throw new Error(`getLlmProviderModels: ${res.status}`);
  return res.json() as Promise<LlmModelCatalog>;
}

export async function getLlmConfig(): Promise<LLMConfig> {
  const res = await fetch("/api/llm/config");
  if (!res.ok) throw new Error(`getLlmConfig: ${res.status}`);
  return res.json() as Promise<LLMConfig>;
}

export async function setLlmConfig(
  partial: LLMConfigUpdate,
): Promise<{ ok: boolean }> {
  const res = await fetch("/api/llm/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(partial),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function setLlmApiKey(
  name: LLMProviderName,
  apiKey: string | null,
): Promise<{ ok: boolean }> {
  // null clears the key. Backend chmods secrets.json to 0o600 after
  // every write; the key is never echoed back via getLlmProviders.
  const res = await fetch(`/api/llm/providers/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export interface LlmTestResult {
  ok: boolean;
  latencyMs?: number;
  error?: string;
}

export async function testLlmProvider(
  name: LLMProviderName,
  opts: { model?: string | null; effort?: string | null } = {},
): Promise<LlmTestResult> {
  // Cost-bounded by the backend: 1-token ping, 15s deadline. Returns
  // ok:false (NOT a non-200 HTTP status) on any failure mode so the
  // UI can render the error inline without try/catch boilerplate.
  //
  // model/effort are passed through so a per-feature row tests the
  // exact combination it is about to save — a provider that answers on
  // its default model can still fail on an exotic one.
  const body: { model?: string; effort?: string } = {};
  if (opts.model) body.model = opts.model;
  if (opts.effort) body.effort = opts.effort;
  const res = await fetch(`/api/llm/providers/${name}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    return { ok: false, error: `HTTP ${res.status}` };
  }
  return res.json();
}


// ── Activity feed ─────────────────────────────────────────────────────────
// Read-only surface over the Request table. Captures every backend op:
// gen_image / gen_video / edit_image (worker), auto_prompt /
// auto_prompt_batch / vision / planner (LLM layer via record_activity).

export type ActivityType =
  | "auto_prompt" | "auto_prompt_batch"
  | "vision" | "planner"
  | "gen_image" | "gen_video" | "edit_image"
  | "upload" | "upload_url";
export type ActivityStatus = "queued" | "running" | "done" | "failed";

export interface ActivityListItem {
  id: number;
  type: ActivityType | string; // string fallback for forward-compat
  status: ActivityStatus | string;
  node_id: number | null;
  node_short_id: string | null;
  created_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface ActivityDetail extends ActivityListItem {
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string | null;
}

export async function getActivityList(opts?: {
  limit?: number;
  beforeId?: number;
  type?: string[];
}): Promise<{ items: ActivityListItem[]; next_before_id: number | null }> {
  const search = new URLSearchParams();
  if (opts?.limit) search.set("limit", String(opts.limit));
  if (opts?.beforeId) search.set("before_id", String(opts.beforeId));
  if (opts?.type && opts.type.length > 0) search.set("type", opts.type.join(","));
  const q = search.toString();
  const res = await fetch(`/api/activity${q ? `?${q}` : ""}`);
  if (!res.ok) throw new Error(`getActivityList: ${res.status}`);
  return res.json();
}

export async function getActivityDetail(id: number): Promise<ActivityDetail> {
  const res = await fetch(`/api/activity/${id}`);
  if (!res.ok) throw new Error(`getActivityDetail: ${res.status}`);
  return res.json();
}

// Cancel a queued or running request. The activity row id IS the
// underlying Request.id, so the same numeric handle works against
// /api/requests. Backend returns 409 when the row has already settled
// (done/failed/timeout/canceled).
export async function cancelActivity(id: number): Promise<void> {
  const res = await fetch(`/api/requests/${id}/cancel`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`cancelActivity: ${res.status} ${detail}`);
  }
}


// ── References ───────────────────────────────────────────────────────────
// User-curated cross-board library of saved media. Backend mirror:
// agent/flowboard/routes/references.py + db.models.Reference.
// JSON wire format is snake_case (mirrors SQLModel column names);
// camelCase is reserved for the TS surface, so each helper maps the
// rows on the way back.

export interface ReferenceItem {
  id: number;
  mediaId: string;
  // Best-effort signed CDN URL captured at save time. May expire — the
  // canonical bytes live in storage/media/{mediaId}.{ext}; this field
  // exists purely as a re-ingest hint when the file goes missing.
  url: string | null;
  label: string;
  kind: "image" | "character" | "visual_asset" | "storyboard_shot";
  // Snapshot of the source node's aiBrief at save time; lets cross-board
  // spawn skip the re-vision call entirely.
  aiBrief: string | null;
  aspectRatio: string | null;
  tags: string[];
  pinned: boolean;
  position: number;
  sourceBoardId: number | null;
  sourceNodeShortId: string | null;
  createdAt: string;
}

// Wire-shape POST body — snake_case to match the FastAPI schema 1:1.
export interface ReferenceCreateInput {
  media_id: string;
  kind: ReferenceItem["kind"];
  label?: string;
  ai_brief?: string | null;
  aspect_ratio?: string | null;
  url?: string | null;
  source_board_id?: number | null;
  source_node_short_id?: string | null;
  tags?: string[];
}

// Wire-shape PATCH body. Same snake_case convention.
export interface ReferencePatchInput {
  label?: string;
  pinned?: boolean;
  position?: number;
  tags?: string[];
}

interface ReferenceRowWire {
  id: number;
  media_id: string;
  url: string | null;
  label: string;
  kind: string;
  ai_brief: string | null;
  aspect_ratio: string | null;
  tags: string[] | null;
  pinned: boolean;
  position: number;
  source_board_id: number | null;
  source_node_short_id: string | null;
  created_at: string;
}

function mapReferenceRow(row: ReferenceRowWire): ReferenceItem {
  // Coerce the kind string into the typed union — the backend already
  // validates against _ALLOWED_KINDS so any unknown value here would
  // mean a backend bug. Fall back to "image" defensively rather than
  // throwing, so a single bad row doesn't break the whole list render.
  const allowed: ReferenceItem["kind"][] = [
    "image",
    "character",
    "visual_asset",
    "storyboard_shot",
  ];
  const kind: ReferenceItem["kind"] = (allowed as string[]).includes(row.kind)
    ? (row.kind as ReferenceItem["kind"])
    : "image";
  return {
    id: row.id,
    mediaId: row.media_id,
    url: row.url,
    label: row.label,
    kind,
    aiBrief: row.ai_brief,
    aspectRatio: row.aspect_ratio,
    tags: Array.isArray(row.tags) ? row.tags : [],
    pinned: row.pinned,
    position: row.position,
    sourceBoardId: row.source_board_id,
    sourceNodeShortId: row.source_node_short_id,
    createdAt: row.created_at,
  };
}

export async function listReferences(params?: {
  q?: string;
  pinned_first?: boolean;
  limit?: number;
}): Promise<ReferenceItem[]> {
  const search = new URLSearchParams();
  if (params?.q) search.set("q", params.q);
  if (params?.pinned_first !== undefined) {
    search.set("pinned_first", String(params.pinned_first));
  }
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  const qs = search.toString();
  const rows = await api<ReferenceRowWire[]>(
    `/api/references${qs ? `?${qs}` : ""}`,
  );
  return rows.map(mapReferenceRow);
}

export async function createReference(
  input: ReferenceCreateInput,
): Promise<ReferenceItem> {
  const row = await api<ReferenceRowWire>("/api/references", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return mapReferenceRow(row);
}

export async function patchReference(
  id: number,
  patch: ReferencePatchInput,
): Promise<ReferenceItem> {
  const row = await api<ReferenceRowWire>(`/api/references/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  return mapReferenceRow(row);
}

export async function deleteReference(id: number): Promise<void> {
  // Backend returns 204 No Content; api<T>() would choke on the empty
  // body, so we use fetch() directly and skip the JSON parse.
  const res = await fetch(`/api/references/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`deleteReference: ${res.status} ${res.statusText}`);
  }
}

// ── Flow project sync (local → Flow, one direction) ───────────────────────

export interface BoardFlowStatus {
  board_id: number;
  board_name: string;
  flow_project_id: string | null;
  // null = could not be checked. Flow exposes no project-listing RPC since
  // the migration, so this is null in practice; treating null as `false`
  // would flag every board as missing from Flow.
  exists_on_flow: boolean | null;
}

export interface FlowListingStatus {
  available: boolean;
  reason: string | null;
  // The single Flow project every board generates into, when one is pinned.
  pinned_project_id: string | null;
}

export interface SyncStatusResponse {
  board_status: BoardFlowStatus[];
  flow_listing: FlowListingStatus;
}

export interface SyncUpAction {
  board_id: number;
  board_name: string;
  old_flow_project_id: string | null;
  new_flow_project_id: string | null;
  status: "created" | "rebound" | "failed";
  error: string | null;
}

export interface SyncUpResponse {
  synced: SyncUpAction[];
  failed: SyncUpAction[];
  total_boards: number;
}

export function getFlowSyncStatus(): Promise<SyncStatusResponse> {
  return api<SyncStatusResponse>("/api/flow/projects");
}

export async function syncBoardsUpToFlow(): Promise<SyncUpResponse> {
  const res = await fetch("/api/flow/projects/sync-up", { method: "POST" });
  if (!res.ok) {
    // The refusal body is {message, reason, fix, pinned_project_id}. `api()`
    // drops it entirely and extractErrorMessage keeps only `message` — but
    // `fix` is the half that says what to do about it, so join the two.
    const detail = await res
      .json()
      .then((b) => (b as { detail?: unknown } | null)?.detail)
      .catch(() => null);
    const d = (detail ?? {}) as { message?: unknown; fix?: unknown };
    const parts = [d.message, d.fix].filter(
      (p): p is string => typeof p === "string" && p.length > 0,
    );
    throw new Error(
      parts.length > 0 ? parts.join(" ") : `${res.status} ${res.statusText}`,
    );
  }
  return res.json() as Promise<SyncUpResponse>;
}

// ── Pinned Flow project ───────────────────────────────────────────────────
// The single Flow project every board generates into. Flow dropped project
// creation and listing in the September 2026 migration, so this uuid is the
// only thing standing between a fresh install and "no project" on every
// dispatch. Server state — deliberately NOT mirrored into the persisted
// settings store.

/** Where the effective id comes from. `"override"` = saved from Settings
 * (wins), `"env"` = FLOWBOARD_FLOW_PROJECT_ID, `"none"` = nothing anywhere,
 * which is the state where generation cannot work at all. */
export type PinnedProjectSource = "override" | "env" | "none";

export interface PinnedFlowProject {
  /** The effective id. null when `source` is `"none"`. */
  flow_project_id: string | null;
  source: PinnedProjectSource;
  /** What .env pins, shown so the user can see what clearing falls back to. */
  env_project_id: string | null;
}

export interface PinnedFlowProjectUpdate extends PinnedFlowProject {
  /** Existing boards re-pointed at the new project by this write. */
  rebound_boards: number;
}

export function getPinnedFlowProject(): Promise<PinnedFlowProject> {
  return api<PinnedFlowProject>("/api/flow/projects/pinned");
}

/** `null` clears the override and falls back to .env. */
export async function setPinnedFlowProject(
  flowProjectId: string | null,
): Promise<PinnedFlowProjectUpdate> {
  const res = await fetch("/api/flow/projects/pinned", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flow_project_id: flowProjectId }),
  });
  if (!res.ok) {
    // The 400 `detail` already names exactly what is wrong with the uuid the
    // user typed, so it goes through verbatim — humanizeBackendError() would
    // only risk swapping an actionable sentence for a generic one.
    const body = await res.json().catch(() => null);
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new Error(
      typeof detail === "string" && detail
        ? detail
        : `${res.status} ${res.statusText}`,
    );
  }
  return res.json() as Promise<PinnedFlowProjectUpdate>;
}

// ── Board templates ──────────────────────────────────────────────────────────
// A ready-made flow (nodes + prompts + edges) per ad type; see
// agent/flowboard/templates/*.json and services/templates.py.

export interface TemplateInput {
  key: string;
  label: string;
  placeholder?: string;
  default?: string;
  /** "select" renders a dropdown of [value, label] pairs; anything else a text field. */
  type?: "text" | "select";
  options?: [string, string][];
}

export interface BoardTemplate {
  id: string;
  title: string;
  blurb: string;
  scenes: number;
  /** Product category this template is made for (product library). */
  category?: ProductCategory | "any";
  /** The clip must show a person (clothes are judged on a body): no hands-only option. */
  person_required?: boolean;
  inputs: TemplateInput[];
}

// ── Product library ──────────────────────────────────────────────────────────

export type ProductGender = "" | "male" | "female" | "unisex";

export const PRODUCT_GENDERS: [ProductGender, string][] = [
  ["", "Không rõ / không quan trọng"],
  ["male", "Nam"],
  ["female", "Nữ"],
  ["unisex", "Unisex (cả nam và nữ)"],
];

/** Model genders a product allows: a men's product only men, a women's only women. */
export function allowedModelGenders(g: ProductGender | undefined | null): ("female" | "male")[] {
  return g === "male" ? ["male"] : g === "female" ? ["female"] : ["female", "male"];
}

export type ProductCategory = "fashion" | "cosmetics" | "food" | "grocery" | "home" | "other";

export const PRODUCT_CATEGORIES: [ProductCategory, string][] = [
  ["fashion", "Thời trang"],
  ["cosmetics", "Mỹ phẩm"],
  ["food", "Đồ ăn / uống"],
  ["grocery", "Tạp hoá & phụ kiện"],
  ["home", "Gia dụng"],
  ["other", "Khác"],
];

export interface Product {
  id: number;
  name: string;
  /** English phrase that goes into prompts as {{product}}. */
  description: string;
  category: ProductCategory;
  price: string;
  /** Vietnamese, one selling point per line. */
  selling_points: string;
  /** Who it is for: male / female / unisex / "" (unknown). The clip's model
   * must match a male / female product. */
  gender: ProductGender;
  link: string;
  /** tracked affiliate short link (s.shopee.vn/…, vt.tiktok.com/…) → first comment of posts */
  aff_link: string;
  /** the shop this affiliate product belongs to */
  shop: string;
  notes: string;
  /** Flow media ids, first = main photo. */
  media_ids: string[];
  aspect_ratio: string | null;
  /** Template a board for this product starts from by default. */
  template_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export type ProductDraft = Partial<Omit<Product, "id" | "template_id" | "created_at" | "updated_at">>;

export async function listProducts(): Promise<Product[]> {
  const res = await fetch("/api/products");
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** Delete several products in one call; returns how many existed. */
export async function bulkDeleteProducts(ids: number[]): Promise<number> {
  const res = await fetch("/api/products/bulk-delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return (await res.json()).deleted;
}

export interface ProductFromLink {
  draft: Pick<Product, "name" | "description" | "category" | "price" | "selling_points" | "link">;
  image_url: string | null;
}

/** A product-library draft read from a product page (TikTok Shop, Shopee …). */
export async function productFromLink(url: string): Promise<ProductFromLink> {
  const res = await fetch("/api/products/from-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** A TikTok / Shopee tab open in Chrome, as "Nhập từ tab đang mở" lists it. */
export interface ShopTab {
  id: number;
  url: string;
  title: string;
  active: boolean;
  platform: "tiktok" | "shopee";
  /** product = one product page; list = a TikTok page of product cards; other = neither. */
  kind: "product" | "list" | "other";
  importable: boolean;
  /** Ticked by default in the picker. */
  suggested: boolean;
}

export interface TabImportResult {
  tab_id: number;
  platform: ShopTab["platform"];
  kind: ShopTab["kind"];
  title: string;
  url: string;
  ok: boolean;
  found: number;
  created: number;
  skipped: number;
  names: string[];
  error: string | null;
}

export interface TabsImport {
  results: TabImportResult[];
  tabs: number;
  found: number;
  created: number;
  skipped: number;
  failed: number;
  photos_pending: number;
}

/** The TikTok / Shopee tabs open in Chrome (via the extension). */
export async function listOpenShopTabs(): Promise<ShopTab[]> {
  const res = await fetch("/api/products/open-tabs");
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return (await res.json()).tabs;
}

/** Import the chosen open tabs: product pages and TikTok showcase / shop pages alike. */
export async function importOpenTabs(tabIds: number[]): Promise<TabsImport> {
  const res = await fetch("/api/products/import-tabs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tab_ids: tabIds }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function getProduct(id: number): Promise<Product> {
  const res = await fetch(`/api/products/${id}`);
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function createProduct(draft: ProductDraft): Promise<Product> {
  const res = await fetch("/api/products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function updateProduct(id: number, draft: ProductDraft): Promise<Product> {
  const res = await fetch(`/api/products/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function deleteProduct(id: number): Promise<void> {
  const res = await fetch(`/api/products/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
}

export async function getTemplates(): Promise<BoardTemplate[]> {
  const res = await fetch("/api/templates");
  if (!res.ok) throw new Error(`getTemplates: ${res.status}`);
  return res.json() as Promise<BoardTemplate[]>;
}

export async function createBoardFromTemplate(
  templateId: string,
  name: string,
  inputs: Record<string, string>,
  productId?: number | null,
  /** Clip `index` of `of` for the same product: the agent writes each a different angle. */
  variant?: { index: number; of: number },
  channelId?: number | null,
  /** "🔇 Không lời": scenes written for no voice-over, no voice lines. */
  voiceless = false,
): Promise<Board> {
  const res = await fetch("/api/boards/from-template", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      template_id: templateId, name, inputs, product_id: productId ?? null, channel_id: channelId ?? null,
      ...(variant ? { variant: variant.index, variant_of: variant.of } : {}),
      ...(voiceless ? { voiceless: true } : {}),
    }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  const body = (await res.json()) as Board & { nodes: Record<string, string> };
  return { id: body.id, name: body.name, created_at: body.created_at, data: body.data };
}

/** Bước 2 "Viết lại kịch bản theo sản phẩm": rewrite an existing clip's
 * scenes from its saved product. Returns the data patch applied per node. */
export async function tailorBoardApi(
  boardId: number,
  scenes: { image_id: number; video_id: number | null }[],
  instructions?: string,
): Promise<{ updated: number; nodes: Record<string, Record<string, string>> }> {
  const res = await fetch(`/api/boards/${boardId}/tailor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenes, instructions: instructions?.trim() || null }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** The user's rough prompt → a polished English one (same rules as auto-prompt). */
export async function refinePromptApi(
  nodeId: number,
  draft: string,
  opts?: { camera?: string },
): Promise<{ node_id: number; prompt: string }> {
  const res = await fetch("/api/prompt/refine", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_id: nodeId, draft, camera: opts?.camera ?? null }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** "Tạo lại" with a request: the node's prompt rewritten to do what the user asked. */
export async function revisePromptApi(
  nodeId: number,
  request: string,
  current?: string,
): Promise<{ node_id: number; prompt: string }> {
  const res = await fetch("/api/prompt/revise", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_id: nodeId, request, current: current ?? null }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export interface SplitStoryboardResult {
  storyboard: string;
  panels: number;
  rows: number;
  cols: number;
  /** spec key (`s1`, `v1`, …) → short id of the node created for it */
  nodes: Record<string, string>;
}

/** Cut a rendered Storyboard composite into one image + video node per tile. */
export async function splitStoryboard(nodeId: number): Promise<SplitStoryboardResult> {
  const res = await fetch(`/api/nodes/${nodeId}/storyboard/split`, { method: "POST" });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

// ── Voice-over ───────────────────────────────────────────────────────────────

/** Voice-over voices (`services/tts.py::VOICES`): Edge (free, instant) and
 * Gemini prebuilt voices (many, style-steerable, served by the key pool). */
export type VoiceGroupId = "clone" | "edge" | "vieneu" | "gemini" | "fpt";
export interface VoiceGroup {
  id: VoiceGroupId;
  label: string;
  voices: [string, string][];
  /** false = this family cannot speak on this machine right now (no key / no VieDub venv) */
  available?: boolean;
  reason?: string;
}
/** The static fallback (Edge + Gemini). `fetchVoiceGroups()` replaces it with the agent's list, which adds VieNeu / FPT. */
export const VOICE_GROUPS: VoiceGroup[] = [
  {
    id: "edge",
    label: "Microsoft Edge — miễn phí, nhanh",
    voices: [
      ["vi-VN-HoaiMyNeural", "Hoài My (nữ)"],
      ["vi-VN-NamMinhNeural", "Nam Minh (nam)"],
    ],
  },
  {
    id: "gemini",
    label: "Gemini — nhiều giọng, chỉnh được phong cách (cần Gemini API key)",
    voices: [
      ["gemini:Kore", "Kore (nữ, chắc giọng)"],
      ["gemini:Aoede", "Aoede (nữ, nhẹ nhàng)"],
      ["gemini:Leda", "Leda (nữ, trẻ trung)"],
      ["gemini:Sulafat", "Sulafat (nữ, ấm áp)"],
      ["gemini:Gacrux", "Gacrux (nữ, chững chạc)"],
      ["gemini:Despina", "Despina (nữ, mượt)"],
      ["gemini:Laomedeia", "Laomedeia (nữ, sôi nổi)"],
      ["gemini:Puck", "Puck (nam, vui tươi)"],
      ["gemini:Charon", "Charon (nam, kể chuyện)"],
      ["gemini:Fenrir", "Fenrir (nam, hào hứng)"],
      ["gemini:Orus", "Orus (nam, chắc giọng)"],
      ["gemini:Achird", "Achird (nam, thân thiện)"],
      ["gemini:Algenib", "Algenib (nam, khàn)"],
      ["gemini:Sadaltager", "Sadaltager (nam, hiểu biết)"],
    ],
  },
];
export const GROUP_SHORT: Record<VoiceGroupId, string> = { clone: "Nhân bản", edge: "Edge", vieneu: "VieNeu", gemini: "Gemini", fpt: "FPT.AI" };
export const VOICES: Record<string, string> = Object.fromEntries(
  VOICE_GROUPS.flatMap((g) => g.voices.map(([id, label]) => [id, `${label} · ${GROUP_SHORT[g.id]}`])),
);
export const DEFAULT_VOICE = "vi-VN-HoaiMyNeural";
export const isGeminiVoice = (id: string) => id.startsWith("gemini:");
/** "edge" | "vieneu" | "gemini" | "fpt" of a voice id */
export const voiceKind = (id: string): VoiceGroupId =>
  id.startsWith("gemini:") ? "gemini" : id.startsWith("vieneu:") ? "vieneu" : id.startsWith("fpt:") ? "fpt" : "edge";

let voiceGroupsPromise: Promise<VoiceGroup[]> | null = null;
/** `GET /api/llm/voices`: every voice family the agent offers (Edge, VieNeu on the machine, Gemini, FPT.AI) with
 * availability; the static list when the agent cannot be asked. Fetched once; `VOICES` is filled in with the result. */
export function fetchVoiceGroups(force = false): Promise<VoiceGroup[]> {
  if (!voiceGroupsPromise || force) {
    voiceGroupsPromise = (async () => {
      const res = await fetch("/api/llm/voices");
      if (!res.ok) throw new Error(await extractErrorMessage(res));
      const data = await res.json() as { groups: { id: VoiceGroupId; label: string; available?: boolean; reason?: string; voices: { id: string; label: string }[] }[] };
      const groups: VoiceGroup[] = data.groups.map((g) => ({
        id: g.id, label: g.label, available: g.available ?? true, reason: g.reason, voices: g.voices.map((v) => [v.id, v.label] as [string, string]),
      }));
      for (const g of groups) for (const [id, label] of g.voices) VOICES[id] = `${label} · ${GROUP_SHORT[g.id] ?? g.id}`;
      return groups;
    })().catch((e) => { voiceGroupsPromise = null; throw e; });
  }
  return voiceGroupsPromise;
}

/** A voice was cloned / renamed / deleted ("🧬 Giọng nhân bản"): every open voice picker reloads its list. */
export const VOICES_CHANGED = "dflow:voices";
export function refreshVoiceGroups(): void {
  voiceGroupsPromise = null;
  window.dispatchEvent(new Event(VOICES_CHANGED));
}

export async function getFptKey(): Promise<{ set: boolean; masked: string }> {
  const res = await fetch("/api/llm/fpt-key");
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}
export async function setFptKey(key: string): Promise<{ set: boolean; masked: string }> {
  const res = await fetch("/api/llm/fpt-key", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  voiceGroupsPromise = null;  // FPT availability changed
  return res.json();
}

/** AI writes one Vietnamese voice line per video node (in clip order) and
 * stores it on each node's `data.narration`. */
export async function writeNarrationApi(
  boardId: number,
  nodeIds: number[],
  instructions?: string,
): Promise<{ narrations: Record<string, string> }> {
  const res = await fetch("/api/prompt/narration", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board_id: boardId, node_ids: nodeIds, instructions: instructions ?? null }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** Drop every rendered image / video on the board; nodes and prompts stay. */
export async function clearBoardMedia(
  boardId: number,
  includeRefs = false,
): Promise<{ board_id: number; cleared: number; include_refs: boolean }> {
  const res = await fetch(`/api/boards/${boardId}/clear-media`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_refs: includeRefs }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

// ── Gemini API key pool ──────────────────────────────────────────────────────

export interface GeminiKeyState {
  masked: string;
  /** the key as a whole is refused (bad key / API off) */
  parked: boolean;
  parked_for_s: number;
  /** model → seconds until that model's quota comes back for this key (free-tier quotas are per model) */
  models_parked?: Record<string, number>;
  /** model → the quota Google named ("10" a day…) */
  model_limits?: Record<string, string>;
  last_error: string | null;
  calls: number;
}

export interface GeminiKeysResponse {
  keys: GeminiKeyState[];
  count: number;
  default_model: string;
}

export async function getGeminiKeys(): Promise<GeminiKeysResponse> {
  const res = await fetch("/api/llm/gemini-keys");
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** Replace the pool with the keys pasted in `text` (any separators). */
export async function setGeminiKeys(text: string): Promise<GeminiKeysResponse> {
  const res = await fetch("/api/llm/gemini-keys", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function testGeminiKeys(): Promise<GeminiKeysResponse & {
  results: { masked: string; ok: boolean; models?: number; latency_ms?: number; error?: string; detail?: string }[];
}> {
  const res = await fetch("/api/llm/gemini-keys/test", { method: "POST" });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

// ── Clip from a reference ad video ───────────────────────────────────────────

export interface ReferenceUpload {
  media_id: string;
  mime: string;
  size: number;
  duration_s: number | null;
  width: number | null;
  height: number | null;
}

export interface ReferencePlanScene {
  title_vi: string;
  image_prompt_en: string;
  motion_prompt_en: string;
  narration_vi: string;
}

export interface ReferenceAnalysis {
  /** Written for a "🔇 Không lời" clip: the scenes have no narration. */
  voiceless?: boolean;
  category: ProductCategory;
  category_vi: string;
  product_seen: string;
  hook: string;
  style?: string;
  tone?: string;
  has_person: boolean;
  voice_transcript_vi?: string;
  scenes: { start_s: number; end_s: number; shot: string; action: string; camera?: string; on_screen_text?: string }[];
  plan: ReferencePlanScene[];
  script_vi: string;
  character: { gender: string; country: string; vibe: string; extras_en?: string } | null;
  match: { relevant: boolean; score: number; reason_vi: string };
  blocked: boolean;
  block_reason?: string;
}

export async function uploadReferenceVideo(file: File): Promise<ReferenceUpload> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/reference-video/upload", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function analyzeReferenceVideo(
  mediaId: string,
  productId: number | null,
  scenes?: number,
  voiceless = false,
): Promise<{ media_id: string; product: Product | null; analysis: ReferenceAnalysis; blocked: boolean; block_reason: string | null }> {
  const res = await fetch("/api/reference-video/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_id: mediaId, product_id: productId, scenes: scenes ?? null, voiceless }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** Plan from a product page (Shopee, Lazada, TikTok Shop …) instead of a video. */
export async function analyzeProductLink(
  url: string,
  productId: number | null,
  scenes?: number,
  voiceless = false,
): Promise<{ product: Product | null; analysis: ReferenceAnalysis; blocked: boolean; block_reason: string | null }> {
  const res = await fetch("/api/reference-video/analyze-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, product_id: productId, scenes: scenes ?? null, voiceless }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function buildFromReferenceVideo(input: {
  /** null: the plan came from a product link, there is no video. */
  mediaId: string | null;
  sourceUrl?: string;
  productId: number | null;
  analysis: ReferenceAnalysis;
  name?: string;
  force?: boolean;
  /** Overrides the analysis' suggested character; omit to keep it. */
  character?: CharacterPick | null;
  channelId?: number | null;
  /** "🔇 Không lời": the clip gets no voice lines. */
  voiceless?: boolean;
}): Promise<Board & { nodes: Record<string, string> }> {
  const res = await fetch("/api/reference-video/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      media_id: input.mediaId, source_url: input.sourceUrl ?? null, product_id: input.productId, analysis: input.analysis,
      name: input.name ?? null, force: input.force ?? false, character: input.character ?? null,
      channel_id: input.channelId ?? null, voiceless: input.voiceless ?? false,
    }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** Download a TikTok / YouTube / … link on the agent (yt-dlp) and register
 * it like an uploaded reference video. */
export async function fetchReferenceVideo(url: string): Promise<ReferenceUpload & { title: string; url: string }> {
  const res = await fetch("/api/reference-video/fetch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

// ── Drama clips (story → narrated slideshow) ─────────────────────────────────

export interface DramaBeat {
  title_vi: string;
  caption_vi: string;
  narration_vi: string;
  image_prompt_en: string;
}

export interface DramaPlan {
  title_vi: string;
  summary_vi: string;
  hook_vi: string;
  tone: string;
  beats: DramaBeat[];
  source_url: string | null;
}

export async function analyzeDrama(input: { url?: string; text?: string; beats?: number }): Promise<{
  source: { title: string; url: string | null; chars: number };
  plan: DramaPlan;
}> {
  const res = await fetch("/api/drama/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: input.url ?? null, text: input.text ?? null, beats: input.beats ?? null }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function buildDrama(plan: DramaPlan, name?: string): Promise<Board & { nodes: Record<string, string>; sequence: { node: string }[] }> {
  const res = await fetch("/api/drama/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan, name: name ?? null }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** One entry of an explicit export order (drama clips): a still or a clip. */
export interface ExportItem {
  media_id: string;
  kind: "image" | "video";
  narration: string;
  caption?: string;
  /** Inserted footage keeps its own sound by default. */
  original_audio?: "duck" | "keep" | "mute";
}

// ── Export extras: voice preview, background music, cover image ─────────────

/** `POST /api/llm/voices/preview`: one fixed sample sentence spoken by
 * `voice` (`style` applies to Gemini voices); play the URL with
 * `new Audio(url)`. The agent caches it per voice + style. */
export async function previewVoice(voice: string, style?: string, text?: string): Promise<{ url: string; voice: string }> {
  const res = await fetch("/api/llm/voices/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice, style: style || null, text: text?.trim() || null }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** A VieNeu voice was picked: the agent loads the model in the background (services/voice_server), so "▶ Nghe thử"
 *  and the dub's voice step read at once. Asked at most once a minute; other voices need nothing. */
let lastWarm = 0;
export function warmVoice(voice: string): void {
  if (!voice.startsWith("vieneu:") || Date.now() - lastWarm < 60_000) return;
  lastWarm = Date.now();
  void fetch("/api/llm/voices/warm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice }),
  }).catch(() => undefined);
}

/** Background-music levels offered in the export step (volume factor). */
export const BGM_VOLUMES: [number, string][] = [[0.08, "Nhỏ"], [0.15, "Vừa"], [0.25, "To"]];
export const BGM_DEFAULT_VOLUME = 0.15;
export const MAX_MUSIC_BYTES = 20 * 1024 * 1024;

export interface MusicUpload {
  media_id: string;
  name: string;
  mime: string;
  size: number;
  duration_s: number | null;
}

/** `POST /api/llm/music`: store an mp3 / m4a / wav track as an audio asset. */
export async function uploadMusic(file: File): Promise<MusicUpload> {
  const form = new FormData();
  form.append("file", file, file.name);
  const res = await fetch("/api/llm/music", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export type CoverStyle = "yellow" | "white" | "red";
export const COVER_STYLES: [CoverStyle, string][] = [["yellow", "Chữ vàng"], ["white", "Chữ trắng"], ["red", "Chữ đỏ"]];

export interface CoverResult {
  media_id: string;
  url: string;
  width: number;
  height: number;
}

/** `POST /api/boards/{id}/cover`: a 1080×1920 PNG cover from a scene image
 * with the title burned in; registered as an image asset. */
export async function createCover(
  boardId: number,
  body: { media_id: string; title: string; subtitle?: string; style?: CoverStyle },
): Promise<CoverResult> {
  const res = await fetch(`/api/boards/${boardId}/cover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_id: body.media_id, title: body.title, subtitle: body.subtitle || null, style: body.style ?? "yellow" }),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

// ── Dialogue: several voices in one narration line ──────────────────────────

/** `[A]` / `[b2]` in a voice line marks who speaks what follows
 * (`services/tts.py::SPEAKER_TAG`). Tags are compared upper-cased. */
export const SPEAKER_TAG = /\[([A-Za-z0-9]{1,8})\]/g;
/** An export node may name this many speakers (`tts.MAX_SPEAKERS`). */
export const MAX_SPEAKERS = 4;

/** `[{ tag, text }]` of a line: `"[A] Ủa? [b] Mát lắm."` →
 * `[{tag: "A", text: "Ủa?"}, {tag: "B", text: "Mát lắm."}]`; text before the
 * first tag has `tag: null`; empty segments are dropped. */
export function parseSpeakers(text: string): { tag: string | null; text: string }[] {
  const out: { tag: string | null; text: string }[] = [];
  let pos = 0;
  let tag: string | null = null;
  for (const m of (text || "").matchAll(SPEAKER_TAG)) {
    const seg = text.slice(pos, m.index).trim();
    if (seg) out.push({ tag, text: seg });
    tag = m[1].toUpperCase();
    pos = (m.index ?? 0) + m[0].length;
  }
  const seg = (text || "").slice(pos).trim();
  if (seg) out.push({ tag, text: seg });
  return out;
}

/** The distinct speaker tags used across `lines`, in order of first use. */
export function speakerTags(lines: string[]): string[] {
  const tags: string[] = [];
  for (const line of lines) {
    for (const seg of parseSpeakers(line)) {
      if (seg.tag && !tags.includes(seg.tag)) tags.push(seg.tag);
    }
  }
  return tags;
}
