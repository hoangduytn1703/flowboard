import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { mediaUrl, patchNode } from "../../api/client";
import { useBoardStore } from "../../store/board";
import type { FlowNode } from "../../store/board";
import { FLOW_DROPPED_VIDEO, useGenerationStore } from "../../store/generation";
import { useQuicktoolStore } from "../../store/quicktool";
import { useSettingsStore } from "../../store/settings";
import { useFlowCredits } from "../../components/credits";
import { creditsPerClip, hasMedia, isBusy, type ClipRoles } from "../roles";
import { toast } from "../../store/toast";
import { knownFlowCheck } from "../flowModelCheck";
import { FLOW_SLOW_AFTER_S, clockOf } from "../muse";
import { MuseBridge, flowWaitS, useFlowWaits, useNow, type MuseFocus } from "./MuseBridge";
import { JoinOptions } from "./JoinOptions";
import { askConfirm } from "../../components/Dialogs";

function statusLabel(n: FlowNode | null, waitS: number | null = null): string {
  if (!n) return "chưa có node";
  if (isBusy(n)) return n.data.autoPromptStatus === "pending" ? "đang viết prompt…" : `đang tạo…${waitS !== null ? ` ${clockOf(waitS)}` : ""}`;
  if (n.data.status === "error") return flowDropped(n.data.error) ? "Flow bỏ lượt này" : `lỗi: ${String(n.data.error ?? "không rõ").slice(0, 80)}`;
  if (hasMedia(n)) return "xong";
  return "chưa tạo";
}

/** Colour of the status pill: done, working, failed, or not started. */
function statusTone(n: FlowNode | null): string {
  if (!n) return "idle";
  if (isBusy(n)) return "busy";
  if (n.data.status === "error") return "error";
  return hasMedia(n) ? "done" : "idle";
}

/** A video that ended as `timeout` — new wording, or the old one still stored on the node. */
function flowDropped(error: unknown): boolean {
  const e = String(error ?? "");
  return e.startsWith(FLOW_DROPPED_VIDEO.slice(0, 24)) || /timeout_waiting_video|Timed out|FLOW_DROPPED_JOB/i.test(e);
}

/** One-tap requests for "Tạo lại theo yêu cầu" (Vietnamese; the agent rewrites the English prompt). */
const QUICK_REQUESTS: Record<"image" | "video", string[]> = {
  image: [
    "Người mẫu cười tươi, tự nhiên hơn",
    "Sản phẩm to và rõ hơn, đúng màu như ảnh gốc",
    "Bối cảnh sáng sủa, gọn gàng hơn",
    "Đổi góc chụp khác",
    "Toàn thân, thấy rõ cả quần áo",
  ],
  video: [
    "Chuyển động chậm, nhẹ nhàng hơn",
    "Người mẫu không nói, không mấp máy môi",
    "Camera đứng yên",
    "Sản phẩm luôn nằm trong khung hình",
    "Động tác tự nhiên, không bị méo tay",
  ],
};

/** The box under a tile after "Tạo lại…": type what to change (or pick a
 * quick request), then regenerate with a revised prompt — or as before. */
function RegenBox({ node, kind, onSubmit, onClose }: {
  node: FlowNode;
  kind: "image" | "video";
  onSubmit(request: string): void;
  onClose(): void;
}) {
  const [text, setText] = useState("");
  const prev = typeof node.data.prevPrompt === "string" ? node.data.prevPrompt : "";
  const last = typeof node.data.lastRequest === "string" ? node.data.lastRequest : "";

  function addQuick(q: string) {
    setText((t) => (t.trim() ? `${t.trim().replace(/[.,;]$/, "")}, ${q.charAt(0).toLowerCase()}${q.slice(1)}` : q));
  }

  function restorePrev() {
    const dbId = parseInt(node.id, 10);
    const patch = { prompt: prev, prevPrompt: "", lastRequest: "" };
    useBoardStore.getState().updateNodeData(node.id, patch);
    if (!isNaN(dbId)) patchNode(dbId, { data: patch }).catch(() => {});
    toast.info("Đã đưa prompt về như trước lần sửa gần nhất (chưa tạo lại).");
  }

  return (
    <div className="qt-regen" onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <label className="qt-regen__label" htmlFor={`regen-${node.id}`}>
        Muốn {kind === "image" ? "ảnh" : "video"} mới khác thế nào?
      </label>
      <textarea
        id={`regen-${node.id}`}
        className="qt-textarea qt-regen__input"
        rows={2}
        autoFocus
        placeholder={kind === "image" ? "VD: áo hồng đậm hơn, người mẫu cười, bỏ cái đèn phía sau…" : "VD: quay chậm lại, người mẫu xoay người khoe áo, không nói…"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim()) onSubmit(text); }}
      />
      <div className="qt-regen__chips">
        {QUICK_REQUESTS[kind].map((q) => (
          <button key={q} type="button" className="qt-regen__chip" onClick={() => addQuick(q)}>+ {q}</button>
        ))}
      </div>
      {last && (
        <div className="qt-regen__last">
          Lần trước đã yêu cầu: “{last}”
          {prev && <> · <button type="button" className="qt-regen__link" onClick={restorePrev}>↺ Về prompt trước đó</button></>}
        </div>
      )}
      <div className="qt-regen__actions">
        <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={!text.trim()} onClick={() => onSubmit(text)}>
          ✨ Tạo lại theo yêu cầu
        </button>
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => onSubmit("")}>Tạo lại y như cũ</button>
        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={onClose}>Huỷ</button>
      </div>
    </div>
  );
}

/** Steps 3 and 4 — the same grid, once for scene images, once for clips. */
export function StepMedia({ roles, kind, productName = "", boardName = "", voiceless = false }: {
  roles: ClipRoles;
  kind: "image" | "video";
  /** For the Muse message ("clip bán hàng <tên sản phẩm>") and the still file names. */
  productName?: string;
  boardName?: string;
  /** "🔇 Không lời": the join options skip the voice and the subtitles. */
  voiceless?: boolean;
}) {
  const generateScene = useQuicktoolStore((s) => s.generateScene);
  const generateVideo = useQuicktoolStore((s) => s.generateVideo);
  const generateAll = useQuicktoolStore((s) => (kind === "image" ? s.generateAllScenes : s.generateAllVideos));
  const uploadVideoToScene = useQuicktoolStore((s) => s.uploadVideoToScene);
  const auto = useQuicktoolStore((s) => s.auto);
  const running = auto !== "idle" && auto !== "done" && auto !== "stopped" && auto !== "failed";
  const videoModel = useSettingsStore((s) => s.videoModel);
  const videoQuality = useSettingsStore((s) => s.videoQuality);
  const { credits: flowCredits } = useFlowCredits();
  const [uploading, setUploading] = useState<number | null>(null);
  // Scene whose "Tạo lại…" box is open.
  const [regenFor, setRegenFor] = useState<number | null>(null);
  const navigate = useNavigate();
  const boardId = useBoardStore((s) => s.boardId);
  const modelCheck = knownFlowCheck(roles.model);
  const fileRef = useRef<HTMLInputElement>(null);
  const pendingScene = useRef<number | null>(null);
  const [museFocus, setMuseFocus] = useState<MuseFocus | null>(null);

  const items = roles.scenes.map((s) => ({ scene: s, node: kind === "image" ? s.image : s.video }));
  // How long each running clip has been waiting on Flow (step 4 only).
  const busyVideoIds = kind === "video" ? items.filter((i) => isBusy(i.node)).map((i) => i.node!.id) : [];
  const waits = useFlowWaits(kind === "video" ? boardId : null, busyVideoIds);
  const now = useNow(busyVideoIds.length > 0);
  function museFor(sceneIndex: number) {
    setMuseFocus((prev) => ({ scene: sceneIndex, nonce: (prev?.nonce ?? 0) + 1 }));
  }
  const done = items.filter((i) => hasMedia(i.node)).length;
  const busy = items.filter((i) => isBusy(i.node)).length;
  const blocked = kind === "video" ? roles.scenes.filter((s) => !hasMedia(s.image)).length : 0;
  // What "make all the missing ones" would actually send.
  const missing = items.filter((i) => i.node && !hasMedia(i.node) && !isBusy(i.node) && (kind === "image" || hasMedia(i.scene.image))).length;

  function pickVideo(sceneIndex: number) {
    pendingScene.current = sceneIndex;
    fileRef.current?.click();
  }

  async function onVideoFile(files: FileList | null) {
    const f = files?.[0];
    // No tile picked (a drop, an automated upload): the first scene still
    // without a clip takes the file.
    const idx = pendingScene.current ?? roles.scenes.find((s) => s.video && !hasMedia(s.video))?.index ?? null;
    pendingScene.current = null;
    if (!f || idx === null) return;
    setUploading(idx);
    try {
      await uploadVideoToScene(idx, f);
    } finally {
      setUploading(null);
    }
  }

  function regenerate(sceneIndex: number, request: string) {
    setRegenFor(null);
    void (kind === "image" ? generateScene(sceneIndex, request) : generateVideo(sceneIndex, request));
  }

  async function startAll() {
    if (kind === "video" && roles.model && modelCheck?.status === "blocked") {
      toast.warning("Flow chặn video có gương mặt người mẫu của clip này — đổi người mẫu ở Bước 1 trước khi tạo video.");
      return;
    }
    if (kind === "video") {
      const cost = missing * creditsPerClip(videoModel, videoQuality);
      const balance = flowCredits === null ? "" : ` Tài khoản còn ${flowCredits.toLocaleString("vi-VN")} credit${cost > flowCredits ? " — KHÔNG ĐỦ" : ""}.`;
      if (!await askConfirm(`Tạo ${missing} video (~${cost} credit Flow, 1–3 phút mỗi clip).${balance} Tiếp tục?`)) return;
    }
    void generateAll();
  }

  return (
    <div className="qt-step">
      <section className="qt-card">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Bước {kind === "image" ? 3 : 4}</div>
            <h3 className="qt-card__title">{kind === "image" ? "Ảnh từng cảnh" : "Video từng cảnh"}</h3>
          </div>
          <button
            type="button"
            className="qt-btn qt-btn--accent"
            disabled={running || missing === 0}
            onClick={startAll}
          >
            {missing === 0 && items.length > 0
              ? (kind === "video" && done < items.length ? "Thiếu ảnh cảnh — làm bước 3 trước" : kind === "image" ? "Đủ ảnh rồi" : "Đủ video rồi")
              : kind === "image" ? `Tạo ${missing} ảnh còn thiếu` : `Tạo ${missing} video còn thiếu`}
          </button>
        </div>
        <div className="qt-stats">
          <div className="qt-stat"><strong>{items.length}</strong><span>cảnh</span></div>
          <div className="qt-stat"><strong>{done}</strong><span>đã xong</span></div>
          <div className="qt-stat"><strong>{busy}</strong><span>đang chạy</span></div>
          {kind === "video" && <div className="qt-stat"><strong>{blocked}</strong><span>thiếu ảnh cảnh</span></div>}
        </div>
        {kind === "video" && (
          <p className="qt-card__hint">
            Mỗi clip 8 giây bằng {videoModel === "omni_flash" ? "Omni Flash (~12 credit)" : "Veo 3.1"}, thường 1–2 phút. Clip chưa ưng thì bấm "Tạo lại…" ở cảnh đó và ghi muốn sửa gì,
            hoặc <strong>⬆ Dùng video của bạn</strong> để thay bằng cảnh quay thật (mp4/mov, tối đa 200 MB, không tốn credit).
            Flow chậm quá hoặc bỏ lượt thì làm cảnh đó bằng <strong>Muse</strong> (khung "🎬 Làm video bằng Muse" bên dưới).
          </p>
        )}
        {kind === "video" && <JoinOptions roles={roles} voiceless={voiceless} />}
        {kind === "image" && (
          <p className="qt-card__hint">Mỗi ảnh mất khoảng 20–60 giây; ảnh chưa ưng thì bấm "Tạo lại…" ở cảnh đó và ghi muốn sửa gì (tiếng Việt cũng được).</p>
        )}
        <div className="qt-grid">
          {items.map(({ scene, node }) => {
            const waitS = kind === "video" ? flowWaitS(node, waits, now) : null;
            const slow = waitS !== null && waitS >= FLOW_SLOW_AFTER_S;
            const source = kind === "video" && node && hasMedia(node) && !isBusy(node)
              ? (node.data.uploadedFrom === "muse" ? "Muse" : node.data.uploaded ? "Video của bạn" : null) : null;
            return (
            <div key={scene.image.id} className={`qt-tile${node && isBusy(node) ? " qt-tile--busy" : ""}`}>
              <div className="qt-tile__head">
                <span className="qt-tile__num">Cảnh {scene.index}{source && <span className="qt-tile__source">{source}</span>}</span>
                <span className={`qt-tile__status qt-tile__status--${statusTone(node)}`} title={statusLabel(node, waitS)}>{statusLabel(node, waitS)}</span>
              </div>
              <div className="qt-tile__media" onClick={() => node && hasMedia(node) && useGenerationStore.getState().openResultViewer(node.id)}>
                {node && hasMedia(node) ? (
                  kind === "image" ? (
                    <img src={mediaUrl(node.data.mediaId as string)} alt="" />
                  ) : (
                    <video src={mediaUrl(node.data.mediaId as string)} controls preload="metadata" playsInline
                           poster={hasMedia(scene.image) ? mediaUrl(scene.image.data.mediaId as string) : undefined} />
                  )
                ) : kind === "video" && hasMedia(scene.image) ? (
                  <img className="qt-tile__poster" src={mediaUrl(scene.image.data.mediaId as string)} alt="" />
                ) : (
                  <div className="qt-tile__empty">{node && isBusy(node) ? "⏳" : "—"}</div>
                )}
              </div>
              <div className="qt-tile__caption" title={String(node?.data.prompt ?? "")}>
                {kind === "video"
                  ? (typeof node?.data.narration === "string" && node.data.narration) || String(node?.data.prompt ?? "").slice(0, 90)
                  : String(scene.image.data.prompt ?? "").slice(0, 90)}
              </div>
              <div className="qt-tile__actions">
                <button
                  type="button"
                  className="qt-btn qt-btn--small"
                  disabled={!node || isBusy(node) || running || (kind === "video" && !hasMedia(scene.image))}
                  onClick={() => {
                    // A first render goes straight out; a redo asks what to change.
                    if (node && hasMedia(node)) setRegenFor(regenFor === scene.index ? null : scene.index);
                    else void (kind === "image" ? generateScene(scene.index) : generateVideo(scene.index));
                  }}
                >
                  {node && hasMedia(node) ? (regenFor === scene.index ? "Đóng" : "Tạo lại…") : "Tạo"}
                </button>
                {node && hasMedia(node) && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost"
                          onClick={() => useGenerationStore.getState().openResultViewer(node.id)}>
                    Xem lớn
                  </button>
                )}
                {kind === "video" && node && (
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost qt-tile__upload"
                          disabled={isBusy(node) || running || uploading !== null}
                          title="Thay cảnh này bằng video bạn tự quay (không tốn credit)"
                          onClick={() => pickVideo(scene.index)}>
                    {uploading === scene.index ? "Đang tải…" : "⬆ Dùng video của bạn"}
                  </button>
                )}
              </div>
              {slow && (
                <div className="qt-slow">
                  <span>⏱ Flow đã chạy {clockOf(waitS ?? 0)} — lâu hơn thường lệ.</span>
                  <button type="button" className="qt-btn qt-btn--small" onClick={() => museFor(scene.index)}>🎬 Làm cảnh này bằng Muse</button>
                </div>
              )}
              {kind === "video" && node && !isBusy(node) && node.data.status === "error"
                && flowDropped(node.data.error) && (
                <div className="qt-dropped">
                  <p>{FLOW_DROPPED_VIDEO}</p>
                  <button type="button" className="qt-btn qt-btn--small" onClick={() => museFor(scene.index)}>🎬 Làm cảnh này bằng Muse</button>
                  {roles.model && modelCheck?.status !== "ok" ? (
                    <>
                      <p>{modelCheck?.status === "blocked"
                        ? "Đã kiểm tra: Flow chặn gương mặt người mẫu của clip này — đổi người mẫu rồi tạo lại ảnh cảnh."
                        : "Nguyên nhân hay gặp nhất: gương mặt người mẫu. Ở Bước 1 bấm \"🎬 Kiểm tra với Flow\" để biết chắc, chặn thì đổi người mẫu."}</p>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent"
                              onClick={() => boardId !== null && navigate(`/clips/${boardId}/setup`)}>
                        Sang Bước 1 · người mẫu
                      </button>
                    </>
                  ) : (
                    <p>Thử: bấm "Tạo" lại, đổi ảnh cảnh này ở bước 3 sang góc cận sản phẩm, hoặc ⬆ Dùng video của bạn.</p>
                  )}
                </div>
              )}
              {regenFor === scene.index && node && hasMedia(node) && !isBusy(node) && (
                <RegenBox node={node} kind={kind} onSubmit={(r) => regenerate(scene.index, r)} onClose={() => setRegenFor(null)} />
              )}
            </div>
            );
          })}
          {items.length === 0 && <div className="qt-empty">Board chưa có cảnh nào.</div>}
        </div>
        {kind === "video" && (
          <input ref={fileRef} type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm" hidden
                 onChange={(e) => { void onVideoFile(e.target.files); e.target.value = ""; }} />
        )}
      </section>
      {kind === "video" && roles.scenes.some((s) => s.video) && (
        <MuseBridge roles={roles} productName={productName} boardName={boardName} boardId={boardId}
                    focus={museFocus} waits={waits} now={now} />
      )}
    </div>
  );
}
