import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getTemplates, type BoardTemplate, type Product } from "../../api/client";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import { ChannelPicker } from "../channels/ChannelPicker";
import { ScheduleDialog, type ScheduleTarget } from "../schedule/ScheduleDialog";
import "../schedule.css";

interface BundleResult {
  product: { id: number; name: string };
  channel_id: number;
  clip: { id: number; name: string; template_id: string; tailored: boolean } | null;
  post: { id: number; title: string; body: string; first_comment: string; kind: string } | null;
  tiktok: { id: number; title: string; body: string; hashtags: string } | null;
  errors: Record<string, string>;
}

let kindsCache: { key: string; label: string }[] | null = null;

/**
 * "🎁 Gói nội dung" for one product: on one channel, in one go — a clip
 * board with the script written for the product, a Facebook post to go
 * with it (affiliate link in the first comment) and a short TikTok caption.
 * The clip's images / videos are rendered afterwards in the wizard (credits).
 */
export function BundleDialog({ product, channelId: initialChannel = null, onClose }: {
  product: Product;
  channelId?: number | null;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [channelId, setChannelId] = useState<number | null>(initialChannel);
  const [templates, setTemplates] = useState<BoardTemplate[]>([]);
  const [templateId, setTemplateId] = useState(product.template_id ?? "");
  const [kinds, setKinds] = useState(kindsCache ?? []);
  const [postKind, setPostKind] = useState("review");
  const [withClip, setWithClip] = useState(true);
  const [withPost, setWithPost] = useState(true);
  const [withTiktok, setWithTiktok] = useState(true);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<BundleResult | null>(null);
  const [schedule, setSchedule] = useState<ScheduleTarget | null>(null);

  useEffect(() => {
    void getTemplates().then((t) => setTemplates(t.filter((x) => x.id !== "drama"))).catch(() => undefined);
    if (!kindsCache) {
      void api<{ post_kinds: { key: string; label: string }[] }>("/api/bundles/options").then((o) => { kindsCache = o.post_kinds; setKinds(o.post_kinds); }).catch(() => undefined);
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);
  useEffect(() => {
    if (!busy) return;
    const t0 = Date.now();
    const t = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, [busy]);

  const fitting = templates.filter((t) => !t.category || t.category === "any" || t.category === product.category);
  const others = templates.filter((t) => !fitting.includes(t));

  async function run() {
    if (!channelId) { toast.warning("Chọn kênh / page cho gói nội dung."); return; }
    setBusy(true);
    setResult(null);
    try {
      const out = await api<BundleResult>("/api/bundles", {
        method: "POST",
        body: JSON.stringify({ product_id: product.id, channel_id: channelId, template_id: templateId || null, post_kind: postKind,
                               with_clip: withClip, with_post: withPost, with_tiktok: withTiktok }),
      });
      setResult(out);
      const n = [out.clip, out.post, out.tiktok].filter(Boolean).length;
      const bad = Object.keys(out.errors).length;
      if (bad) toast.warning(`Xong ${n} phần, ${bad} phần lỗi — xem bên dưới.`);
      else toast.success(`Gói nội dung "${product.name}" đã sẵn sàng (${n} phần).`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="project-modal-backdrop" onClick={() => { if (!busy) onClose(); }}>
      <div className="project-modal project-modal--wide qt-bundle" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3 className="qt-card__title">🎁 Gói nội dung · {product.name}</h3>
        {!result ? (
          <>
            <p className="qt-card__hint">Một lần bấm ra trọn bộ cho sản phẩm này, cùng giọng của kênh: clip (kịch bản viết riêng, chưa tốn credit), bài Facebook đi kèm (link aff ở bình luận đầu) và caption TikTok ngắn.</p>
            <ChannelPicker value={channelId} onChange={setChannelId} required label="Đăng trên kênh / page" />
            <label className="qt-bundle__part">
              <input type="checkbox" checked={withClip} onChange={(e) => setWithClip(e.target.checked)} />
              <span><strong>🎬 Clip</strong> — board + kịch bản 3–4 cảnh viết theo sản phẩm; tạo ảnh/video sau ở wizard.</span>
            </label>
            {withClip && (
              <label className="qt-field qt-bundle__sub">
                <span>Kiểu clip</span>
                <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                  {fitting.map((t) => <option key={t.id} value={t.id}>{t.title} · phù hợp</option>)}
                  {others.length > 0 && <optgroup label="Kiểu khác">{others.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</optgroup>}
                </select>
              </label>
            )}
            <label className="qt-bundle__part">
              <input type="checkbox" checked={withPost} onChange={(e) => setWithPost(e.target.checked)} />
              <span><strong>📝 Bài Facebook</strong> — đọc lời thoại clip + sản phẩm, bình luận đầu kèm link aff{product.aff_link ? "" : " (sản phẩm chưa có link aff)"}.</span>
            </label>
            {withPost && (
              <label className="qt-field qt-bundle__sub">
                <span>Kiểu bài</span>
                <select value={postKind} onChange={(e) => setPostKind(e.target.value)}>
                  {(kinds.length ? kinds : [{ key: "review", label: "Review sản phẩm" }]).map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                </select>
              </label>
            )}
            <label className="qt-bundle__part">
              <input type="checkbox" checked={withTiktok} onChange={(e) => setWithTiktok(e.target.checked)} />
              <span><strong>🎵 Caption TikTok</strong> — 1–2 câu móc + hashtag, dán khi đăng video.</span>
            </label>
            <div className="qt-post__actions">
              <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={busy || !channelId || !(withClip || withPost || withTiktok)} onClick={() => void run()}>
                {busy ? `AI đang làm… ${elapsed}s` : "🎁 Tạo gói nội dung"}
              </button>
              <button type="button" className="qt-btn qt-btn--ghost" disabled={busy} onClick={onClose}>Huỷ</button>
              {busy && <small className="qt-card__hint">Khoảng 20–40 giây: viết kịch bản clip trước, rồi bài và caption cùng lúc.</small>}
            </div>
          </>
        ) : (
          <>
            <ul className="qt-bundle__results">
              <li className={result.clip ? "" : "is-bad"}>
                <strong>🎬 Clip</strong>
                {result.clip ? (
                  <>
                    <span>{result.clip.name}{result.clip.tailored ? " · kịch bản đã viết theo sản phẩm" : " · kịch bản mẫu (AI chưa viết riêng được)"}</span>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => { onClose(); navigate(`/clips/${result.clip!.id}/script`); }}>Mở kịch bản →</button>
                  </>
                ) : <span className="qt-bundle__err">{result.errors.clip ?? "bỏ qua"}</span>}
              </li>
              <li className={result.post ? "" : "is-bad"}>
                <strong>📝 Bài Facebook</strong>
                {result.post ? (
                  <>
                    <span>{result.post.title}{result.post.first_comment ? " · có bình luận đầu kèm link" : ""}</span>
                    <span className="qt-bundle__btns">
                      <button type="button" className="qt-btn qt-btn--small" onClick={() => { onClose(); navigate(`/posts?post=${result.post!.id}`); }}>Mở bài</button>
                      <button type="button" className="qt-btn qt-btn--small" onClick={() => setSchedule({ kind: "post", postId: result.post!.id, channelId: result.channel_id, title: result.post!.title })}>📅 Lên lịch</button>
                    </span>
                  </>
                ) : <span className="qt-bundle__err">{result.errors.post ?? "bỏ qua"}</span>}
              </li>
              <li className={result.tiktok ? "" : "is-bad"}>
                <strong>🎵 Caption TikTok</strong>
                {result.tiktok ? (
                  <>
                    <span className="qt-bundle__caption">{result.tiktok.body}{result.tiktok.hashtags ? `\n${result.tiktok.hashtags}` : ""}</span>
                    <span className="qt-bundle__btns">
                      <button type="button" className="qt-btn qt-btn--small" onClick={() => void navigator.clipboard.writeText(`${result.tiktok!.body}\n\n${result.tiktok!.hashtags}`.trim()).then(() => toast.success("Đã copy caption TikTok."))}>📋 Copy</button>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => { onClose(); navigate(`/posts?post=${result.tiktok!.id}`); }}>Mở</button>
                    </span>
                  </>
                ) : <span className="qt-bundle__err">{result.errors.tiktok ?? "bỏ qua"}</span>}
              </li>
            </ul>
            <p className="qt-card__hint">Tiếp theo: mở kịch bản clip → "⚡ Tạo video tự động" (tốn credit), rồi lên lịch clip ở Bước 5. Bài và caption đã nằm trong "Bài đã lưu".</p>
            <div className="qt-post__actions">
              <button type="button" className="qt-btn qt-btn--accent" onClick={onClose}>Xong</button>
              <button type="button" className="qt-btn qt-btn--ghost" onClick={() => setResult(null)}>Làm gói khác</button>
            </div>
          </>
        )}
      </div>
      {schedule && <ScheduleDialog target={schedule} onClose={() => setSchedule(null)} onSaved={() => setSchedule(null)} />}
    </div>
  );
}
