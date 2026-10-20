import { useRef, useState } from "react";
import { mediaUrl, patchNode, setBoardModelMode, type QuicktoolState } from "../../api/client";
import { CHARACTER_COUNTRIES, CHARACTER_GENDERS, CHARACTER_VIBES } from "../../constants/character";
import { useBoardStore, type FlowNode } from "../../store/board";
import { useGenerationStore } from "../../store/generation";
import { MAX_PRODUCT_PHOTOS, useQuicktoolStore } from "../../store/quicktool";
import { useSettingsStore } from "../../store/settings";
import { hasMedia, isBusy, type ClipRoles } from "../roles";

function setNodeData(n: FlowNode, patch: Record<string, unknown>) {
  useBoardStore.getState().updateNodeData(n.id, patch);
  const dbId = parseInt(n.id, 10);
  if (!isNaN(dbId)) patchNode(dbId, { data: patch }).catch(() => {});
}

/** Step 1 — the inputs: product photos, the model, the render settings. */
export function StepSetup({ roles, sourceMediaId = null, personRequired = false, hands = null }: {
  roles: ClipRoles;
  sourceMediaId?: string | null;
  /** Clothes: the clip must show a person, so no hands-only switch. */
  personRequired?: boolean;
  /** The board's stored hands-only setting (null = a model). */
  hands?: QuicktoolState["hands"];
}) {
  const uploadToNode = useQuicktoolStore((s) => s.uploadToNode);
  const addProductPhoto = useQuicktoolStore((s) => s.addProductPhoto);
  const removeProductPhoto = useQuicktoolStore((s) => s.removeProductPhoto);
  const [addingPhoto, setAddingPhoto] = useState(false);
  const addRef = useRef<HTMLInputElement>(null);

  async function addPhotos(files: FileList | null) {
    if (!files?.length) return;
    setAddingPhoto(true);
    try {
      const room = MAX_PRODUCT_PHOTOS - roles.products.length;
      for (const f of Array.from(files).slice(0, Math.max(room, 0))) {
        if (!(await addProductPhoto(f))) break;
      }
    } finally {
      setAddingPhoto(false);
    }
  }
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
  const boardId = useBoardStore((s) => s.boardId);
  const [handGender, setHandGender] = useState<"female" | "male">(hands?.gender === "hands_male" ? "male" : "female");
  const [handCountry, setHandCountry] = useState(hands?.country ?? (model?.data.charCountry as string) ?? "vn");
  const [handLook, setHandLook] = useState(hands?.look ?? "");
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const handsMode = !model && !!hands;

  /** Person ⇄ hands on the existing board: the agent rewrites the scene
   * prompts and adds / removes the model node, then the board is re-read. */
  async function applyMode(mode: "person" | "hands", next?: Partial<{ gender: "female" | "male"; country: string; look: string }>) {
    if (boardId === null || switching) return;
    const gender = next?.gender ?? handGender;
    const country = next?.country ?? handCountry;
    const look = next?.look ?? handLook;
    setSwitching(true);
    setSwitchError(null);
    try {
      await setBoardModelMode(boardId, mode === "hands"
        ? { mode, gender, country, hand_look: look }
        : { mode, gender: (model?.data.charGender as "female" | "male") ?? gender, country, vibe: (model?.data.charVibe as string) ?? "casual" });
      await Promise.all([useBoardStore.getState().refreshBoardState(), useBoardStore.getState().refreshBoardList()]);
    } catch (err) {
      setSwitchError(err instanceof Error ? err.message : "không đổi được kiểu mẫu");
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div className="qt-step qt-step--two">
      <section className="qt-card">
        <div className="qt-card__eyebrow">Bước 1 · Sản phẩm</div>
        <h3 className="qt-card__title">Ảnh & nội dung sản phẩm</h3>
        <p className="qt-card__hint">
          Ảnh thật của sản phẩm, tối đa {MAX_PRODUCT_PHOTOS} ảnh, mỗi ảnh một góc: mặt trước, mặt sau, cận chất liệu,
          và nên có <strong>một ảnh người cầm sản phẩm trên tay</strong> để AI hiểu đúng kích thước. Mọi ảnh đều được
          đưa vào từng cảnh làm tham chiếu.
        </p>
        <div className="qt-photos">
          {roles.products.map((p, i) => (
            <div key={p.id} className="qt-photo">
              {hasMedia(p) ? (
                <img src={mediaUrl(p.data.mediaId as string)} alt="" onClick={() => useGenerationStore.getState().openResultViewer(p.id)} />
              ) : (
                <button type="button" className="qt-photo__empty" onClick={() => pickPhoto(p)}>
                  + Upload ảnh
                </button>
              )}
              <div className="qt-photo__name">{p.data.title}</div>
              <div className="qt-row qt-row--tight">
                {hasMedia(p) && (
                  <button type="button" className="qt-link" onClick={() => pickPhoto(p)}>Đổi ảnh</button>
                )}
                {i > 0 && (
                  <button type="button" className="qt-link qt-link--danger" onClick={() => void removeProductPhoto(p.id)}>Bỏ ảnh</button>
                )}
              </div>
              {typeof p.data.aiBrief === "string" && p.data.aiBrief && (
                <div className="qt-photo__brief" title={p.data.aiBrief}>✨ {p.data.aiBrief}</div>
              )}
            </div>
          ))}
          {roles.products.length > 0 && roles.products.length < MAX_PRODUCT_PHOTOS && (
            <div className="qt-photo">
              <button type="button" className="qt-photo__empty qt-photo__empty--add" disabled={addingPhoto}
                      onClick={() => addRef.current?.click()} title="Thêm một ảnh sản phẩm ở góc khác">
                {addingPhoto ? "Đang thêm…" : "+ Thêm góc khác"}
              </button>
              <div className="qt-photo__name">{roles.products.length}/{MAX_PRODUCT_PHOTOS} ảnh</div>
            </div>
          )}
          {roles.products.length === 0 && (
            <div className="qt-empty">Mẫu này không có node sản phẩm. Thêm trong Canvas nếu cần.</div>
          )}
        </div>
        <input ref={addRef} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden
               onChange={(e) => { void addPhotos(e.target.files); e.target.value = ""; }} />
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
        <div className="qt-card__eyebrow">Bước 1 · Người mẫu</div>
        <h3 className="qt-card__title">Người mẫu & thiết lập bản dựng</h3>
        {!personRequired && (
          <div className="qt-mode" role="radiogroup" aria-label="Kiểu mẫu">
            <button type="button" role="radio" aria-checked={!handsMode} disabled={switching}
                    className={`qt-mode__opt${!handsMode ? " qt-mode__opt--active" : ""}`}
                    onClick={() => handsMode && void applyMode("person")}>
              👤 Người mẫu
            </button>
            <button type="button" role="radio" aria-checked={handsMode} disabled={switching}
                    className={`qt-mode__opt${handsMode ? " qt-mode__opt--active" : ""}`}
                    onClick={() => !handsMode && void applyMode("hands")}
                    title="Không lộ mặt: chỉ bàn tay cầm, bẻ, dùng sản phẩm, quay trực diện">
              ✋ Chỉ bàn tay (không lộ mặt)
            </button>
            {switching && <span className="qt-mode__busy">Đang đổi…</span>}
          </div>
        )}
        {switchError && <p className="product-form__error" role="alert">{switchError}</p>}
        {handsMode ? (
          <div className="qt-model__form">
            <label className="qt-field">
              <span>Bàn tay</span>
              <select value={handGender} disabled={switching}
                      onChange={(e) => { const g = e.target.value as "female" | "male"; setHandGender(g); void applyMode("hands", { gender: g }); }}>
                <option value="female">Tay nữ</option>
                <option value="male">Tay nam</option>
              </select>
            </label>
            <label className="qt-field">
              <span>Quốc gia</span>
              <select value={handCountry} disabled={switching}
                      onChange={(e) => { setHandCountry(e.target.value); void applyMode("hands", { country: e.target.value }); }}>
                {CHARACTER_COUNTRIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select>
            </label>
            <label className="qt-field qt-field--wide">
              <span>Mô tả bàn tay (tiếng Anh; trống = tay đẹp, da mịn, móng sạch)</span>
              <input type="text" maxLength={200} value={handLook} placeholder="ví dụ: chubby hands, short nails" disabled={switching}
                     onChange={(e) => setHandLook(e.target.value)}
                     onBlur={() => { if ((hands?.look ?? "") !== handLook.trim()) void applyMode("hands", { look: handLook.trim() }); }} />
            </label>
            <p className="qt-card__hint qt-field--wide">Không có người mẫu: mọi cảnh chỉ quay bàn tay và sản phẩm, góc trực diện. Đổi ở đây sẽ sửa lại prompt của các cảnh; ảnh/video đã tạo trước đó cần bấm "Tạo lại".</p>
          </div>
        ) : model ? (
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
          <div className="qt-empty">
            Clip này không có người mẫu (chỉ sản phẩm).{" "}
            {!personRequired && <button type="button" className="qt-btn qt-btn--small" disabled={switching} onClick={() => void applyMode("person")}>Thêm người mẫu</button>}
          </div>
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
