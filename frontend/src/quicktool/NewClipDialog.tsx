import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  analyzeProductLink,
  analyzeDrama,
  analyzeReferenceVideo,
  buildDrama,
  buildFromReferenceVideo,
  createBoardFromTemplate,
  createProduct,
  productFromLink,
  uploadImageFromUrl,
  fetchReferenceVideo,
  listProducts,
  mediaUrl,
  uploadReferenceVideo,
  type BoardTemplate,
  type DramaPlan,
  type CharacterPick,
  allowedModelGenders,
  type Product,
  type ReferenceAnalysis,
  type ReferenceUpload,
} from "../api/client";
import { useBoardStore } from "../store/board";
import { SuggestField } from "./SuggestField";
import { BACKDROPS, backdropGroups } from "./suggestions";
import { useGenerationStore } from "../store/generation";
import { toast, useToastOn } from "../store/toast";
import { ChannelPicker } from "./channels/ChannelPicker";
import "./newclip.css";

/** The "kind of clip" card that is not a template: an uploaded ad video. */
export const REFERENCE_KIND = "reference_video";
/** The other non-template card: a product page link instead of a video. */
export const PRODUCT_LINK_KIND = "product_link";
/** A story (article link or pasted text) told as narrated stills. */
export const DRAMA_KIND = "drama";
/** Drama clips are parked for now: the card stays hidden until this is
 * flipped (the agent gates its API with FLOWBOARD_DRAMA=1 the same way). */
export const DRAMA_ENABLED = false;
const DRAMA_BEAT_CHOICES = [4, 6, 8, 10, 12];

/** Backdrops offered for the extra clips of one product, per template. The
 * first entry of each is that template's own default, so clip 1 is unchanged. */
const SETTING_IDEAS: Record<string, string[]> = {
  fashion_ad: [
    "a bright minimalist studio with wooden wardrobes behind the model",
    "a sunlit Vietnamese café terrace with rattan chairs and green plants",
    "a quiet Hanoi old-quarter street with yellow walls in soft morning light",
    "a modern co-working space with large windows and white desks",
    "a cozy bedroom corner with a full-length mirror and warm lamp light",
  ],
  cosmetics_ad: [
    "a clean pastel beauty studio with soft diffused light",
    "a bright bathroom vanity with white marble and morning window light",
    "a cozy bedroom dressing table with warm lamp light and a round mirror",
    "a minimalist cream-colored studio with a single dried-flower vase",
    "a sunny balcony with sheer curtains and potted plants",
  ],
  fast_food_ad: [
    "a bright modern fast-food diner with a wooden table",
    "a lively Vietnamese street-food stall with plastic stools at dusk",
    "a sunny rooftop terrace table with city skyline behind",
    "a cozy home kitchen counter with warm pendant light",
    "a clean white picnic table in a green park",
  ],
  unboxing_review: [
    "a tidy wooden desk by a window with soft daylight",
    "a modern living-room coffee table with a grey sofa behind",
    "a bright white studio desk with a ring light visible",
    "a cozy bedroom desk with fairy lights and a plant",
    "a minimalist workspace with a monitor and dark wooden shelves",
  ],
  grocery_ad: [
    "a clean white desk with a phone, a notebook and soft daylight",
    "a pastel bedroom desk with a small plant and a phone stand",
    "a café table with a latte and a laptop in warm light",
    "a car dashboard and console in soft daylight",
    "a tidy shop counter with a phone and a small mirror",
  ],
  home_appliance_review: [
    "a bright modern Vietnamese home kitchen with white counters and morning light",
    "a small apartment kitchen with wooden cabinets and warm evening light",
    "a tiled living room with a sofa and a balcony door open to daylight",
    "a compact laundry corner with a washing machine and shelves",
    "a family dining table with a kettle and bowls in soft daylight",
  ],
  food_review: [
    "a cozy Vietnamese eatery table with a wooden top and warm light",
    "a lively street-food stall with plastic stools at dusk",
    "a bright café window table in the morning",
    "a home dining table with a steaming pot in warm lamp light",
    "a night-market food court with string lights behind",
  ],
  affiliate_reel: [
    "a bright everyday Vietnamese living room with natural light",
    "a tidy bedroom with a desk and a window in soft daylight",
    "a small home office with a plant and a ring light",
    "a kitchen counter with morning light through the window",
    "a sunny balcony with potted plants and a small table",
  ],
};
const MAX_CLIPS = 5;

/** Second line of a product card; empty for "other" so no stray separator. */
const CATEGORY_LABEL: Record<string, string> = {
  fashion: "Thời trang",
  cosmetics: "Mỹ phẩm",
  food: "Đồ ăn",
  grocery: "Tạp hoá & phụ kiện",
  home: "Gia dụng",
};

/** Why a template refuses the hands-only mode (shown under its form). */
const PERSON_REASON: Record<string, string> = {
  fashion_ad: "Quảng cáo quần áo cần người mẫu mặc để thấy form và độ vừa, nên không có lựa chọn chỉ quay bàn tay.",
  food_review: "Review ăn thử cần có người ăn để thấy phản ứng khi nếm, nên không có lựa chọn chỉ quay bàn tay.",
};
/** A template for every product line: shown last, never tagged as the fit. */
const ANY_CATEGORY = "any";

type RefPhase = "pick" | "fetching" | "uploading" | "analyzing" | "review" | "building";

/**
 * "Clip mới": pick the product being sold (optional) and the kind of clip —
 * one of the ad templates, or "Theo video mẫu": drop an existing ad video,
 * Gemini breaks it down and adapts its beats to the product. Either way the
 * product brings its photo, description and selling points onto the board.
 * "Theo link sản phẩm" does the same from a product page instead of a video.
 * The two analyses are kept apart, so hopping between cards loses neither.
 */
export function NewClipDialog({
  templates,
  initialTemplateId,
  initialProductId,
  onClose,
  onCreated,
}: {
  templates: BoardTemplate[];
  initialTemplateId: string | null;
  initialProductId: number | null;
  onClose: () => void;
  onCreated: (boardId: number) => void;
  /** Accepted for compatibility; several clips at once now say so inline
   * and open clip #1 through `onCreated` like a single one. */
  onCreatedMany?: (boardIds: number[]) => void;
}) {
  const createNewBoardFromTemplate = useBoardStore((s) => s.createNewBoardFromTemplate);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState<number | null>(initialProductId);
  // The channel (page) the clip is for — `?channel=` from "Tạo clip cho kênh".
  const [channelId, setChannelId] = useState<number | null>(() => {
    const q = Number(new URLSearchParams(window.location.search).get("channel"));
    return q > 0 ? q : null;
  });
  const [kind, setKind] = useState<string>(initialTemplateId ?? templates[0]?.id ?? "");
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  // Review screen of a link / video clip: the model, over the AI's suggestion.
  const [pickGender, setPickGender] = useState<"auto" | CharacterPick["gender"]>("auto");
  const [pickCountry, setPickCountry] = useState("");
  const [pickHandLook, setPickHandLook] = useState("");
  // One product, several clips: clip 1 uses the "Bối cảnh" field, the others
  // these backdrops.
  const [clipCount, setClipCount] = useState(1);
  const [extraSettings, setExtraSettings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Failures are toasts: the red line above the buttons was easy to miss in a tall dialog.
  useToastOn(error, "error", () => setError(null));
  // "Số clip" > 1: how many were just made, shown while clip #1 opens.
  // Seconds since the current analysis (link / video / story) started.
  const [elapsed, setElapsed] = useState(0);
  // Reference-video mode.
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<ReferenceUpload | null>(null);
  const [analysis, setAnalysis] = useState<ReferenceAnalysis | null>(null);
  const [refPhase, setRefPhase] = useState<RefPhase>("pick");
  const [link, setLink] = useState("");
  const [linkTitle, setLinkTitle] = useState("");
  // Product-link mode.
  const [productUrl, setProductUrl] = useState("");
  const [linkAnalysis, setLinkAnalysis] = useState<ReferenceAnalysis | null>(null);
  const [linkPhase, setLinkPhase] = useState<RefPhase>("pick");
  const [analyzedUrl, setAnalyzedUrl] = useState("");
  // Drama mode.
  const [dramaInput, setDramaInput] = useState("");
  const [dramaBeats, setDramaBeats] = useState(8);
  const [dramaPlan, setDramaPlan] = useState<DramaPlan | null>(null);
  const [dramaPhase, setDramaPhase] = useState<RefPhase>("pick");
  const fileRef = useRef<HTMLInputElement>(null);

  const isReference = kind === REFERENCE_KIND;
  const isLink = kind === PRODUCT_LINK_KIND;
  const isDrama = kind === DRAMA_KIND;
  // What the current card shows: its own analysis and phase.
  const phase = isLink ? linkPhase : refPhase;
  const shown = isLink ? linkAnalysis : analysis;
  const template = templates.find((t) => t.id === kind) ?? null;
  const product = products.find((p) => p.id === productId) ?? null;
  const busyPhase = (ph: RefPhase) => ph === "fetching" || ph === "uploading" || ph === "analyzing" || ph === "building";
  const refBusy = busyPhase(refPhase) || busyPhase(linkPhase) || busyPhase(dramaPhase);
  const locked = busy || refBusy;
  // Once the video is analysed the result (prompts, fit verdict) belongs to
  // this product: picking another would throw it away, so step 1 freezes
  // until "← Đổi video" (or "Bỏ phân tích" off the reference card) goes back.
  // The clip kind stays free — hopping to a template and back keeps the
  // upload and the analysis, they live in this component's state.
  const analysisLocked = [refPhase, linkPhase].some((ph) => ph === "review" || ph === "building");
  const pickLocked = locked || analysisLocked;
  const analyzing = [refPhase, linkPhase, dramaPhase].includes("analyzing");

  // Gemini takes 20 s to a few minutes here and gives no progress: a running
  // clock on the button shows the request is alive.
  useEffect(() => {
    if (!analyzing) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [analyzing]);

  async function reloadProducts(): Promise<Product[]> {
    const list = await listProducts().catch(() => [] as Product[]);
    setProducts(list);
    return list;
  }

  // Adding a product without leaving the dialog: paste its link, the agent
  // reads the page, the product is saved to "Sản phẩm đang bán" and picked.
  const [addLinkOpen, setAddLinkOpen] = useState(false);
  const [addLink, setAddLink] = useState("");
  const [addingProduct, setAddingProduct] = useState(false);
  async function addProductFromLink() {
    const url = addLink.trim();
    if (!url || addingProduct) return;
    setAddingProduct(true);
    setError(null);
    try {
      const r = await productFromLink(url);
      let media_ids: string[] = [];
      let aspect_ratio: string | null = null;
      if (r.image_url) {
        try {
          const projectId = await useGenerationStore.getState().ensureProjectId();
          if (projectId) {
            const up = await uploadImageFromUrl(r.image_url, projectId);
            media_ids = [up.media_id];
            aspect_ratio = up.aspect_ratio ?? null;
          }
        } catch {
          // The card is still useful without a photo; it can be added later.
        }
      }
      const saved = await createProduct({ ...r.draft, media_ids, aspect_ratio });
      await reloadProducts();
      pickProduct(saved);
      setAddLink("");
      setAddLinkOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "không đọc được link sản phẩm");
    } finally {
      setAddingProduct(false);
    }
  }

  useEffect(() => {
    listProducts().then((list) => {
      setProducts(list);
      // A product chosen before the dialog opened brings its template along.
      const chosen = list.find((p) => p.id === initialProductId);
      if (chosen?.template_id && !initialTemplateId) setKind(chosen.template_id);
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Seed the inputs with the template defaults whenever the template changes.
  useEffect(() => {
    if (!template) return;
    setInputs(Object.fromEntries(template.inputs.map((i) => [i.key, i.default ?? ""])));
    setExtraSettings([]);
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Can this model pick (female / male / hands_*) be used with the chosen product? */
  function genderAllowed(v: string): boolean {
    const g = v.replace(/^hands_/, "");
    if (g !== "female" && g !== "male") return true;
    return allowedModelGenders(product?.gender).includes(g);
  }
  // Review screen: an AI-suggested model of the wrong gender for the product
  // (a woman for a men's shirt) is replaced by an allowed one up front.
  useEffect(() => {
    const suggested = shown?.character?.gender;
    if (pickGender === "auto" && suggested && !genderAllowed(suggested)) {
      setPickGender(allowedModelGenders(product?.gender)[0]);
    } else if (pickGender !== "auto" && pickGender !== "none" && !genderAllowed(pickGender)) {
      setPickGender(pickGender.startsWith("hands_") ? `hands_${allowedModelGenders(product?.gender)[0]}` as CharacterPick["gender"] : allowedModelGenders(product?.gender)[0]);
    }
  }, [shown?.character?.gender, product?.id ?? null, product?.gender, pickGender]); // eslint-disable-line react-hooks/exhaustive-deps

  // Picking a men's product while "Nữ" is selected switches it to "Nam" (and back).
  useEffect(() => {
    const cur = inputs.charGender;
    if (!cur || genderAllowed(cur)) return;
    const allowed = allowedModelGenders(product?.gender)[0];
    setInputs((p) => ({ ...p, charGender: cur.startsWith("hands_") ? `hands_${allowed}` : allowed }));
  }, [product?.id ?? null, product?.gender, inputs.charGender]); // eslint-disable-line react-hooks/exhaustive-deps

  // "Tên gọi trong lời thoại" follows the chosen product (its name), and goes
  // back to the template's wording when the product is cleared. Runs after
  // the seeding above on a template change, so the name survives it.
  useEffect(() => {
    const fallback = template?.inputs.find((i) => i.key === "product_name")?.default ?? "";
    setInputs((p) => ({ ...p, product_name: product ? product.name : fallback }));
  }, [product?.id ?? null, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !locked) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [locked, onClose]);

  function pickProduct(p: Product | null) {
    setProductId(p?.id ?? null);
    if (p?.template_id && !isReference && !isLink) setKind(p.template_id);
    // The fit verdict depends on the product: analyse again.
    if (analysis) {
      setAnalysis(null);
      setRefPhase("pick");
    }
    if (linkAnalysis) {
      setLinkAnalysis(null);
      setLinkPhase("pick");
    }
  }

  async function analyzeLink() {
    const url = productUrl.trim();
    if (!url) return;
    setError(null);
    setLinkPhase("analyzing");
    try {
      const res = await analyzeProductLink(url, productId);
      setLinkAnalysis(res.analysis);
      setAnalyzedUrl(url);
      setLinkPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "phân tích thất bại");
      setLinkPhase("pick");
    }
  }

  async function createFromLink(force: boolean) {
    if (!linkAnalysis) return;
    setError(null);
    setLinkPhase("building");
    try {
      const board = await buildFromReferenceVideo({
        mediaId: null, sourceUrl: analyzedUrl, productId, analysis: linkAnalysis, name: name.trim() || undefined, force, character: characterPick,
        channelId,
      });
      useBoardStore.setState((s) => ({
        boards: [{ id: board.id, name: board.name, created_at: board.created_at, data: board.data }, ...s.boards],
      }));
      await useBoardStore.getState().switchBoard(board.id);
      onCreated(board.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "tạo clip thất bại");
      setLinkPhase("review");
    }
  }

  /** Backdrop for extra clip ``n`` (1-based after the first): what the user
   * typed, else the next idea that differs from clip 1's. */
  function settingFor(n: number): string {
    const typed = extraSettings[n - 1];
    if (typed !== undefined) return typed;
    const first = inputs.setting ?? "";
    const category = (template?.category as string | undefined) ?? "";
    const pool = SETTING_IDEAS[kind] ?? (BACKDROPS[category] ?? Object.values(BACKDROPS).flat()).map((b) => b.value);
    const ideas = pool.filter((x) => x !== first);
    return ideas[(n - 1) % ideas.length];
  }

  /** Drama: the story is a link or pasted text; Gemini writes the beats. */
  async function analyzeDramaStory() {
    const raw = dramaInput.trim();
    if (!raw) return;
    setError(null);
    setDramaPhase("analyzing");
    try {
      const isUrl = /^https?:\/\/\S+$/i.test(raw);
      const res = await analyzeDrama(isUrl ? { url: raw, beats: dramaBeats } : { text: raw, beats: dramaBeats });
      setDramaPlan(res.plan);
      setDramaPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "phân tích thất bại");
      setDramaPhase("pick");
    }
  }

  async function createFromDrama() {
    if (!dramaPlan) return;
    setError(null);
    setDramaPhase("building");
    try {
      const board = await buildDrama(dramaPlan, name.trim() || undefined);
      useBoardStore.setState((s) => ({
        boards: [{ id: board.id, name: board.name, created_at: board.created_at, data: board.data }, ...s.boards],
      }));
      await useBoardStore.getState().switchBoard(board.id);
      onCreated(board.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "tạo clip thất bại");
      setDramaPhase("review");
    }
  }

  async function createFromTemplate() {
    if (!template || busy) return;
    setBusy(true);
    setError(null);
    const baseName = name.trim() || (product ? `${product.name} — ${template.title}` : template.title);
    // With a product the backend fills {{product}} from its description; the
    // spoken name is whatever the user left in "Tên gọi trong lời thoại"
    // (prefilled with the product's name), the backend's own fallback when
    // that is blank.
    const sent = { ...inputs };
    if (product) {
      delete sent.product;
      if (!sent.product_name?.trim()) delete sent.product_name;
    }
    if (clipCount <= 1) {
      const id = await createNewBoardFromTemplate(kind, baseName, sent, productId, channelId);
      setBusy(false);
      if (id === null) {
        setError(useBoardStore.getState().error ?? "Không tạo được clip");
        return;
      }
      onCreated(id);
      return;
    }
    const ids: number[] = [];
    // Side by side: with a product each clip waits ~20 s for the agent to
    // write its script, and each gets its own angle (variant n of N).
    const results = await Promise.allSettled(Array.from({ length: clipCount }, (_, n) => {
      const setting = n === 0 ? sent.setting : settingFor(n);
      return createBoardFromTemplate(
        kind, `${baseName} #${n + 1}`, { ...sent, ...(setting ? { setting } : {}) }, productId,
        productId ? { index: n, of: clipCount } : undefined, channelId,
      );
    }));
    for (const r of results) if (r.status === "fulfilled") ids.push(r.value.id);
    const failed = results.find((r): r is PromiseRejectedResult => r.status === "rejected");
    if (failed) {
      const made = ids.length ? ` (đã tạo ${ids.length}/${clipCount} clip)` : "";
      setError((failed.reason instanceof Error ? failed.reason.message : "Không tạo được clip") + made);
    }
    await useBoardStore.getState().refreshBoardList();
    if (ids.length !== clipCount) {
      setBusy(false);
      return;
    }
    // N boards appeared in the library and clip #1 opens; the others wait
    // there. The toast outlives the dialog, so there is no need to hold it
    // open to say so.
    toast.success(`Đã tạo ${ids.length} clip trong "Clip của tôi". Đang mở clip 1, các clip còn lại nằm ở thư viện.`);
    onCreated(ids[0]);
  }

  /** A TikTok / YouTube link: the agent downloads it, then it is the
   * reference video exactly like an uploaded file. */
  async function fetchLink() {
    const url = link.trim();
    if (!url) return;
    setError(null);
    setRefPhase("fetching");
    try {
      const res = await fetchReferenceVideo(url);
      setFile(null);
      setUpload(res);
      setLinkTitle(res.title || url);
      setAnalysis(null);
      setRefPhase("pick");
    } catch (err) {
      setError(err instanceof Error ? err.message : "không tải được link");
      setRefPhase("pick");
    }
  }

  async function analyze() {
    if (!file && !upload) {
      setError("Chọn video quảng cáo mẫu hoặc dán link trước.");
      return;
    }
    setError(null);
    try {
      let up = upload;
      if (!up) {
        setRefPhase("uploading");
        up = await uploadReferenceVideo(file!);
        setUpload(up);
      }
      setRefPhase("analyzing");
      const res = await analyzeReferenceVideo(up.media_id, productId);
      setAnalysis(res.analysis);
      setRefPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "phân tích thất bại");
      setRefPhase("pick");
    }
  }

  async function createFromReference(force: boolean) {
    if (!upload || !analysis) return;
    setError(null);
    setRefPhase("building");
    try {
      const board = await buildFromReferenceVideo({
        mediaId: upload.media_id, productId, analysis, name: name.trim() || undefined, force, character: characterPick,
        channelId,
      });
      useBoardStore.setState((s) => ({
        boards: [{ id: board.id, name: board.name, created_at: board.created_at, data: board.data }, ...s.boards],
      }));
      await useBoardStore.getState().switchBoard(board.id);
      onCreated(board.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "tạo clip thất bại");
      setRefPhase("review");
    }
  }

  const refBase = product?.name ?? shown?.product_seen ?? "Clip";
  // Clothes are judged on a body: no hands-only option for them.
  const pickPersonRequired = (product?.category ?? shown?.category) === "fashion";
  const characterPick: CharacterPick | null = pickGender === "auto" && !pickCountry ? null : {
    gender: pickGender === "auto" ? (shown?.character ? shown.character.gender as "female" | "male" : "none") : pickGender,
    country: pickCountry || shown?.character?.country || "vn",
    hand_look: pickHandLook.trim() || undefined,
  };
  const refNamePlaceholder = isLink ? refBase : `${refBase} — theo video mẫu`;
  // Section 2, first group: the templates in their own order, except that
  // the ones made for the chosen product's category move to the front and
  // get a "phù hợp" tag. The any-category reel keeps its place at the end.
  const fits = (t: BoardTemplate) =>
    product !== null && (t.category as string | undefined) !== ANY_CATEGORY && t.category === product.category;
  const orderedTemplates = [...templates.filter(fits), ...templates.filter((t) => !fits(t))];
  const fitCount = templates.filter(fits).length;

  const review = shown && (
    <>
                <div className={`qt-ref__verdict${shown.blocked ? " qt-ref__verdict--bad" : shown.match.score < 0.75 && productId !== null ? " qt-ref__verdict--warn" : ""}`}>
                  {shown.blocked ? (
                    <><strong>⚠ Không khớp.</strong> {shown.block_reason}</>
                  ) : productId !== null ? (
                    <><strong>✓ Khớp {Math.round(shown.match.score * 100)}%.</strong> {shown.match.reason_vi}</>
                  ) : (
                    <><strong>{isLink ? "Sản phẩm" : "Video quảng cáo"} {shown.category_vi}:</strong> {shown.product_seen}. Bạn sẽ upload ảnh sản phẩm ở bước 1.</>
                  )}
                </div>
                <div className="qt-ref__summary">
                  <div><span>Hook</span><strong>{shown.hook}</strong></div>
                  {shown.style && <div><span>Phong cách</span><strong>{shown.style}{shown.tone ? ` · ${shown.tone}` : ""}</strong></div>}
                  <div><span>Cảnh</span><strong>{shown.plan.length} cảnh × 8 s</strong></div>
                </div>
                <div className="tpl-inputs qt-ref__model">
                  <label className="tpl-inputs__field">
                    <span>Người mẫu</span>
                    <select className="project-modal__input" value={pickGender} disabled={locked}
                            onChange={(e) => setPickGender(e.target.value as typeof pickGender)}>
                      <option value="auto">
                        {shown.character
                          ? `AI gợi ý: ${shown.character.gender === "male" ? "nam" : "nữ"} · ${shown.character.country.toUpperCase()}`
                          : "AI gợi ý: không có người"}
                      </option>
                      {genderAllowed("female") && <option value="female">Nữ</option>}
                      {genderAllowed("male") && <option value="male">Nam</option>}
                      {!pickPersonRequired && genderAllowed("female") && <option value="hands_female">Tay nữ (không lộ mặt)</option>}
                      {!pickPersonRequired && genderAllowed("male") && <option value="hands_male">Tay nam (không lộ mặt)</option>}
                      <option value="none">Không có người (chỉ sản phẩm)</option>
                    </select>
                  </label>
                  {pickGender !== "none" && (
                    <label className="tpl-inputs__field">
                      <span>Quốc gia</span>
                      <select className="project-modal__input" value={pickCountry || shown.character?.country || "vn"} disabled={locked}
                              onChange={(e) => setPickCountry(e.target.value)}>
                        {[["vn", "Việt Nam"], ["kr", "Hàn Quốc"], ["jp", "Nhật Bản"], ["cn", "Trung Quốc"], ["th", "Thái Lan"], ["us", "Mỹ"], ["fr", "Pháp"]].map(([v, l]) => (
                          <option key={v} value={v}>{l}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  {pickGender.startsWith("hands_") && (
                    <label className="tpl-inputs__field qt-field--wide">
                      <span>Mô tả bàn tay (tiếng Anh, tuỳ chọn)</span>
                      <input className="project-modal__input" type="text" maxLength={200} value={pickHandLook} disabled={locked}
                             placeholder="để trống = tay đẹp, da mịn, móng sạch. Ví dụ: chubby hands"
                             onChange={(e) => setPickHandLook(e.target.value)} />
                    </label>
                  )}
                  {pickPersonRequired && (
                    <p className="qt-new__hint qt-field--wide">Sản phẩm thời trang cần người mẫu mặc, nên không có lựa chọn chỉ quay bàn tay.</p>
                  )}
                </div>
                <ol className="qt-ref__plan">
                  {shown.plan.map((p, i) => (
                    <li key={i}>
                      <div className="qt-ref__plan-title">{i + 1}. {p.title_vi}</div>
                      <div className="qt-ref__plan-line">🎙 {p.narration_vi}</div>
                      <div className="qt-ref__plan-prompt">{p.image_prompt_en}</div>
                    </li>
                  ))}
                </ol>
                {isLink && (
                  <p className="qt-new__hint">Kiểm tra lại thông số kỹ thuật — AI có thể đoán sai.</p>
                )}
                <label className="tpl-inputs__field">
                  <span>Tên clip</span>
                  <input className="project-modal__input" type="text" maxLength={80} value={name}
                         placeholder={refNamePlaceholder} onChange={(e) => setName(e.target.value)} disabled={locked} />
                </label>
              </>
  );

  return (
    <div className="project-modal-backdrop" role="presentation" onClick={(e) => { if (e.target === e.currentTarget && !locked) onClose(); }}>
      <div className="project-modal project-modal--wide qt-new" role="dialog" aria-modal="true" aria-labelledby="qt-new-title">
        <h2 id="qt-new-title" className="project-modal__title">Clip mới</h2>

        <div className="qt-new__section">
          <div className="qt-new__label">1 · Sản phẩm (tuỳ chọn){analysisLocked ? " · đã khoá vì đã phân tích" : ""}
            {analysisLocked && phase !== "review" && !locked && (
              <button type="button" className="qt-btn" style={{ marginLeft: 8 }}
                      onClick={() => { setAnalysis(null); setRefPhase("pick"); setLinkAnalysis(null); setLinkPhase("pick"); }}>
                Bỏ kết quả phân tích
              </button>
            )}
          </div>
          <div className="qt-new__products">
            <button
              type="button"
              className={`qt-new__product${productId === null ? " qt-new__product--active" : ""}`}
              onClick={() => pickProduct(null)}
              disabled={pickLocked}
            >
              <span className="qt-new__product-thumb qt-new__product-thumb--empty">—</span>
              <span>Không chọn, tự upload ảnh sau</span>
            </button>
            {products.length === 0 && (
              <p className="qt-new__hint">
                Chưa có sản phẩm nào. Dán link để thêm ngay, hoặc thêm ở <Link to="/products">Sản phẩm đang bán</Link>.
              </p>
            )}
            {products.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`qt-new__product${productId === p.id ? " qt-new__product--active" : ""}`}
                onClick={() => pickProduct(p)}
                disabled={pickLocked}
              >
                {p.media_ids[0] ? (
                  <img className="qt-new__product-thumb" src={mediaUrl(p.media_ids[0])} alt="" />
                ) : (
                  <span className="qt-new__product-thumb qt-new__product-thumb--empty">?</span>
                )}
                <span>
                  {p.name}
                  {/* The second line is "category · price"; the dot only sits between two parts. */}
                  {(p.price || CATEGORY_LABEL[p.category]) && (
                    <small>{[CATEGORY_LABEL[p.category], p.price].filter(Boolean).join(" · ")}</small>
                  )}
                </span>
              </button>
            ))}
            <button type="button" className="qt-new__product qt-new__product--add" onClick={() => setAddLinkOpen((v) => !v)}
                    disabled={pickLocked || addingProduct} title="Dán link TikTok Shop / Shopee… để lưu sản phẩm mới và dùng luôn">
              <span className="qt-new__product-thumb qt-new__product-thumb--empty">🔗</span>
              <span>Thêm sản phẩm từ link</span>
            </button>
          </div>
          {addLinkOpen && (
            <div className="qt-ref__link qt-new__addlink">
              <input className="project-modal__input" type="url" autoFocus value={addLink} disabled={addingProduct}
                     placeholder="Dán link sản phẩm: TikTok Shop / Shopee / Lazada / web shop…"
                     onChange={(e) => setAddLink(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") void addProductFromLink(); }} />
              <button type="button" className="qt-btn qt-btn--accent" onClick={() => void addProductFromLink()} disabled={addingProduct || !addLink.trim()}>
                {addingProduct ? "AI đang đọc…" : "Lưu & chọn"}
              </button>
            </div>
          )}
        </div>

        <div className="qt-new__section qt-new__channel">
          <ChannelPicker value={channelId} onChange={setChannelId} disabled={locked} label="Kênh đăng clip"
                         hint={<small className="qt-card__hint">Clip gắn kênh thì bài đăng ở Bước 5 viết theo định hướng kênh; đổi được ở Bước 1.</small>} />
        </div>

        <div className="qt-new__section">
          <div className="qt-new__label">2 · Kiểu clip</div>
          <div className="qt-new__group">
            <p className="qt-new__group-title">
              Theo ngành hàng
              {product && fitCount > 0 && (
                <small> · {fitCount} kiểu phù hợp với {CATEGORY_LABEL[product.category] ?? "sản phẩm này"} xếp trước</small>
              )}
            </p>
            <div className="tpl-grid" role="radiogroup" aria-label="Theo ngành hàng">
              {orderedTemplates.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`tpl-card${kind === t.id ? " tpl-card--active" : ""}${fits(t) ? " tpl-card--fit" : ""}`}
                  onClick={() => setKind(t.id)}
                  disabled={locked}
                  role="radio"
                  aria-checked={kind === t.id}
                >
                  <span className="tpl-card__title">
                    {t.title}
                    {fits(t) && <span className="tpl-card__fit" title="Kiểu clip dành cho ngành hàng của sản phẩm đã chọn">phù hợp</span>}
                  </span>
                  <span className="tpl-card__blurb">{t.blurb}</span>
                  <span className="tpl-card__meta">{t.scenes} cảnh · {t.scenes} video</span>
                </button>
              ))}
            </div>
          </div>
          <div className="qt-new__group">
            <p className="qt-new__group-title">Từ nguồn có sẵn</p>
            <div className="tpl-grid" role="radiogroup" aria-label="Từ nguồn có sẵn">
              <button
                type="button"
                className={`tpl-card tpl-card--reference${isReference ? " tpl-card--active" : ""}`}
                onClick={() => setKind(REFERENCE_KIND)}
                disabled={locked}
                role="radio"
                aria-checked={isReference}
              >
                <span className="tpl-card__title">🎞️ Theo video mẫu</span>
                <span className="tpl-card__blurb">
                  Bỏ một video quảng cáo có sẵn vào, AI xem và viết lại kịch bản theo đúng nhịp đó cho sản phẩm của bạn.
                </span>
                <span className="tpl-card__meta">Gemini · 2–6 cảnh</span>
              </button>
              <button
                type="button"
                className={`tpl-card tpl-card--reference${isLink ? " tpl-card--active" : ""}`}
                onClick={() => setKind(PRODUCT_LINK_KIND)}
                disabled={locked}
                role="radio"
                aria-checked={isLink}
              >
                <span className="tpl-card__title">🔗 Theo link sản phẩm</span>
                <span className="tpl-card__blurb">
                  Dán link trang sản phẩm (Shopee, Lazada, TikTok Shop, web shop…), AI đọc thông tin và viết kịch bản quảng cáo, không cần video mẫu.
                </span>
                <span className="tpl-card__meta">Gemini · 3–5 cảnh</span>
              </button>
              {DRAMA_ENABLED && (
                <button
                  type="button"
                  className={`tpl-card tpl-card--reference${isDrama ? " tpl-card--active" : ""}`}
                  onClick={() => setKind(DRAMA_KIND)}
                  disabled={locked}
                  role="radio"
                  aria-checked={isDrama}
                >
                  <span className="tpl-card__title">📰 Tạo drama</span>
                  <span className="tpl-card__blurb">
                    Dán link bài viết hoặc gõ câu chuyện, AI tóm tắt thành các đoạn: mỗi đoạn một ảnh minh hoạ + lời kể + tiêu đề, ảnh chuyển cảnh nối nhau. Chèn thêm video phỏng vấn nếu có.
                  </span>
                  <span className="tpl-card__meta">Gemini · 4–12 đoạn · không cần sản phẩm</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {isDrama && (
          <div className="qt-new__section">
            <div className="qt-new__label">3 · Câu chuyện</div>
            {dramaPhase !== "review" && dramaPhase !== "building" ? (
              <>
                <textarea
                  className="qt-textarea"
                  rows={5}
                  value={dramaInput}
                  placeholder={"Dán link bài viết (báo, Facebook, blog…) HOẶC gõ / dán nội dung câu chuyện vào đây."}
                  onChange={(e) => setDramaInput(e.target.value)}
                  disabled={locked}
                />
                <div className="qt-row">
                  <label className="qt-field">
                    <span>Số đoạn (mỗi đoạn một ảnh)</span>
                    <select value={dramaBeats} onChange={(e) => setDramaBeats(Number(e.target.value))} disabled={locked}>
                      {DRAMA_BEAT_CHOICES.map((n) => <option key={n} value={n}>{n} đoạn · ~{n * 8} s</option>)}
                    </select>
                  </label>
                </div>
                <div className="qt-card__hint">
                  AI giữ đúng nội dung nguồn, gắn "theo bài viết" cho các cáo buộc, ảnh minh hoạ không lấy mặt người thật.
                  Trang bắt đăng nhập (Facebook riêng tư) thì dán nội dung thay vì link.
                </div>
              </>
            ) : dramaPlan && (
              <>
                <div className="qt-ref__summary">
                  <div><span>Tiêu đề</span><strong>{dramaPlan.title_vi}</strong></div>
                  <div><span>Hook</span><strong>{dramaPlan.hook_vi}</strong></div>
                  {dramaPlan.tone && <div><span>Giọng kể</span><strong>{dramaPlan.tone}</strong></div>}
                  <div><span>Đoạn</span><strong>{dramaPlan.beats.length} ảnh · ~{dramaPlan.beats.length * 8} s</strong></div>
                </div>
                {dramaPlan.summary_vi && <div className="qt-card__hint">{dramaPlan.summary_vi}</div>}
                <ol className="qt-ref__plan">
                  {dramaPlan.beats.map((b, i) => (
                    <li key={i}>
                      <div className="qt-ref__plan-title">{i + 1}. {b.title_vi} <small>· {b.caption_vi}</small></div>
                      <div className="qt-ref__plan-line">🎙 {b.narration_vi}</div>
                      <div className="qt-ref__plan-prompt">{b.image_prompt_en}</div>
                    </li>
                  ))}
                </ol>
                <label className="tpl-inputs__field">
                  <span>Tên clip</span>
                  <input className="project-modal__input" type="text" maxLength={80} value={name}
                         placeholder={`Drama — ${dramaPlan.title_vi}`} onChange={(e) => setName(e.target.value)} disabled={locked} />
                </label>
              </>
            )}
          </div>
        )}

        {template && !isReference && !isLink && !isDrama && (
          <div className="qt-new__section">
            <div className="qt-new__label">3 · Thiết lập</div>
            <div className="tpl-inputs">
              {template.inputs
                // "Sản phẩm" is the list of products being sold (same choice
                // as step 1); the spoken name stays editable.
                .map((i) => i.key === "product" ? (
                  <label key={i.key} className="tpl-inputs__field">
                    <span>Sản phẩm đang bán</span>
                    <select className="project-modal__input" value={productId ?? ""} disabled={pickLocked || products.length === 0}
                            onChange={(e) => pickProduct(products.find((p) => p.id === Number(e.target.value)) ?? null)}>
                      <option value="">{products.length ? "— Không chọn (upload ảnh ở bước 1) —" : "Chưa có sản phẩm"}</option>
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>{p.name}{p.price ? ` · ${p.price}` : ""}</option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label key={i.key} className="tpl-inputs__field">
                    <span>{i.label}</span>
                    {i.type === "select" ? (
                      <>
                        <select className="project-modal__input" value={inputs[i.key] ?? i.default ?? ""}
                                onChange={(e) => setInputs((p) => ({ ...p, [i.key]: e.target.value }))} disabled={locked}>
                          {(i.options ?? [])
                            // A men's / women's product: only models of that gender (hands too).
                            .filter(([v]) => i.key !== "charGender" || genderAllowed(v))
                            .map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                        </select>
                        {i.key === "charGender" && product && (product.gender === "male" || product.gender === "female") && (
                          <small className="qt-new__hint">Sản phẩm dành cho {product.gender === "male" ? "nam" : "nữ"} — chỉ chọn được người mẫu {product.gender === "male" ? "nam" : "nữ"}.</small>
                        )}
                      </>
                    ) : i.key === "setting" ? (
                      <SuggestField
                        value={inputs[i.key] ?? ""}
                        placeholder={i.placeholder ?? i.default ?? ""}
                        onChange={(v) => setInputs((p) => ({ ...p, [i.key]: v }))}
                        disabled={locked}
                        // Backdrops that suit the chosen product, else the clip kind.
                        groups={backdropGroups((product?.category as string | undefined) ?? (template.category as string | undefined))}
                      />
                    ) : (
                      <input className="project-modal__input" type="text" maxLength={200}
                             value={inputs[i.key] ?? ""} placeholder={i.placeholder ?? i.default ?? ""}
                             onChange={(e) => setInputs((p) => ({ ...p, [i.key]: e.target.value }))} disabled={locked} />
                    )}
                  </label>
                ))}
              {template.person_required && (
                <p className="qt-new__hint qt-field--wide">
                  {PERSON_REASON[template.id] ?? `${template.title} cần có người mẫu, nên không có lựa chọn chỉ quay bàn tay.`}
                </p>
              )}
              {(inputs.charGender ?? "").startsWith("hands_") && !template.person_required && (
                <label className="tpl-inputs__field qt-field--wide">
                  <span>Mô tả bàn tay (tiếng Anh, tuỳ chọn)</span>
                  <input className="project-modal__input" type="text" maxLength={200}
                         value={inputs.handLook ?? ""}
                         placeholder="để trống = tay đẹp, da mịn, móng sạch. Ví dụ: chubby hands"
                         onChange={(e) => setInputs((p) => ({ ...p, handLook: e.target.value }))} disabled={locked} />
                </label>
              )}
              <label className="tpl-inputs__field">
                <span>Tên clip</span>
                <input className="project-modal__input" type="text" maxLength={80} value={name}
                       placeholder={product ? `${product.name} — ${template.title}` : template.title}
                       onChange={(e) => setName(e.target.value)} disabled={locked}
                       onKeyDown={(e) => { if (e.key === "Enter") createFromTemplate(); }} />
              </label>
              <label className="tpl-inputs__field">
                <span>Số clip (mỗi clip một bối cảnh)</span>
                <select className="project-modal__input" value={clipCount} disabled={locked}
                        onChange={(e) => setClipCount(Number(e.target.value))}>
                  {Array.from({ length: MAX_CLIPS }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>{n === 1 ? "1 clip" : `${n} clip từ cùng sản phẩm`}</option>
                  ))}
                </select>
              </label>
            </div>
            {clipCount > 1 && (
              <div className="tpl-inputs" style={{ marginTop: 8 }}>
                <div className="qt-card__hint" style={{ gridColumn: "1 / -1" }}>
                  Clip 1 dùng ô "Bối cảnh" ở trên. Các clip sau dùng bối cảnh dưới đây (sửa được). Mỗi clip là một dự án
                  riêng trong "Clip của tôi", bạn chạy "Tạo video tự động" cho từng clip.
                </div>
                {Array.from({ length: clipCount - 1 }, (_, i) => i + 1).map((n) => (
                  <label key={n} className="tpl-inputs__field">
                    <span>Bối cảnh clip {n + 1}</span>
                    <input className="project-modal__input" type="text" maxLength={200} value={settingFor(n)}
                           onChange={(e) => setExtraSettings((p) => { const next = [...p]; next[n - 1] = e.target.value; return next; })}
                           disabled={locked} />
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {isReference && (
          <div className="qt-new__section">
            <div className="qt-new__label">3 · Video quảng cáo mẫu</div>
            {refPhase !== "review" && refPhase !== "building" ? (
              <>
                <div className="qt-ref__link">
                  <input
                    className="project-modal__input"
                    type="url"
                    placeholder="Dán link TikTok / YouTube / Instagram / Facebook…"
                    value={link}
                    onChange={(e) => setLink(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") fetchLink(); }}
                    disabled={locked}
                  />
                  <button type="button" className="qt-btn" onClick={fetchLink} disabled={locked || !link.trim()}>
                    {refPhase === "fetching" ? "Đang tải…" : "Tải từ link"}
                  </button>
                </div>
                <div className="qt-ref__or">hoặc</div>
                <div className="qt-ref__drop" onClick={() => !locked && fileRef.current?.click()}>
                  {file ? (
                    <>
                      <video className="qt-ref__preview" src={URL.createObjectURL(file)} controls muted playsInline />
                      <div className="qt-ref__meta">{file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB · bấm để đổi</div>
                    </>
                  ) : upload ? (
                    <>
                      <video className="qt-ref__preview" src={mediaUrl(upload.media_id)} controls muted playsInline />
                      <div className="qt-ref__meta">
                        {linkTitle || "video từ link"} · {(upload.size / 1024 / 1024).toFixed(1)} MB
                        {upload.duration_s ? ` · ${Math.round(upload.duration_s)} s` : ""} · bấm để chọn file khác
                      </div>
                    </>
                  ) : (
                    <div className="qt-ref__placeholder">+ Chọn video từ máy (mp4 / mov / webm, ≤ 200 MB, nên dưới 90 giây)</div>
                  )}
                </div>
                <input ref={fileRef} type="file" accept="video/mp4,video/quicktime,video/webm" hidden
                       onChange={(e) => { setFile(e.target.files?.[0] ?? null); setUpload(null); setLinkTitle(""); setAnalysis(null); }} />
                <div className="qt-card__hint">
                  Video mẫu chỉ dùng để phân tích, không upload lên Flow. AI kiểm tra sản phẩm ở mục 1 có cùng loại với
                  video không — video đồ ăn mà chọn áo thì sẽ báo không khớp.
                </div>
              </>
            ) : review}
          </div>
        )}

        {isLink && (
          <div className="qt-new__section">
            <div className="qt-new__label">3 · Link sản phẩm</div>
            {linkPhase !== "review" && linkPhase !== "building" ? (
              <>
                <div className="qt-ref__link">
                  <input
                    className="project-modal__input"
                    type="url"
                    placeholder="Dán link sản phẩm: Shopee / Lazada / TikTok Shop / web shop…"
                    value={productUrl}
                    onChange={(e) => setProductUrl(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") analyzeLink(); }}
                    disabled={locked}
                  />
                </div>
                <div className="qt-card__hint">
                  AI đọc nội dung trang (tên, mô tả, giá, điểm nổi bật) rồi viết kịch bản. Trang bắt đăng nhập hoặc chặn bot
                  thì không đọc được — khi đó hãy tạo sản phẩm trong thư viện và dán mô tả vào. Nếu chọn sản phẩm ở mục 1,
                  AI kiểm tra nó có cùng loại với trang không.
                </div>
              </>
            ) : review}
          </div>
        )}

        <div className="project-modal__actions">
          {isDrama && (dramaPhase === "review" || dramaPhase === "building") ? (
            <>
              <button type="button" className="project-modal__btn" onClick={() => setDramaPhase("pick")} disabled={locked}>← Sửa câu chuyện</button>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={createFromDrama} disabled={locked}>
                {dramaPhase === "building" ? "Đang tạo…" : "Tạo clip →"}
              </button>
            </>
          ) : isDrama ? (
            <>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={analyzeDramaStory} disabled={locked || !dramaInput.trim()}>
                {dramaPhase === "analyzing" ? `AI đang viết kịch bản… ${elapsed} s` : "Phân tích →"}
              </button>
            </>
          ) : (isReference || isLink) && (phase === "review" || phase === "building") ? (
            <>
              <button type="button" className="project-modal__btn" onClick={() => (isLink ? setLinkPhase("pick") : setRefPhase("pick"))} disabled={locked}>{isLink ? "← Đổi link" : "← Đổi video"}</button>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              {shown?.blocked ? (
                <button type="button" className="project-modal__btn qt-btn--danger" onClick={() => (isLink ? createFromLink(true) : createFromReference(true))} disabled={locked}>
                  {phase === "building" ? "Đang tạo…" : "Vẫn tạo (tự chịu)"}
                </button>
              ) : (
                <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={() => (isLink ? createFromLink(false) : createFromReference(false))} disabled={locked}>
                  {phase === "building" ? "Đang tạo…" : "Tạo clip →"}
                </button>
              )}
            </>
          ) : isLink ? (
            <>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={analyzeLink} disabled={locked || !productUrl.trim()}>
                {linkPhase === "analyzing" ? `AI đang đọc trang… ${elapsed} s` : "Phân tích →"}
              </button>
            </>
          ) : isReference ? (
            <>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={analyze} disabled={locked || (!file && !upload)}>
                {refPhase === "uploading" ? "Đang tải video…" : refPhase === "analyzing" ? `AI đang xem video… ${elapsed} s` : "Phân tích →"}
              </button>
            </>
          ) : (
            <>
              <button type="button" className="project-modal__btn" onClick={onClose} disabled={locked}>Huỷ</button>
              <button type="button" className="project-modal__btn project-modal__btn--primary qt-btn--accent" onClick={createFromTemplate} disabled={locked || !template}>
                {busy ? (productId ? "AI đang viết kịch bản theo sản phẩm…" : "Đang tạo…") : clipCount > 1 ? `Tạo ${clipCount} clip →` : "Tạo clip →"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
