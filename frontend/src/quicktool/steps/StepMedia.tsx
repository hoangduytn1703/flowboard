import { useRef, useState } from "react";
import { mediaUrl } from "../../api/client";
import type { FlowNode } from "../../store/board";
import { useGenerationStore } from "../../store/generation";
import { useQuicktoolStore } from "../../store/quicktool";
import { useSettingsStore } from "../../store/settings";
import { useFlowCredits } from "../../components/credits";
import { creditsPerClip, hasMedia, isBusy, type ClipRoles } from "../roles";

function statusLabel(n: FlowNode | null): string {
  if (!n) return "chưa có node";
  if (isBusy(n)) return n.data.autoPromptStatus === "pending" ? "đang viết prompt…" : "đang tạo…";
  if (n.data.status === "error") return `lỗi: ${String(n.data.error ?? "").slice(0, 80)}`;
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

/** Steps 3 and 4 — the same grid, once for scene images, once for clips. */
export function StepMedia({ roles, kind }: { roles: ClipRoles; kind: "image" | "video" }) {
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
  const fileRef = useRef<HTMLInputElement>(null);
  const pendingScene = useRef<number | null>(null);

  const items = roles.scenes.map((s) => ({ scene: s, node: kind === "image" ? s.image : s.video }));
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

  function startAll() {
    if (kind === "video") {
      const cost = missing * creditsPerClip(videoModel, videoQuality);
      const balance = flowCredits === null ? "" : ` Tài khoản còn ${flowCredits.toLocaleString("vi-VN")} credit${cost > flowCredits ? " — KHÔNG ĐỦ" : ""}.`;
      if (!window.confirm(`Tạo ${missing} video (~${cost} credit Flow, 1–3 phút mỗi clip).${balance} Tiếp tục?`)) return;
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
            Mỗi clip 8 giây bằng {videoModel === "omni_flash" ? "Omni Flash (~25 credit)" : "Veo 3.1"}, mất 1–3 phút. Clip hỏng thì bấm "Tạo lại" ở cảnh đó,
            hoặc <strong>⬆ Dùng video của bạn</strong> để thay bằng cảnh quay thật (mp4/mov, tối đa 200 MB, không tốn credit).
          </p>
        )}
        {kind === "image" && (
          <p className="qt-card__hint">Mỗi ảnh mất khoảng 20–60 giây; ảnh chưa ưng thì bấm "Tạo lại" ở cảnh đó.</p>
        )}
        <div className="qt-grid">
          {items.map(({ scene, node }) => (
            <div key={scene.image.id} className={`qt-tile${node && isBusy(node) ? " qt-tile--busy" : ""}`}>
              <div className="qt-tile__head">
                <span className="qt-tile__num">Cảnh {scene.index}</span>
                <span className={`qt-tile__status qt-tile__status--${statusTone(node)}`} title={statusLabel(node)}>{statusLabel(node)}</span>
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
                  onClick={() => void (kind === "image" ? generateScene(scene.index) : generateVideo(scene.index))}
                >
                  {node && hasMedia(node) ? "Tạo lại" : "Tạo"}
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
            </div>
          ))}
          {items.length === 0 && <div className="qt-empty">Board chưa có cảnh nào.</div>}
        </div>
        {kind === "video" && (
          <input ref={fileRef} type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm" hidden
                 onChange={(e) => { void onVideoFile(e.target.files); e.target.value = ""; }} />
        )}
      </section>
    </div>
  );
}
