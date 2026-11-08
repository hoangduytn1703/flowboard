import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  brainstormChannel, createChannel, deleteChannel, getChannelOptions, listChannels, reviewChannelPage, updateChannel,
  type Channel, type ChannelInput, type ChannelOptions,
} from "../../api/channels";
import { clipThumbUrl, listBoardSummaries, mediaUrl, type BoardSummary } from "../../api/client";
import { listPosts, type SavedPost } from "../../api/posts";
import { toast } from "../../store/toast";
import { invalidateChannels } from "../channels/ChannelPicker";
import { FacebookConnect } from "../channels/FacebookConnect";
import { PageEmpty, PageLoading } from "../PageState";
import { canUse, useFeature } from "../../lib/features";
import "../channels.css";

const EMPTY: ChannelInput = { name: "", platforms: ["facebook"], categories: [], description: "", audience: "", goal: "", link: "" };
const LINK_RE = /^https:\/\/([a-z0-9-]+\.)*(facebook\.com|fb\.com|instagram\.com|tiktok\.com|youtube\.com|threads\.net|threads\.com|zalo\.me)\//i;

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Create / edit form: name, platforms, business, description, audience, goal. */
function ChannelForm({ initial, options, onSaved, onCancel }: {
  initial: Channel | null; options: ChannelOptions; onSaved: (c: Channel) => void; onCancel: () => void;
}) {
  const [form, setForm] = useState<ChannelInput>(initial ? {
    name: initial.name, platforms: initial.platforms,
    categories: initial.categories?.length ? initial.categories : initial.category ? [initial.category] : [],
    description: initial.description, audience: initial.audience, goal: initial.goal, link: initial.link,
  } : EMPTY);
  const [busy, setBusy] = useState(false);
  const set = (patch: ChannelInput) => setForm((f) => ({ ...f, ...patch }));
  const plats = form.platforms ?? [];
  const cats = form.categories ?? [];
  const maxCats = options.max_categories || 3;

  async function submit() {
    if (!form.name?.trim()) { toast.warning("Kênh cần có tên."); return; }
    // Same normalisation as the backend: bare "tiktok.com/@x" and "http://" are fine.
    let link = (form.link ?? "").trim();
    if (link) {
      link = link.match(/https?:\/\/\S+/)?.[0] ?? link.split(/\s+/)[0];
      if (!/^[a-z]+:\/\//i.test(link)) link = "https://" + link.replace(/^\/+/, "");
      link = link.replace(/^http:\/\//i, "https://").replace(/\/+$/, "");
      form.link = link;
    }
    if (link && !LINK_RE.test(link + "/")) {
      toast.warning("Link kênh phải là Facebook, TikTok, Instagram, YouTube, Threads hoặc Zalo (https://…).");
      return;
    }
    setBusy(true);
    try {
      const row = initial ? await updateChannel(initial.id, form) : await createChannel(form);
      invalidateChannels();
      toast.success(initial ? "Đã lưu kênh." : `Đã tạo kênh "${row.name}".`);
      onSaved(row);
    } catch (e) {
      toast.error(`Lưu không được: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="qt-card qt-channels__form">
      <div className="qt-card__head">
        <h3 className="qt-card__title">{initial ? `Sửa kênh "${initial.name}"` : "Kênh mới"}</h3>
      </div>
      <label className="qt-field">
        <span>Tên kênh / page</span>
        <input value={form.name ?? ""} onChange={(e) => set({ name: e.target.value })} placeholder="VD: Bếp Ăn Vặt Của Mình" autoFocus />
      </label>
      <div className="qt-field">
        <span>Đăng ở đâu</span>
        <div className="qt-posts__chips">
          {options.platforms.map((p) => (
            <button key={p.key} type="button" className={`qt-chip${plats.includes(p.key) ? " qt-chip--on" : ""}`}
                    onClick={() => set({ platforms: plats.includes(p.key) ? plats.filter((x) => x !== p.key) : [...plats, p.key] })}>
              {p.label}
            </button>
          ))}
        </div>
        <small className="qt-card__hint">Nền tảng đầu tiên là nơi chính — bài viết sẽ theo định dạng của nó (Facebook dài hơn, TikTok là caption ngắn…).</small>
      </div>
      <label className="qt-field">
        <span>Link kênh / page <small>(không bắt buộc — AI đọc trang để bám sát phong cách và đánh giá kênh)</small></span>
        <input value={form.link ?? ""} onChange={(e) => set({ link: e.target.value })}
               placeholder="https://www.facebook.com/… · https://www.tiktok.com/@…" />
      </label>
      <div className="qt-field">
        <span>Danh mục của trang <small>(chọn tối đa {maxCats}, như khi tạo Trang trên Facebook — {cats.length}/{maxCats})</small></span>
        <div className="qt-posts__chips">
          {options.categories.map((c) => {
            const on = cats.includes(c.key);
            const full = !on && cats.length >= maxCats;
            return (
              <button key={c.key} type="button" className={`qt-chip${on ? " qt-chip--on" : ""}`} disabled={full}
                      title={full ? `Đã chọn đủ ${maxCats} — bỏ một cái để chọn cái khác` : undefined}
                      onClick={() => set({ categories: on ? cats.filter((x) => x !== c.key) : [...cats, c.key] })}>
                {c.label}
              </button>
            );
          })}
        </div>
        <small className="qt-card__hint">Cái đầu là danh mục chính. Ghép "bán gì" với "nói về gì" (VD: Cửa hàng + Nhà sáng tạo nội dung số) để AI hiểu đúng trang.</small>
      </div>
      <label className="qt-field">
        <span>Mô tả kênh</span>
        <textarea className="qt-textarea" value={form.description ?? ""} onChange={(e) => set({ description: e.target.value })}
                  placeholder="Page bán gì, nói về gì, khác gì page khác. VD: đồ ăn vặt healthy cho dân văn phòng, review thật, giá bình dân" />
      </label>
      <div className="qt-posts__row">
        <label className="qt-field">
          <span>Khán giả <small>(không bắt buộc)</small></span>
          <input value={form.audience ?? ""} onChange={(e) => set({ audience: e.target.value })} placeholder="VD: nữ 22-35, dân văn phòng" />
        </label>
        <label className="qt-field">
          <span>Mục tiêu bài đăng <small>(không bắt buộc)</small></span>
          <input value={form.goal ?? ""} onChange={(e) => set({ goal: e.target.value })} placeholder="VD: tương tác + kéo về link TikTok Shop" />
        </label>
      </div>
      <div className="qt-post__actions">
        <button type="button" className="qt-btn qt-btn--accent" disabled={busy} onClick={() => void submit()}>{busy ? "Đang lưu…" : initial ? "💾 Lưu kênh" : "+ Tạo kênh"}</button>
        <button type="button" className="qt-btn qt-btn--ghost" disabled={busy} onClick={onCancel}>Huỷ</button>
      </div>
    </section>
  );
}

/** "🔎 Đánh giá kênh": the page read through Chrome and reviewed by the AI. */
function PageReviewCard({ channel, onUpdated, onEdit }: { channel: Channel; onUpdated: (c: Channel) => void; onEdit: () => void }) {
  const [busy, setBusy] = useState(false);
  const r = channel.page_review;
  async function run() {
    setBusy(true);
    try {
      const row = await reviewChannelPage(channel.id);
      invalidateChannels();
      onUpdated(row);
      toast.success(`Đã đánh giá kênh — ${row.page_review?.score ?? "?"}/10.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="qt-card qt-channels__review">
      <div className="qt-card__head">
        <div>
          <h3 className="qt-card__title">🔎 Đánh giá kênh</h3>
          {channel.link
            ? <small className="qt-card__hint"><a href={channel.link} target="_blank" rel="noopener noreferrer">{channel.link}</a>{r ? ` · đọc lúc ${when(r.at)} (${r.posts_seen} bài thấy được)` : ""}</small>
            : <small className="qt-card__hint">Chưa có link kênh.</small>}
        </div>
        {channel.link ? (
          <button type="button" className={`qt-btn${r ? "" : " qt-btn--accent"}`} disabled={busy} onClick={() => void run()}>
            {busy ? "Đang đọc trang… (~1 phút)" : r ? "↻ Đọc & đánh giá lại" : "🔎 Xem & đánh giá kênh"}
          </button>
        ) : (
          <button type="button" className="qt-btn" onClick={onEdit}>+ Thêm link</button>
        )}
      </div>
      {!r ? (
        <p className="qt-card__hint">
          {channel.link
            ? "AI mở trang trong Chrome của bạn (tab nền, tự đóng), đọc các bài gần nhất rồi chấm điểm, chỉ điểm mạnh / cần sửa, và ghi lại phong cách bài đang đăng để bài viết sau bám theo. Cần extension bản 0.6.0."
            : "Gắn link page (Facebook, TikTok, Instagram, YouTube…) để AI xem kênh thật: đánh giá, gợi ý, và viết bài đúng giọng page."}
        </p>
      ) : (
        <div className="qt-channels__review-body">
          <div className="qt-channels__score">
            <strong>{r.score}</strong><span>/10</span>
            <small>{r.page_name}{r.followers ? ` · ${r.followers}${/theo dõi|follow/i.test(r.followers) ? "" : " theo dõi"}` : ""}</small>
          </div>
          <p className="qt-channels__summary">{r.summary}</p>
          {r.criteria.length > 0 && (
            <ul className="qt-channels__criteria">
              {r.criteria.map((c, i) => (
                <li key={i}>
                  <span>{c.name}</span>
                  <span className="qt-channels__bar"><span style={{ width: `${c.score * 10}%` }} /></span>
                  <b>{c.score}</b>
                  {c.note && <small>{c.note}</small>}
                </li>
              ))}
            </ul>
          )}
          <div className="qt-channels__cols">
            {r.strengths.length > 0 && <div><h4>👍 Điểm mạnh</h4><ul>{r.strengths.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
            {r.weaknesses.length > 0 && <div><h4>⚠ Cần cải thiện</h4><ul>{r.weaknesses.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          </div>
          {r.suggestions.length > 0 && <div><h4>💡 Gợi ý cho các bài tới</h4><ol>{r.suggestions.map((x, i) => <li key={i}>{x}</li>)}</ol></div>}
          {r.house_style && (
            <div className="qt-channels__style">
              <h4>✍️ Phong cách page đang dùng <small>(AI viết bài sẽ bám theo)</small></h4>
              <p>{r.house_style}</p>
              {r.sample_hooks.length > 0 && <ul>{r.sample_hooks.map((h, i) => <li key={i}>“{h}”</li>)}</ul>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** The brainstorm profile, readable in ten seconds, with the refresh button. */
function Direction({ channel, options, onUpdated }: { channel: Channel; options: ChannelOptions; onUpdated: (c: Channel) => void }) {
  const [busy, setBusy] = useState(false);
  const b = channel.brainstorm;
  async function run() {
    setBusy(true);
    try {
      const row = await brainstormChannel(channel.id);
      invalidateChannels();
      onUpdated(row);
      toast.success("Đã cập nhật định hướng kênh.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const left = Math.max(0, options.brainstorm_min_posts - channel.posts);
  return (
    <section className="qt-card qt-channels__direction">
      <div className="qt-card__head">
        <div>
          <h3 className="qt-card__title">🧠 Định hướng kênh</h3>
          {b && <small className="qt-card__hint">Brainstorm lúc {when(b.at)} từ {b.post_count} bài{b.clip_count ? ` + ${b.clip_count} clip` : ""}{channel.brainstorm_due ? " · đã có thêm bài mới, nên làm lại" : ""}</small>}
        </div>
        <button type="button" className={`qt-btn${b ? "" : " qt-btn--accent"}`} disabled={busy} onClick={() => void run()}>
          {busy ? "AI đang brainstorm…" : b ? "↻ Brainstorm lại" : "🧠 Brainstorm ngay"}
        </button>
      </div>
      {!b ? (
        <p className="qt-card__hint">
          {left > 0
            ? `Sau ${left} bài viết nữa AI sẽ tự đọc các bài và clip của kênh rồi rút ra định hướng (vị thế, giọng, chủ đề, nên / không nên). Bạn cũng có thể bấm brainstorm ngay từ mô tả kênh.`
            : "Kênh đã đủ bài — bấm Brainstorm để AI rút ra định hướng; các bài viết sau sẽ bám theo."}
        </p>
      ) : (
        <div className="qt-channels__profile">
          <p className="qt-channels__summary">{b.summary || b.positioning}</p>
          <dl>
            {b.positioning && <><dt>Vị thế</dt><dd>{b.positioning}</dd></>}
            {b.audience && <><dt>Khán giả</dt><dd>{b.audience}</dd></>}
            {b.voice && <><dt>Giọng</dt><dd>{b.voice}</dd></>}
            {b.post_mix && <><dt>Nhịp bài</dt><dd>{b.post_mix}</dd></>}
            {b.pillars.length > 0 && <><dt>Chủ đề trụ cột</dt><dd><ul>{b.pillars.map((p, i) => <li key={i}><strong>{p.name}</strong>{p.note ? ` — ${p.note}` : ""}</li>)}</ul></dd></>}
            {b.do.length > 0 && <><dt>Nên</dt><dd><ul>{b.do.map((x, i) => <li key={i}>{x}</li>)}</ul></dd></>}
            {b.dont.length > 0 && <><dt>Không nên</dt><dd><ul>{b.dont.map((x, i) => <li key={i}>{x}</li>)}</ul></dd></>}
            {b.hashtags.length > 0 && <><dt>Hashtag nhà</dt><dd className="qt-channels__tags">{b.hashtags.join(" ")}</dd></>}
            {b.ideas.length > 0 && <><dt>Ý tưởng bài tiếp</dt><dd><ol>{b.ideas.map((x, i) => <li key={i}>{x}</li>)}</ol></dd></>}
          </dl>
        </div>
      )}
    </section>
  );
}

/**
 * "Kênh của tôi" — the pages the seller posts to. Each channel: its fields,
 * the brainstormed direction, and the posts / clips made for it.
 */
export function ChannelsPage() {
  const navigate = useNavigate();
  const postsOn = useFeature("posts");
  const fbOn = useFeature("facebook");
  const [params, setParams] = useSearchParams();
  const [options, setOptions] = useState<ChannelOptions | null>(null);
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [editing, setEditing] = useState<Channel | null | "new">(null);
  const [openId, setOpenId] = useState<number | null>(Number(params.get("id")) || null);
  const [posts, setPosts] = useState<SavedPost[]>([]);
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    document.title = "Kênh của tôi · DFlow";
    void getChannelOptions().then(setOptions).catch((e) => toast.error(`Không tải được tuỳ chọn: ${e instanceof Error ? e.message : e}`));
    void listChannels().then(setChannels).catch(() => setChannels([]));
    void listBoardSummaries().then(setBoards).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!openId) { setPosts([]); return; }
    void listPosts(undefined, openId).then(setPosts).catch(() => setPosts([]));
  }, [openId]);
  useEffect(() => {
    if (channels && channels.length && openId === null) setOpenId(channels[0].id);
  }, [channels, openId]);

  const open = useMemo(() => channels?.find((c) => c.id === openId) ?? null, [channels, openId]);
  const clips = useMemo(() => boards.filter((b) => (b.data?.quicktool as { channel_id?: number } | undefined)?.channel_id === openId), [boards, openId]);

  function replace(row: Channel) {
    setChannels((list) => {
      const l = list ?? [];
      return l.some((c) => c.id === row.id) ? l.map((c) => (c.id === row.id ? row : c)) : [row, ...l];
    });
  }

  /** A new link is read and reviewed right away, in the background. */
  async function autoReview(row: Channel) {
    if (!canUse("posts")) return; // the page review is part of the "Bài viết" feature
    toast.info(`Đang mở ${row.link} trong Chrome để đánh giá kênh (khoảng 1 phút)…`, { duration: 8000 });
    try {
      const out = await reviewChannelPage(row.id);
      invalidateChannels();
      replace(out);
      toast.success(`Đã đánh giá kênh "${out.name}" — ${out.page_review?.score ?? "?"}/10. AI viết bài sẽ bám phong cách page.`, { duration: 9000 });
    } catch (e) {
      toast.warning(`Chưa đánh giá được kênh: ${e instanceof Error ? e.message : e}`);
    }
  }

  async function remove(c: Channel) {
    try {
      await deleteChannel(c.id);
      invalidateChannels();
      setChannels((list) => (list ?? []).filter((x) => x.id !== c.id));
      setOpenId(null);
      toast.success(`Đã xoá kênh "${c.name}". Bài viết và clip của kênh vẫn còn, chỉ không gắn kênh nữa.`);
    } catch (e) {
      toast.error(`Xoá không được: ${e instanceof Error ? e.message : e}`);
    } finally {
      setConfirmDelete(false);
    }
  }

  if (!options || channels === null) return <PageLoading text="Đang mở Kênh của tôi…" />;
  const catLabel = (k: string) => options.categories.find((c) => c.key === k)?.label ?? k;
  const platLabel = (k: string) => options.platforms.find((p) => p.key === k)?.label ?? k;

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Kênh của tôi</span>
      </header>
      <div className="qt-home qt-channels">
        {editing !== null && (
          <ChannelForm initial={editing === "new" ? null : editing} options={options}
                       onSaved={(row) => {
                         const wasNew = editing === "new";
                         const linkChanged = !wasNew && editing && editing.link !== row.link;
                         replace(row); setEditing(null); setOpenId(row.id); setParams({ id: String(row.id) }, { replace: true });
                         if (row.link && (wasNew || linkChanged)) void autoReview(row);
                       }}
                       onCancel={() => setEditing(null)} />
        )}
        {channels.length === 0 ? (
          editing === null && (
            <PageEmpty icon="📣" title="Chưa có kênh nào"
                       actions={<button type="button" className="qt-btn qt-btn--accent" onClick={() => setEditing("new")}>+ Tạo kênh đầu tiên</button>}>
              Một kênh = một page / tài khoản bạn đăng bài. Khai báo page bán gì, cho ai, giọng thế nào — AI sẽ viết bài và clip
              bám theo, và sau 3 bài sẽ tự brainstorm định hướng.
            </PageEmpty>
          )
        ) : (
          <div className="qt-channels__grid">
            <aside className="qt-card qt-channels__list">
              <div className="qt-card__head">
                <h3 className="qt-card__title">Kênh</h3>
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={() => setEditing("new")}>+ Kênh mới</button>
              </div>
              <ul>
                {channels.map((c) => (
                  <li key={c.id}>
                    <button type="button" className={`qt-channels__item${c.id === openId ? " is-open" : ""}`}
                            onClick={() => { setOpenId(c.id); setConfirmDelete(false); setParams({ id: String(c.id) }, { replace: true }); }}>
                      <strong>{c.name}</strong>
                      <small>{c.platforms.map(platLabel).join(" · ") || "—"} · {c.posts} bài · {c.clips} clip{c.brainstorm ? " · 🧠" : ""}{c.brainstorm_due ? " ·  cần brainstorm" : ""}</small>
                    </button>
                  </li>
                ))}
              </ul>
            </aside>

            {open && (
              <div className="qt-channels__detail">
                <section className="qt-card">
                  <div className="qt-card__head">
                    <div>
                      <h3 className="qt-card__title">📣 {open.name}</h3>
                      <small className="qt-card__hint">{open.platforms.map(platLabel).join(", ") || "Chưa chọn nền tảng"} · {(open.categories.length ? open.categories : [open.category || "other"]).map(catLabel).join(" · ")}</small>
                    </div>
                    <div className="qt-posts__headbtns">
                      <button type="button" className="qt-btn qt-btn--small" onClick={() => setEditing(open)}>✎ Sửa</button>
                      {confirmDelete ? (
                        <button type="button" className="qt-btn qt-btn--small qt-btn--danger" onClick={() => void remove(open)}>Xoá thật?</button>
                      ) : (
                        <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => setConfirmDelete(true)}>Xoá</button>
                      )}
                    </div>
                  </div>
                  {open.description && <p className="qt-channels__desc">{open.description}</p>}
                  <div className="qt-stats">
                    <div className="qt-stat"><strong>{open.posts}</strong><span>bài viết</span></div>
                    <div className="qt-stat"><strong>{open.clips}</strong><span>clip</span></div>
                    {open.audience && <div className="qt-stat qt-stat--text"><strong>{open.audience}</strong><span>khán giả</span></div>}
                    {open.goal && <div className="qt-stat qt-stat--text"><strong>{open.goal}</strong><span>mục tiêu</span></div>}
                  </div>
                  <div className="qt-post__actions">
                    {postsOn && <button type="button" className="qt-btn qt-btn--accent" onClick={() => navigate(`/posts?channel=${open.id}`)}>✍️ Viết bài cho kênh</button>}
                    <button type="button" className="qt-btn" onClick={() => navigate(`/clips/new?channel=${open.id}`)}>🎬 Tạo clip cho kênh</button>
                  </div>
                </section>

                {fbOn && <FacebookConnect channel={open} onUpdated={replace} />}

                {postsOn && <PageReviewCard channel={open} onUpdated={replace} onEdit={() => setEditing(open)} />}

                {postsOn && <Direction channel={open} options={options} onUpdated={replace} />}

                <section className="qt-card">
                  <div className="qt-card__head"><h3 className="qt-card__title">📝 Bài viết của kênh</h3></div>
                  {posts.length === 0 ? <p className="qt-card__hint">Chưa có bài nào — viết ở trang Bài viết và chọn kênh này.</p> : (
                    <ul className="qt-posts__saved">
                      {posts.map((p) => (
                        <li key={p.id}>
                          {p.images[0] ? <img src={mediaUrl(p.images[0])} alt="" loading="lazy" /> : <span className="qt-posts__noimg">📝</span>}
                          <div className="qt-posts__savedtext">
                            <strong>{p.title || p.body.split("\n")[0]}</strong>
                            <small>{when(p.updated_at ?? p.created_at)}{p.board_id ? ` · clip #${p.board_id}` : ""}</small>
                          </div>
                          <button type="button" className="qt-btn qt-btn--small" onClick={() => navigate(`/posts?post=${p.id}`)}>Mở</button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="qt-card">
                  <div className="qt-card__head"><h3 className="qt-card__title">🎬 Clip của kênh</h3></div>
                  {clips.length === 0 ? <p className="qt-card__hint">Chưa có clip nào — khi tạo clip mới chọn kênh này, hoặc gắn ở Bước 1 của clip cũ.</p> : (
                    <ul className="qt-today__list">
                      {clips.map((b) => (
                        <li key={b.id}>
                          {clipThumbUrl(b.summary) && <img className="qt-today__thumb" src={clipThumbUrl(b.summary)!} alt="" loading="lazy" />}
                          <span className="qt-today__what">{b.name}</span>
                          <span className="qt-today__meta">{b.summary.exported ? "đã ghép" : `${b.summary.clips_done}/${b.summary.clips} video`}</span>
                          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => navigate(`/clips/${b.id}`)}>Mở</button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
