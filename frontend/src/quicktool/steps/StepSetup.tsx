import { useEffect, useRef, useState } from "react";
import {
  characterBadges,
  characterPhotoUrl,
  defaultCharacterLabel,
  voiceOf,
  type CharacterMeta,
  type SavedCharacter,
} from "../../api/characters";
import { VOICES, allowedModelGenders, mediaUrl, patchNode, setBoardModelMode, type ProductGender, type QuicktoolState } from "../../api/client";
import { CHARACTER_COUNTRIES, CHARACTER_GENDERS, CHARACTER_VIBES } from "../../constants/character";
import type { CountryKey, GenderKey, VibeKey } from "../../constants/character";
import { buildCharacterPrompt } from "../../lib/characterPrompt";
import { ProductFaceCheck } from "../ProductFaceCheck";
import { useBoardStore, type FlowNode } from "../../store/board";
import { useGenerationStore } from "../../store/generation";
import { MAX_PRODUCT_PHOTOS, useQuicktoolStore } from "../../store/quicktool";
import { useCharactersStore } from "../../store/references";
import { checkModelNode, knownFlowCheck } from "../flowModelCheck";
import { useSettingsStore } from "../../store/settings";
import { hasMedia, isBusy, type ClipRoles } from "../roles";
import "../models.css";
import { toast, useToastOn } from "../../store/toast";
import { askConfirm, askText } from "../../components/Dialogs";

function setNodeData(n: FlowNode, patch: Record<string, unknown>) {
  useBoardStore.getState().updateNodeData(n.id, patch);
  const dbId = parseInt(n.id, 10);
  if (!isNaN(dbId)) patchNode(dbId, { data: patch }).catch(() => {});
}

/** The character-builder form of a model node, as stored in the library. */
function modelMeta(model: FlowNode, product: string | undefined): CharacterMeta {
  const d = model.data;
  const gender = (typeof d.charGender === "string" ? d.charGender : "female") as GenderKey;
  const country = (typeof d.charCountry === "string" ? d.charCountry : "vn") as CountryKey;
  const vibe = (typeof d.charVibe === "string" ? d.charVibe : "clean") as VibeKey;
  const extras = typeof d.charExtras === "string" ? d.charExtras : "";
  return {
    gender, country, vibe, extras,
    prompt: buildCharacterPrompt(gender, country, vibe, extras),
    product,
  };
}

/** Step 1 — the inputs: product photos, the model, the render settings. */
/** "🎬 Kiểm tra với Flow": one short probe clip from the model photo alone. */
function FlowCheckButton({ node }: { node: FlowNode }) {
  const [busy, setBusy] = useState(false);
  const check = knownFlowCheck(node);
  const running = busy || check?.status === "running";
  async function run() {
    if (!await askConfirm("Thử tạo 1 video 8 giây chỉ từ ảnh người mẫu để xem Flow có chặn gương mặt này không (~12 credit nếu qua, bị chặn thì được hoàn, mất 1–3 phút). Tiếp tục?")) return;
    setBusy(true);
    try {
      const v = await checkModelNode(node);
      if (v.status === "ok") toast.success("Flow làm video với người mẫu này được.");
      else toast.warning("Flow chặn video của người mẫu này (giống người thật / người nổi tiếng). Nên đổi người mẫu trước khi tạo video.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Kiểm tra thất bại.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <button type="button" className="qt-btn qt-btn--ghost" disabled={running || isBusy(node)} onClick={() => void run()}
            title="Tạo thử 1 video ngắn từ ảnh người mẫu để biết Flow có chặn gương mặt này không">
      {running ? "Đang kiểm tra với Flow…" : check?.status ? "🎬 Kiểm tra lại với Flow" : "🎬 Kiểm tra với Flow"}
    </button>
  );
}

function FlowCheckNote({ node }: { node: FlowNode }) {
  const check = knownFlowCheck(node);
  if (check?.status === "ok") return <p className="qt-card__hint qt-field--wide qt-flowcheck qt-flowcheck--ok">✓ Đã thử: Flow làm video với gương mặt này được.</p>;
  if (check?.status === "blocked") {
    return (
      <p className="qt-card__hint qt-field--wide qt-flowcheck qt-flowcheck--blocked">
        ✕ Flow chặn video có gương mặt này (bị coi là giống người thật / người nổi tiếng) — mọi cảnh có người mẫu sẽ không ra video.
        Hãy "Tạo lại người mẫu", chọn mẫu khác trong thư viện hoặc upload ảnh người thật, rồi tạo lại ảnh cảnh.
      </p>
    );
  }
  return null;
}

export function StepSetup({ roles, sourceMediaId = null, personRequired = false, hands = null, productGender = "", productId = null, productName = "" }: {
  roles: ClipRoles;
  /** The saved product behind the clip: a clean product-only shot is added to its photos. */
  productId?: number | null;
  productName?: string;
  /** Who the clip's product is for; a men's / women's product only gets models of that gender. */
  productGender?: ProductGender;
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
  const [uploadingNode, setUploadingNode] = useState<string | null>(null);

  /** Extra angles: each file becomes a new product-photo node. */
  async function addPhotos(files: File[]) {
    if (!files.length) return;
    setAddingPhoto(true);
    try {
      const room = MAX_PRODUCT_PHOTOS - roles.products.length;
      for (const f of files.slice(0, Math.max(room, 0))) {
        if (!(await addProductPhoto(f))) break;
      }
    } finally {
      setAddingPhoto(false);
    }
  }

  /** One file input serves both "put this photo on that node" and "add
   * more angles": which one depends on `pendingNode`, so the first visible
   * upload button can never land a photo on the wrong node. */
  async function onFiles(files: FileList | null) {
    const list = Array.from(files ?? []);
    // No button picked a node (a drop, an automated upload): an empty main
    // product node takes the first photo rather than becoming "ảnh 2".
    const main = roles.products[0];
    const id = pendingNode.current ?? (main && !hasMedia(main) ? main.id : null);
    pendingNode.current = null;
    if (!list.length) return;
    if (id) {
      setUploadingNode(id);
      try {
        await uploadToNode(id, list[0]);
      } finally {
        setUploadingNode(null);
      }
      // A product node took the first file; the rest become extra angles.
      if (list.length > 1 && roles.products.some((p) => p.id === id)) await addPhotos(list.slice(1));
    } else {
      await addPhotos(list);
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

  function pickMore() {
    pendingNode.current = null;
    fileRef.current?.click();
  }

  const model = roles.model;
  const allowedGenders = allowedModelGenders(productGender);
  const genderLocked = productGender === "male" || productGender === "female";
  const forWhom = productGender === "male" ? "nam" : "nữ";
  const modelGender = (model?.data.charGender as string) ?? "female";
  const modelGenderWrong = !!model && genderLocked && !allowedGenders.includes(modelGender as "female" | "male");
  const boardId = useBoardStore((s) => s.boardId);
  const boardName = useBoardStore((s) => s.boardName || undefined);

  // Model library: ★ save the rendered / uploaded model, or put a saved one
  // on this clip. The store is shared with the /models page.
  const characters = useCharactersStore((s) => s.items);
  const charactersLoaded = useCharactersStore((s) => s.loaded);
  const charactersError = useCharactersStore((s) => s.error);
  useToastOn(charactersError ? `Không tải được thư viện người mẫu: ${charactersError}` : null, "error");
  const loadCharacters = useCharactersStore((s) => s.load);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [savingModel, setSavingModel] = useState(false);
  useEffect(() => { void loadCharacters(); }, [loadCharacters]);
  const modelMediaId = model && hasMedia(model) ? (model.data.mediaId as string) : null;
  const modelSaved = !!modelMediaId && characters.some((c) => c.mediaId === modelMediaId);

  async function saveModel() {
    if (!model || !modelMediaId || savingModel) return;
    const meta = modelMeta(model, boardName);
    const fallback = defaultCharacterLabel(meta);
    const name = await askText("Đặt tên cho người mẫu này (để dùng lại cho sản phẩm khác):", fallback);
    if (name === null) return;
    setSavingModel(true);
    try {
      const row = await useCharactersStore.getState().save({
        media_id: modelMediaId,
        label: name.trim() || fallback,
        meta,
        ai_brief: typeof model.data.aiBrief === "string" ? model.data.aiBrief : null,
        aspect_ratio: typeof model.data.aspectRatio === "string" ? model.data.aspectRatio : "9:16",
        source_board_id: boardId,
        source_node_short_id: typeof model.data.shortId === "string" ? model.data.shortId : null,
      });
      toast.success(`Đã lưu "${row.label}" vào thư viện người mẫu. Đặt giọng đọc và câu nói cho người mẫu ở trang Người mẫu đã lưu.`);
    } catch (err) {
      toast.error(`Không lưu được người mẫu: ${err instanceof Error ? err.message : "lỗi"}`);
    } finally {
      setSavingModel(false);
    }
  }

  /** Put a saved model on this clip's model node: photo + form, marked as
   * rendered so the scenes take it as their character reference. */
  function applySavedModel(c: SavedCharacter) {
    if (!model) return;
    const patch: Record<string, unknown> = {
      mediaId: c.mediaId,
      mediaIds: [c.mediaId],
      variantCount: 1,
      status: "done",
      charGender: c.meta.gender ?? model.data.charGender ?? "female",
      charCountry: c.meta.country ?? model.data.charCountry ?? "vn",
      charVibe: c.meta.vibe ?? model.data.charVibe ?? "clean",
      charExtras: c.meta.extras ?? "",
      aspectRatio: c.aspectRatio ?? model.data.aspectRatio ?? "9:16",
    };
    useBoardStore.getState().updateNodeData(model.id, { ...patch, aiBrief: c.aiBrief ?? undefined, error: undefined });
    const dbId = parseInt(model.id, 10);
    if (!isNaN(dbId)) {
      patchNode(dbId, {
        status: "done",
        data: { ...patch, aiBrief: c.aiBrief, error: null, renderedAt: new Date().toISOString() },
      }).catch(() => {});
    }
    setPickerOpen(false);
    void applyModelVoice(c);
  }

  /** The saved model's voice becomes the clip's voice-over (export node), and
   * its line, if any, opens scene 1's voice line. */
  async function applyModelVoice(c: SavedCharacter) {
    const said: string[] = [`Đang dùng người mẫu "${c.label}". Các cảnh sẽ lấy ảnh này làm tham chiếu.`];
    try {
      const voice = voiceOf(c);
      const expId = await useQuicktoolStore.getState().ensureExportNode();
      if (expId) {
        const patch: Record<string, unknown> = { voice, voiceStyle: c.meta.voiceStyle ?? "" };
        useBoardStore.getState().updateNodeData(expId, patch);
        const dbId = parseInt(expId, 10);
        if (!isNaN(dbId)) await patchNode(dbId, { data: patch });
        said.push(`Giọng đọc của clip: ${VOICES[voice] ?? voice}.`);
      }
      const line = c.meta.line?.trim();
      const first = roles.scenes[0]?.video;
      if (line && first) {
        const cur = typeof first.data.narration === "string" ? first.data.narration.trim() : "";
        if (!cur.startsWith(line)) {
          const narration = cur ? `${line} ${cur}` : line;
          useBoardStore.getState().updateNodeData(first.id, { narration });
          const dbId = parseInt(first.id, 10);
          if (!isNaN(dbId)) await patchNode(dbId, { data: { narration } });
          said.push("Đã thêm câu nói của người mẫu vào đầu lời thoại cảnh 1.");
        }
      }
      toast.success(said.join(" "));
    } catch (err) {
      toast.error(`Đã đổi người mẫu nhưng chưa đặt được giọng đọc: ${err instanceof Error ? err.message : "lỗi"}`);
    }
  }
  const [handGender, setHandGender] = useState<"female" | "male">(hands?.gender === "hands_male" ? "male" : "female");
  const [handCountry, setHandCountry] = useState(hands?.country ?? (model?.data.charCountry as string) ?? "vn");
  const [handLook, setHandLook] = useState(hands?.look ?? "");
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  useToastOn(switchError, "error", () => setSwitchError(null));
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
          và nên có <strong>một ảnh bàn tay cầm sản phẩm</strong> để AI hiểu đúng kích thước. Mọi ảnh đều được
          đưa vào từng cảnh làm tham chiếu — <strong>tránh ảnh có mặt người mẫu thật</strong> (ảnh shop): Flow hay chặn video
          làm từ mặt người thật.
        </p>
        <div className="qt-photos">
          {roles.products.map((p, i) => (
            <div key={p.id} className="qt-photo">
              {hasMedia(p) ? (
                <img src={mediaUrl(p.data.mediaId as string)} alt="" onClick={() => useGenerationStore.getState().openResultViewer(p.id)} />
              ) : (
                <button type="button" className="qt-photo__empty" disabled={uploadingNode === p.id} onClick={() => pickPhoto(p)}>
                  {uploadingNode === p.id ? "Đang tải…" : "+ Upload ảnh"}
                </button>
              )}
              <div className="qt-photo__name">{p.data.title}</div>
              <div className="qt-row qt-row--tight">
                {hasMedia(p) && (
                  <button type="button" className="qt-link" disabled={uploadingNode === p.id} onClick={() => pickPhoto(p)}>{uploadingNode === p.id ? "Đang tải…" : "Đổi ảnh"}</button>
                )}
                {i > 0 && (
                  <button type="button" className="qt-link qt-link--danger" onClick={() => void removeProductPhoto(p.id)}>Bỏ ảnh</button>
                )}
              </div>
              {hasMedia(p) && <ProductFaceCheck node={p} productId={productId} productName={productName} />}
              {typeof p.data.aiBrief === "string" && p.data.aiBrief && (
                <div className="qt-photo__brief" title={p.data.aiBrief}>✨ {p.data.aiBrief}</div>
              )}
            </div>
          ))}
          {roles.products.length > 0 && roles.products.length < MAX_PRODUCT_PHOTOS && (
            <div className="qt-photo">
              <button type="button" className="qt-photo__empty qt-photo__empty--add" disabled={addingPhoto}
                      onClick={pickMore} title="Thêm một ảnh sản phẩm ở góc khác">
                {addingPhoto ? "Đang thêm…" : "+ Thêm góc khác"}
              </button>
              <div className="qt-photo__name">{roles.products.length}/{MAX_PRODUCT_PHOTOS} ảnh</div>
            </div>
          )}
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
          multiple
          hidden
          onChange={(e) => {
            void onFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </section>

      <section className="qt-card">
        <div className="qt-card__eyebrow">Bước 1 · Người mẫu</div>
        <h3 className="qt-card__title">Người mẫu & thiết lập bản dựng</h3>
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
            {personRequired && (
              <small className="qt-field--wide qt-gender-note">💡 Gợi ý: quần áo / đồ ăn thường đẹp hơn khi có người mặc / ăn thử. Túi, phụ kiện, đồ cầm tay thì chỉ quay bàn tay vẫn ổn — bạn chọn.</small>
            )}
            {genderLocked && handGender !== productGender && (
              <small className="qt-field--wide qt-gender-note">💡 Gợi ý: sản phẩm dành cho {forWhom} — tay {forWhom} hợp hơn.</small>
            )}
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
                <select value={modelGender} onChange={(e) => setNodeData(model, { charGender: e.target.value })}>
                  {CHARACTER_GENDERS.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
                </select>
              </label>
              {modelGenderWrong && (
                <div className="qt-gender-warn qt-field--wide" role="alert">
                  💡 Gợi ý: sản phẩm này dành cho <strong>{forWhom}</strong> nhưng người mẫu đang là {modelGender === "male" ? "nam" : "nữ"} (vẫn dùng được nếu bạn muốn).
                  <button type="button" className="qt-btn qt-btn--small"
                          onClick={() => setNodeData(model, { charGender: allowedGenders[0] })}>
                    Đổi sang người mẫu {forWhom}
                  </button>
                  {hasMedia(model) && <small> Sau khi đổi, bấm "Tạo lại người mẫu" hoặc chọn mẫu {forWhom} từ thư viện để có ảnh mới.</small>}
                </div>
              )}
              {genderLocked && !modelGenderWrong && <small className="qt-field--wide qt-gender-note">Sản phẩm dành cho {forWhom}.</small>}
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
                  // Remount when extras change from outside (a saved model
                  // was picked); blur commits the same value, so no flicker.
                  key={`${model.id}:${(model.data.charExtras as string) ?? ""}`}
                  type="text"
                  maxLength={200}
                  defaultValue={(model.data.charExtras as string) ?? ""}
                  onBlur={(e) => setNodeData(model, { charExtras: e.target.value.trim() })}
                />
              </label>
              <div className="qt-field--wide qt-row">
                <button type="button" className="qt-btn" disabled={isBusy(model)} onClick={() => void generateModel(true)}>
                  {hasMedia(model) ? "Tạo lại người mẫu" : "Tạo người mẫu"}
                </button>
                <button type="button" className="qt-btn qt-btn--ghost" onClick={() => pickPhoto(model)}>
                  Upload ảnh người thật
                </button>
                <button type="button" className={`qt-btn qt-btn--ghost${pickerOpen ? " qt-btn--on" : ""}`}
                        onClick={() => setPickerOpen((o) => !o)}
                        title="Dùng lại một người mẫu đã lưu từ clip / sản phẩm khác">
                  👤 Chọn từ thư viện
                </button>
                {modelMediaId && (
                  <button type="button" className="qt-btn qt-btn--ghost" disabled={modelSaved || savingModel || isBusy(model)}
                          onClick={() => void saveModel()}
                          title={modelSaved ? "Ảnh người mẫu này đã có trong thư viện" : "Lưu người mẫu này để dùng cho sản phẩm khác"}>
                    {modelSaved ? "✓ Đã lưu" : savingModel ? "Đang lưu…" : "★ Lưu người mẫu"}
                  </button>
                )}
                {modelMediaId && model && <FlowCheckButton node={model} />}
              </div>
              {model && <FlowCheckNote node={model} />}
            </div>
          </div>
        ) : (
          <div className="qt-empty">
            Clip này không có người mẫu (chỉ sản phẩm).{" "}
            <button type="button" className="qt-btn qt-btn--small" disabled={switching} onClick={() => void applyMode("person")}>Thêm người mẫu</button>
          </div>
        )}

        {model && !handsMode && pickerOpen && (
          <div className="qt-models-picker" role="region" aria-label="Thư viện người mẫu">
            <div className="qt-card__head">
              <div>
                <div className="qt-card__eyebrow">Thư viện người mẫu</div>
                <div className="qt-models-picker__title">Chọn một người mẫu đã lưu cho clip này</div>
              </div>
              <button type="button" className="qt-link" onClick={() => setPickerOpen(false)}>Đóng</button>
            </div>
            {!charactersLoaded ? (
              <div className="qt-models-picker__grid" aria-hidden="true">
                {Array.from({ length: 3 }, (_, i) => (
                  <div key={`sk-${i}`} className="qt-model-card qt-model-card--skeleton">
                    <span className="qt-model-card__photo qt-skeleton" />
                    <span className="qt-skeleton qt-skeleton--line" />
                    <span className="qt-skeleton qt-skeleton--line qt-skeleton--short" />
                  </div>
                ))}
              </div>
            ) : characters.length === 0 ? (
              <div className="qt-empty">Chưa có người mẫu nào — tạo một người mẫu rồi bấm ★ Lưu.</div>
            ) : (
              <div className="qt-models-picker__grid">
                {characters.map((c) => {
                  const current = c.mediaId === modelMediaId;
                  const wrongGender = genderLocked && !!c.meta.gender && !allowedGenders.includes(c.meta.gender as "female" | "male");
                  return (
                    <div key={c.id} className={`qt-model-card${current ? " qt-model-card--current" : ""}`}>
                      <img className="qt-model-card__photo" src={characterPhotoUrl(c)} alt={c.label} loading="lazy" />
                      <div className="qt-model-card__name" title={c.label}>{c.label}</div>
                      <div className="qt-badges">
                        {characterBadges(c.meta).map((b) => <span key={b} className="qt-badge">{b}</span>)}
                      </div>
                      <div className="qt-model-card__voice" title="Giọng đọc của người mẫu — thành giọng đọc của clip khi dùng">🎙 {VOICES[voiceOf(c)]?.split(" · ")[0] ?? voiceOf(c)}</div>
                      <button type="button" className={`qt-btn qt-btn--small${current ? "" : " qt-btn--accent"}`}
                              disabled={current || isBusy(model)} onClick={() => applySavedModel(c)}
                              title={wrongGender ? `Gợi ý: sản phẩm dành cho ${forWhom}` : undefined}>
                        {current ? "Đang dùng" : "Dùng người mẫu này"}
                      </button>
                      {wrongGender && !current && <small className="qt-gender-note">💡 Sản phẩm dành cho {forWhom}</small>}
                    </div>
                  );
                })}
              </div>
            )}
            <p className="qt-card__hint">Người mẫu đã lưu dùng chung cho mọi sản phẩm. Quản lý trong mục "Người mẫu đã lưu" ở thanh bên.</p>
          </div>
        )}

        <div className="qt-settings">
          <div className="qt-setting"><span>Tỉ lệ</span><strong>9:16 dọc (TikTok)</strong></div>
          <div className="qt-setting"><span>Model ảnh</span><strong>{imageModel === "NANO_BANANA_2" ? "Nano Banana 2" : "Nano Banana Pro"}</strong></div>
          <div className="qt-setting">
            <span>Model video</span>
            <strong>{videoModel === "omni_flash" ? `Omni Flash · ${omniDuration}s/clip` : `Veo 3.1 ${videoQuality}`}</strong>
          </div>
          <div className="qt-setting"><span>Số cảnh</span><strong>{roles.scenes.length}</strong></div>
        </div>
        <p className="qt-card__hint">Đổi model ảnh / video ở ⚙ Cài đặt → Tạo ảnh & video.</p>
      </section>
    </div>
  );
}
