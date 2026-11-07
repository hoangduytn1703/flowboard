import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getTemplates, listProducts, type BoardTemplate, type Product } from "../../api/client";
import { getPostOptions, type PostOptions } from "../../api/posts";
import { HOOK_TYPE_LABEL, adaptSwipe, analyzeSwipe, deleteSwipe, listSwipes, type Swipe } from "../../api/swipes";
import { toast } from "../../store/toast";
import { ChannelPicker } from "../channels/ChannelPicker";
import { PageEmpty, PageLoading } from "../PageState";
import "../swipes.css";
import { askConfirm } from "../../components/Dialogs";

const PLATFORM_ICON: Record<string, string> = { tiktok: "🎵", douyin: "🎵", youtube: "▶️", instagram: "📸", facebook: "📘", threads: "🧵", x: "𝕏", zalo: "💬", text: "📝" };

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" }) : "";
}

/**
 * "🔥 Mẫu đang hot": paste a link (post or video) or the text of something
 * that did well; the AI explains why it worked (hook, beats, triggers) and
 * writes the seller's own post or clip for a product on that structure.
 */
export function SwipesPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Swipe[] | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [q, setQ] = useState("");

  useEffect(() => {
    document.title = "Mẫu đang hot · DFlow";
    void listSwipes().then((rows) => { setItems(rows); setOpenId(rows[0]?.id ?? null); }).catch((e) => { setItems([]); toast.error(`Không tải được: ${e instanceof Error ? e.message : e}`); });
  }, []);
  useEffect(() => {
    if (!busy) return;
    const t0 = Date.now();
    const t = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, [busy]);

  const open = useMemo(() => items?.find((s) => s.id === openId) ?? null, [items, openId]);
  const isLink = /^https?:\/\/\S+/i.test(input.trim()) || /https?:\/\/\S+/.test(input) && input.trim().length < 400;
  const shown = (items ?? []).filter((s) => !q.trim() || `${s.title} ${s.tags.join(" ")} ${s.analysis?.summary ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()));

  async function analyze() {
    const text = input.trim();
    if (!text) return;
    setBusy(true);
    try {
      const row = await analyzeSwipe(isLink ? { url: text } : { text });
      setItems((list) => [row, ...(list ?? [])]);
      setOpenId(row.id);
      setInput("");
      toast.success(`Đã phân tích "${row.title}".`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function remove(s: Swipe) {
    if (!await askConfirm(`Xoá mẫu "${s.title}"? (bài / clip đã viết từ mẫu vẫn còn)`)) return;
    try {
      await deleteSwipe(s.id);
      setItems((list) => (list ?? []).filter((x) => x.id !== s.id));
      if (openId === s.id) setOpenId(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }

  if (items === null) return <PageLoading text="Đang mở kho mẫu…" />;

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Mẫu đang hot</span>
      </header>
      <div className="qt-home qt-swipes">
        <section className="qt-card">
          <div className="qt-card__head">
            <div>
              <div className="qt-card__eyebrow">Kho mẫu viral</div>
              <h2 className="qt-card__title">🔥 Thấy bài / video nào đang hot, dán vào đây</h2>
            </div>
          </div>
          <p className="qt-card__hint">
            Dán <strong>link</strong> (bài Facebook / Threads — đọc qua Chrome của bạn; video TikTok / Douyin / YouTube / Reels — AI xem video)
            hoặc dán thẳng <strong>nội dung bài</strong>. AI chỉ ra vì sao nó chạy (câu mở đầu, các bước, cảm xúc chạm vào), rồi viết bản của bạn
            cho sản phẩm — theo cấu trúc, không chép chữ.
          </p>
          <div className="qt-swipes__input">
            <textarea className="qt-textarea" rows={3} value={input} onChange={(e) => setInput(e.target.value)} disabled={busy}
                      placeholder="https://www.tiktok.com/@…/video/…  hoặc  https://www.facebook.com/…/posts/…  hoặc dán nguyên bài viết" />
            <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={busy || !input.trim()} onClick={() => void analyze()}>
              {busy ? `AI đang phân tích… ${elapsed}s` : isLink ? "🔍 Đọc & phân tích link" : "🔍 Phân tích bài này"}
            </button>
          </div>
          {busy && <small className="qt-card__hint">Bài chữ ~10 s; video phải tải về rồi AI xem, 30–90 s.</small>}
        </section>

        {items.length === 0 ? (
          <PageEmpty icon="🔥" title="Kho mẫu còn trống">
            Lướt TikTok / Facebook thấy bài nào nhiều tương tác thì dán link vào ô trên. Mỗi mẫu đã phân tích dùng lại được cho nhiều sản phẩm.
          </PageEmpty>
        ) : (
          <div className="qt-swipes__grid">
            <aside className="qt-card qt-swipes__list">
              <div className="qt-card__head">
                <h3 className="qt-card__title">Đã lưu · {items.length}</h3>
              </div>
              <input type="search" className="qt-plib-page__search qt-swipes__search" placeholder="tìm theo tên, nhãn…" value={q} onChange={(e) => setQ(e.target.value)} />
              <ul>
                {shown.map((s) => (
                  <li key={s.id}>
                    <button type="button" className={`qt-swipes__item${s.id === openId ? " is-open" : ""}`} onClick={() => setOpenId(s.id)}>
                      <span className="qt-swipes__plat">{PLATFORM_ICON[s.platform] ?? "🔗"}</span>
                      <span className="qt-swipes__itemtext">
                        <strong>{s.title || "(không tên)"}</strong>
                        <small>{HOOK_TYPE_LABEL[s.analysis?.hook_type ?? ""] ?? s.analysis?.hook_type ?? ""}{s.tags.length ? ` · ${s.tags.slice(0, 3).join(", ")}` : ""} · {when(s.created_at)}{s.uses ? ` · dùng ${s.uses}` : ""}</small>
                      </span>
                    </button>
                  </li>
                ))}
                {shown.length === 0 && <li className="qt-card__hint">Không có mẫu nào khớp.</li>}
              </ul>
            </aside>
            {open && <SwipeDetail swipe={open} onDelete={() => void remove(open)} onOpenPost={(id) => navigate(`/posts?post=${id}`)} onOpenClip={(id) => navigate(`/clips/${id}/script`)} />}
          </div>
        )}
      </div>
    </>
  );
}

function SwipeDetail({ swipe, onDelete, onOpenPost, onOpenClip }: {
  swipe: Swipe; onDelete: () => void; onOpenPost: (id: number) => void; onOpenClip: (id: number) => void;
}) {
  const a = swipe.analysis;
  const [channelId, setChannelId] = useState<number | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState<number | null>(null);
  const [options, setOptions] = useState<PostOptions | null>(null);
  const [kind, setKind] = useState("story");
  const [templates, setTemplates] = useState<BoardTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [wish, setWish] = useState("");
  const [busy, setBusy] = useState<"" | "post" | "clip">("");
  const [showSource, setShowSource] = useState(false);

  useEffect(() => {
    void listProducts().then(setProducts).catch(() => undefined);
    void getPostOptions().then(setOptions).catch(() => undefined);
    void getTemplates().then((t) => setTemplates(t.filter((x) => x.id !== "drama"))).catch(() => undefined);
  }, []);
  const product = products.find((p) => p.id === productId) ?? null;
  useEffect(() => { if (product?.template_id) setTemplateId(product.template_id); }, [product?.template_id]);

  async function adapt(as: "post" | "clip") {
    if (!channelId) { toast.warning("Chọn kênh / page trước."); return; }
    if (as === "clip" && !productId) { toast.warning("Tạo clip theo mẫu cần chọn sản phẩm."); return; }
    setBusy(as);
    try {
      const out = await adaptSwipe(swipe.id, { as, channel_id: channelId, product_id: productId, kind, template_id: templateId || null, wish: wish.trim() || undefined });
      if (out.as === "post") {
        toast.success(`Đã viết bài "${out.title}" theo mẫu — đang mở.`, { duration: 6000 });
        onOpenPost(out.post_id);
      } else {
        toast.success(`Đã tạo clip "${out.name}"${out.tailored ? " với kịch bản theo mẫu" : " (kịch bản mẫu, AI chưa viết riêng được)"} — đang mở Bước 2.`, { duration: 7000 });
        onOpenClip(out.board_id);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="qt-channels__detail">
      <section className="qt-card">
        <div className="qt-card__head">
          <div>
            <h3 className="qt-card__title">{PLATFORM_ICON[swipe.platform] ?? "🔗"} {swipe.title}</h3>
            <small className="qt-card__hint">
              {swipe.kind === "video" ? "Video" : "Bài viết"} · {swipe.platform}{swipe.url && <> · <a href={swipe.url} target="_blank" rel="noreferrer">mở gốc ↗</a></>}
              {swipe.uses ? ` · đã dùng ${swipe.uses} lần` : ""}
            </small>
          </div>
          <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={onDelete}>🗑 Xoá</button>
        </div>
        {a ? (
          <div className="qt-swipes__analysis">
            <p className="qt-swipes__summary">{a.summary}</p>
            <div className="qt-swipes__hook">
              <span className="qt-swipes__badge">Câu mở đầu · {HOOK_TYPE_LABEL[a.hook_type] ?? a.hook_type}</span>
              <q>{a.hook}</q>
            </div>
            <div className="qt-swipes__cols">
              <div>
                <h4>🪜 Các bước</h4>
                <ol>{a.structure.map((s, i) => <li key={i}>{s.replace(/^Bước \d+:\s*/i, "")}</li>)}</ol>
              </div>
              <div>
                <h4>💡 Vì sao chạy</h4>
                <ul>{a.why_it_works.map((s, i) => <li key={i}>{s}</li>)}</ul>
                {a.triggers.length > 0 && <p className="qt-swipes__meta"><strong>Chạm vào:</strong> {a.triggers.join(", ")}</p>}
                <p className="qt-swipes__meta"><strong>Định dạng:</strong> {a.format || "—"} · <strong>Kêu gọi:</strong> {a.cta || "không"}</p>
              </div>
            </div>
            {a.skeleton && (
              <details className="qt-swipes__skeleton">
                <summary>📐 Khung mẫu để tự viết (có chỗ trống [ ])</summary>
                <pre>{a.skeleton}</pre>
              </details>
            )}
            {a.tags.length > 0 && <div className="qt-swipes__tags">{a.tags.map((t) => <span key={t} className="qt-plib__tag">{t}</span>)}</div>}
            <button type="button" className="qt-link" onClick={() => setShowSource((v) => !v)}>{showSource ? "ẩn nội dung gốc" : "xem nội dung gốc đã đọc"}</button>
            {showSource && <pre className="qt-swipes__source">{swipe.text}</pre>}
          </div>
        ) : <p className="qt-card__hint">Mẫu này chưa có phân tích.</p>}
      </section>

      <section className="qt-card qt-swipes__adapt">
        <div className="qt-card__head"><h3 className="qt-card__title">✍️ Viết bản của mình theo mẫu này</h3></div>
        <p className="qt-card__hint">AI giữ cấu trúc và kiểu câu mở đầu, thay bằng sản phẩm và giọng của kênh bạn — không chép câu chữ của bài gốc.</p>
        <ChannelPicker value={channelId} onChange={setChannelId} required label="Kênh / page" />
        <label className="qt-field">
          <span>Sản phẩm <small>(bài: không bắt buộc · clip: bắt buộc)</small></span>
          <select value={productId ?? ""} onChange={(e) => setProductId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">— Không gắn sản phẩm —</option>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name}{p.aff_link ? " · 🔗 aff" : ""}</option>)}
          </select>
        </label>
        <div className="qt-posts__row">
          <label className="qt-field">
            <span>Kiểu bài</span>
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {(options?.kinds ?? [{ key: "story", label: "Kể chuyện trải nghiệm" }]).filter((k) => k.key !== "serial").map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
            </select>
          </label>
          <label className="qt-field">
            <span>Kiểu clip <small>(cho nút tạo clip)</small></span>
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              <option value="">Theo ngành sản phẩm</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          </label>
        </div>
        <label className="qt-field">
          <span>Muốn nhấn gì thêm <small>(không bắt buộc)</small></span>
          <input value={wish} maxLength={500} onChange={(e) => setWish(e.target.value)} placeholder="VD: nhắc đang freeship, viết cho mẹ bầu tháng cuối" />
        </label>
        <div className="qt-post__actions">
          <button type="button" className="qt-btn qt-btn--accent" disabled={!!busy || !channelId} onClick={() => void adapt("post")}>
            {busy === "post" ? "AI đang viết…" : "✍️ Viết bài theo mẫu"}
          </button>
          <button type="button" className="qt-btn" disabled={!!busy || !channelId || !productId} onClick={() => void adapt("clip")}
                  title={productId ? "Tạo clip (kịch bản viết theo các bước của mẫu); tạo ảnh/video sau" : "Chọn sản phẩm trước"}>
            {busy === "clip" ? "AI đang viết kịch bản…" : "🎬 Tạo clip theo mẫu"}
          </button>
        </div>
      </section>
    </div>
  );
}
