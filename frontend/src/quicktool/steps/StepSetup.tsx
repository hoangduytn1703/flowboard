import { useRef } from "react";
import { mediaUrl, patchNode } from "../../api/client";
import { CHARACTER_COUNTRIES, CHARACTER_GENDERS, CHARACTER_VIBES } from "../../constants/character";
import { useBoardStore, type FlowNode } from "../../store/board";
import { useGenerationStore } from "../../store/generation";
import { useQuicktoolStore } from "../../store/quicktool";
import { useSettingsStore } from "../../store/settings";
import { hasMedia, isBusy, type ClipRoles } from "../roles";

function setNodeData(n: FlowNode, patch: Record<string, unknown>) {
  useBoardStore.getState().updateNodeData(n.id, patch);
  const dbId = parseInt(n.id, 10);
  if (!isNaN(dbId)) patchNode(dbId, { data: patch }).catch(() => {});
}

/** Step 1 — the inputs: product photos, the model, the render settings. */
export function StepSetup({ roles, sourceMediaId = null }: { roles: ClipRoles; sourceMediaId?: string | null }) {
  const uploadToNode = useQuicktoolStore((s) => s.uploadToNode);
  const generateModel = useQuicktoolStore((s) => s.generateModel);
  const videoModel = useSettingsStore((s) => s.videoModel);
  const omniDuration = useSettingsStore((s) => s.omniFlashDuration);
  const videoQuality = useSettingsStore((s) => s.videoQuality);
  const imageModel = useSettingsStore((s) => s.imageModel);
  const fileRef = useRef<HTMLInputElement>(null);
  const pendingNode = useRef<string | null>(null);

  function pickPhoto(n: FlowNode) {
    pendingNode.current = n.id;
    fileRef.current?.click();
  }

  const model = roles.model;

  return (
    <div className="qt-step qt-step--two">
      <section className="qt-card">
        <div className="qt-card__eyebrow">Input 1/2 · Bước 1</div>
        <h3 className="qt-card__title">Ảnh & nội dung sản phẩm</h3>
        <p className="qt-card__hint">
          Ảnh thật của sản phẩm. Nên có <strong>một ảnh người cầm sản phẩm trên tay</strong> để AI hiểu đúng
          kích thước; ảnh phụ (mặt sau, cận chất liệu) giúp giữ đúng chi tiết.
        </p>
        <div className="qt-photos">
          {roles.products.map((p) => (
            <div key={p.id} className="qt-photo">
              {hasMedia(p) ? (
                <img src={mediaUrl(p.data.mediaId as string)} alt="" onClick={() => useGenerationStore.getState().openResultViewer(p.id)} />
              ) : (
                <button type="button" className="qt-photo__empty" onClick={() => pickPhoto(p)}>
                  + Upload ảnh
                </button>
              )}
              <div className="qt-photo__name">{p.data.title}</div>
              {hasMedia(p) && (
                <button type="button" className="qt-link" onClick={() => pickPhoto(p)}>Đổi ảnh</button>
              )}
              {typeof p.data.aiBrief === "string" && p.data.aiBrief && (
                <div className="qt-photo__brief" title={p.data.aiBrief}>✨ {p.data.aiBrief}</div>
              )}
            </div>
          ))}
          {roles.products.length === 0 && (
            <div className="qt-empty">Mẫu này không có node sản phẩm. Thêm trong Canvas nếu cần.</div>
          )}
        </div>
        {sourceMediaId && (
          <div className="qt-source">
            <div className="qt-card__eyebrow">Video mẫu đã phân tích</div>
            <video src={mediaUrl(sourceMediaId)} controls muted playsInline preload="metadata" />
          </div>
        )}
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            const id = pendingNode.current;
            if (f && id) void uploadToNode(id, f);
            e.target.value = "";
          }}
        />
      </section>

      <section className="qt-card">
        <div className="qt-card__eyebrow">Input 2/2 · Bước 1</div>
        <h3 className="qt-card__title">Người mẫu & thiết lập bản dựng</h3>
        {model ? (
          <div className="qt-model">
            <div className="qt-model__preview">
              {hasMedia(model) ? (
                <img src={mediaUrl(model.data.mediaId as string)} alt="" onClick={() => useGenerationStore.getState().openResultViewer(model.id)} />
              ) : (
                <div className={`qt-photo__empty qt-photo__empty--static${isBusy(model) ? " qt-busy" : ""}`}>
                  {isBusy(model) ? "Đang tạo…" : "Chưa có"}
                </div>
              )}
            </div>
            <div className="qt-model__form">
              <label className="qt-field">
                <span>Giới tính</span>
                <select value={(model.data.charGender as string) ?? "female"} onChange={(e) => setNodeData(model, { charGender: e.target.value })}>
                  {CHARACTER_GENDERS.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
                </select>
              </label>
              <label className="qt-field">
                <span>Quốc gia</span>
                <select value={(model.data.charCountry as string) ?? "vn"} onChange={(e) => setNodeData(model, { charCountry: e.target.value })}>
                  {CHARACTER_COUNTRIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                </select>
              </label>
              <label className="qt-field">
                <span>Phong cách</span>
                <select value={(model.data.charVibe as string) ?? "clean"} onChange={(e) => setNodeData(model, { charVibe: e.target.value })}>
                  {CHARACTER_VIBES.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
                </select>
              </label>
              <label className="qt-field qt-field--wide">
                <span>Mô tả thêm (tiếng Anh: tóc, tuổi, nét mặt)</span>
                <input
                  key={model.id}
                  type="text"
                  maxLength={200}
                  defaultValue={(model.data.charExtras as string) ?? ""}
                  onBlur={(e) => setNodeData(model, { charExtras: e.target.value.trim() })}
                />
              </label>
              <div className="qt-field--wide qt-row">
                <button type="button" className="qt-btn" disabled={isBusy(model)} onClick={() => void generateModel()}>
                  {hasMedia(model) ? "Tạo lại người mẫu" : "Tạo người mẫu"}
                </button>
                <button type="button" className="qt-btn qt-btn--ghost" onClick={() => pickPhoto(model)}>
                  Upload ảnh người thật
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="qt-empty">Mẫu này không dùng người mẫu.</div>
        )}

        <div className="qt-settings">
          <div className="qt-setting"><span>Tỉ lệ</span><strong>9:16 dọc (TikTok)</strong></div>
          <div className="qt-setting"><span>Model ảnh</span><strong>{imageModel}</strong></div>
          <div className="qt-setting">
            <span>Model video</span>
            <strong>{videoModel === "omni_flash" ? `Omni Flash · ${omniDuration}s/clip` : `Veo 3.1 ${videoQuality}`}</strong>
          </div>
          <div className="qt-setting"><span>Số cảnh</span><strong>{roles.scenes.length}</strong></div>
        </div>
        <p className="qt-card__hint">Đổi model ảnh/video trong ⚙ Settings (góc dưới trái).</p>
      </section>
    </div>
  );
}
