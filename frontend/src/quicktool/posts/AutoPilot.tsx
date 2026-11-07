import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createAutoPlan, deleteAutoPlan, getAutopilotStatus, listAutoPlans, prepareAutoPlan, RUN_STATUS, updateAutoPlan,
  type AutoAi, type AutoPlan, type AutoPlanInput, type AutopilotStatus, type AutoRun, type ProductMode,
} from "../../api/autopilot";
import type { Product } from "../../api/client";
import type { PostBrief, PostOptions, PostSeries } from "../../api/posts";
import { toast } from "../../store/toast";
import { ChannelPicker, useChannels } from "../channels/ChannelPicker";
import { PageEmpty, PageLoading } from "../PageState";
import "./autopilot.css";

/** What "🤖 Tự động đăng theo lịch với cài đặt này" brings over from the write form. */
export interface AutoSeed {
  channel_id: number | null;
  brief: PostBrief;
  product_id: number | null;
  series: string;
}

const DAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const QUICK_TIMES = ["07:00", "11:30", "12:00", "20:00", "21:00"];
const LEADS: [number, string][] = [[60, "1 tiếng"], [120, "2 tiếng"], [180, "3 tiếng"], [360, "6 tiếng"], [720, "12 tiếng (tối hôm trước)"]];
const BRIEF_DEFAULT: PostBrief = { kind: "discussion", tone: "friendly", length: "medium", cta: "none", hook: "auto", format: "auto", emoji: "some", boosts: [], images: 1 };

function blank(seed?: AutoSeed | null): AutoPlanInput {
  const brief = { ...BRIEF_DEFAULT, ...(seed?.brief ?? {}) };
  delete brief.with_video;  // a schedule posts text + pictures (a Flow video per slot would burn credits)
  return {
    name: "", channel_id: seed?.channel_id ?? 0, days: [0, 2, 4], times: ["20:00"], lead_minutes: 180, brief,
    series: seed?.series ?? "", product_mode: seed?.product_id ? "fixed" : "none",
    product_ids: seed?.product_id ? [seed.product_id] : [], ai: "claude", fb_story: false,
  };
}

function inputOf(p: AutoPlan): AutoPlanInput {
  return {
    name: p.name, channel_id: p.channel_id, days: p.days, times: p.times, lead_minutes: p.lead_minutes,
    brief: { ...BRIEF_DEFAULT, ...p.brief }, series: p.series, product_mode: p.product_mode, product_ids: p.product_ids,
    ai: p.ai, fb_story: p.fb_story,
  };
}

function RunChip({ run }: { run: AutoRun }) {
  const s = RUN_STATUS[run.status] ?? { label: run.status, tone: "off" };
  return <span className={`ap-chip ap-chip--${s.tone}`}>{s.label}</span>;
}

/** "🤖 Tự động đăng" on the Posts page: a Page's fixed posting schedules — when, what, which AI — and what each
 * slot got. Nobody has to do anything once a schedule is on: the agent writes each post ahead and posts it. */
export function AutoPilot({ options, products, allSeries, seed, onSeedUsed }: {
  options: PostOptions;
  products: Product[];
  allSeries: PostSeries[];
  seed: AutoSeed | null;
  onSeedUsed: () => void;
}) {
  const navigate = useNavigate();
  const [channels] = useChannels();
  const [plans, setPlans] = useState<AutoPlan[] | null>(null);
  const [status, setStatus] = useState<AutopilotStatus | null>(null);
  const [selected, setSelected] = useState<number | "new" | null>(null);
  const [form, setForm] = useState<AutoPlanInput>(() => blank(seed));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [newSeries, setNewSeries] = useState(false);
  const seeded = useRef(false);

  async function reload() {
    try {
      setPlans(await listAutoPlans());
    } catch (e) {
      toast.error(`Không tải được lịch tự động: ${e instanceof Error ? e.message : e}`);
      setPlans((p) => p ?? []);
    }
  }

  useEffect(() => {
    void reload();
    void getAutopilotStatus().then(setStatus).catch(() => undefined);
  }, []);

  // a seed from the write form opens a new schedule with those settings
  useEffect(() => {
    if (!seed || seeded.current) return;
    seeded.current = true;
    setSelected("new");
    setForm(blank(seed));
    setNewSeries(Boolean(seed.series) && !allSeries.some((s) => s.name === seed.series));
    setDirty(true);
    onSeedUsed();
    toast.info("Đã lấy cài đặt từ form Viết bài — chọn ngày, giờ đăng rồi bấm Lưu lịch.");
  }, [seed, allSeries, onSeedUsed]);

  // first plan opens by itself; nothing yet → a new one
  useEffect(() => {
    if (plans === null || selected !== null) return;
    if (plans.length) pick(plans[0]);
    else { setSelected("new"); setForm(blank(null)); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plans]);

  // refresh while something is being written / posted (10 s), else every 30 s
  const active = (plans ?? []).some((p) => [...p.runs, ...p.next.map((n) => n.run).filter(Boolean) as AutoRun[]]
    .some((r) => ["writing", "pictures", "posting"].includes(r.status)));
  useEffect(() => {
    const t = window.setInterval(() => void reload(), active ? 10_000 : 30_000);
    return () => window.clearInterval(t);
  }, [active]);

  function pick(p: AutoPlan) {
    if (dirty && !window.confirm("Lịch đang sửa chưa lưu — bỏ thay đổi?")) return;
    setSelected(p.id);
    setForm(inputOf(p));
    setNewSeries(false);
    setDirty(false);
    setConfirmDelete(false);
  }

  function startNew() {
    if (dirty && !window.confirm("Lịch đang sửa chưa lưu — bỏ thay đổi?")) return;
    setSelected("new");
    setForm(blank(null));
    setNewSeries(false);
    setDirty(false);
  }

  function set(patch: Partial<AutoPlanInput>) {
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
  }
  function setBrief(patch: Partial<PostBrief>) {
    setForm((f) => ({ ...f, brief: { ...f.brief, ...patch } }));
    setDirty(true);
  }

  const plan = typeof selected === "number" ? (plans ?? []).find((p) => p.id === selected) ?? null : null;
  const channel = channels.find((c) => c.id === form.channel_id);
  const connected = Boolean(channel?.fb_connected);
  const channelSeries = useMemo(() => {
    const names = new Map<string, PostSeries>();
    for (const s of allSeries) if (s.channel_id === form.channel_id || s.channel_id == null) if (!names.has(s.name)) names.set(s.name, s);
    return [...names.values()];
  }, [allSeries, form.channel_id]);

  const problem = !form.channel_id ? "Chọn kênh / page"
    : !connected ? "Kênh chưa kết nối Facebook Page"
      : !form.days.length ? "Chọn ít nhất một ngày"
        : !form.times.filter(Boolean).length ? "Chọn giờ đăng"
          : form.product_mode !== "none" && !form.product_ids.length ? "Chọn sản phẩm"
            : newSeries && !form.series.trim() ? "Đặt tên loạt truyện" : null;

  async function save() {
    if (problem) return;
    setBusy("save");
    try {
      const body = { ...form, times: form.times.filter(Boolean) };
      const saved = selected === "new" || plan === null ? await createAutoPlan({ ...body, enabled: true }) : await updateAutoPlan(plan.id, body);
      toast.success(selected === "new" ? `Đã bật lịch tự động — ${saved.when}. Bài kế tiếp: ${saved.next[0]?.label ?? "—"}.` : "Đã lưu lịch tự động.");
      setDirty(false);
      setSelected(saved.id);
      setForm(inputOf(saved));
      setNewSeries(false);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function toggle(p: AutoPlan) {
    setBusy(`toggle-${p.id}`);
    try {
      await updateAutoPlan(p.id, { enabled: !p.enabled });
      toast.success(p.enabled ? "Đã tạm dừng — các bài đã soạn mà chưa đăng sẽ không đăng." : "Đã bật lại lịch tự động.");
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function prepare(p: AutoPlan) {
    setBusy("prepare");
    try {
      const r = await prepareAutoPlan(p.id);
      toast.info(`AI đang soạn bài cho khung ${r.label} — xong sẽ hiện ở "Sắp tới" (bài nằm trong Bài đã lưu, sửa được trước giờ đăng).`);
      window.setTimeout(() => void reload(), 1500);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function remove(p: AutoPlan) {
    if (!confirmDelete) { setConfirmDelete(true); return; }
    setBusy("delete");
    try {
      await deleteAutoPlan(p.id);
      toast.success("Đã xoá lịch tự động (bài đã viết vẫn trong Bài đã lưu).");
      setSelected(null);
      setDirty(false);
      setConfirmDelete(false);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  function toggleDay(d: number) {
    set({ days: form.days.includes(d) ? form.days.filter((x) => x !== d) : [...form.days, d].sort() });
  }
  function setTime(i: number, v: string) {
    set({ times: form.times.map((t, j) => (j === i ? v : t)) });
  }
  function addTime(v = "") {
    if (form.times.length >= (status?.max_times ?? 6) || (v && form.times.includes(v))) return;
    set({ times: [...form.times, v].sort((a, b) => (a || "99").localeCompare(b || "99")) });
  }

  if (plans === null) return <PageLoading text="Đang tải lịch tự động…" />;

  const runs = plan?.runs ?? [];
  const aiDown = (ai: AutoAi) => status !== null && !status.ai[ai];

  return (
    <div className="ap">
      <aside className="qt-card ap-list">
        <div className="ap-list__head">
          <strong>Lịch tự động</strong>
          <button type="button" className="qt-btn qt-btn--small qt-btn--accent" onClick={startNew}>＋ Lịch mới</button>
        </div>
        {plans.length === 0 && selected !== "new" && (
          <PageEmpty compact icon="🤖" title="Chưa có lịch tự động">Đặt ngày, giờ và kiểu bài — tool tự viết và đăng lên Page.</PageEmpty>
        )}
        <ul>
          {plans.map((p) => {
            const next = p.next[0];
            const last = p.runs.find((r) => !["writing", "pictures", "waiting", "scheduled"].includes(r.status));
            return (
              <li key={p.id} className={`ap-plan${selected === p.id ? " is-on" : ""}${p.enabled ? "" : " is-paused"}`}>
                <button type="button" className="ap-plan__open" onClick={() => pick(p)}>
                  <span className="ap-plan__name">{p.enabled ? "🟢" : "⏸"} {p.name}</span>
                  <span className="ap-plan__when">{p.channel} · {p.when}</span>
                  {p.enabled && next && (
                    <span className="ap-plan__next">Bài kế: {next.label}{next.run ? <> · <RunChip run={next.run} /></> : " · chưa soạn"}</span>
                  )}
                  {last && <span className="ap-plan__last">Lần trước: <RunChip run={last} /></span>}
                  {!p.connected && <span className="ap-plan__warn">⚠ Kênh chưa kết nối Facebook Page</span>}
                </button>
                <button type="button" className={`ap-switch${p.enabled ? " is-on" : ""}`} role="switch" aria-checked={p.enabled}
                        title={p.enabled ? "Tạm dừng" : "Bật lại"} disabled={busy === `toggle-${p.id}`} onClick={() => void toggle(p)}>
                  <span />
                </button>
              </li>
            );
          })}
        </ul>
        <p className="qt-card__hint ap-list__note">
          Máy phải bật và DFlow đang chạy thì mới soạn / đăng được. Khung giờ trôi qua lúc máy tắt sẽ bị bỏ qua, không đăng bù.
        </p>
      </aside>

      <section className="qt-card ap-edit">
        <div className="ap-edit__head">
          <h3 className="qt-card__title">{selected === "new" ? "Lịch tự động mới" : plan?.name ?? "Lịch tự động"}</h3>
          {plan && <span className={`ap-chip ${plan.enabled ? "ap-chip--ok" : "ap-chip--off"}`}>{plan.enabled ? "● Đang chạy" : "⏸ Tạm dừng"}</span>}
          {dirty && <span className="ap-chip ap-chip--wait">● Chưa lưu</span>}
        </div>

        <div className="ap-grid">
          <div className="ap-col">
            <div className="qt-posts__block">
              <div className="qt-posts__blockhead"><span className="qt-posts__num">1</span> Đăng lên đâu, lúc nào</div>
              <label className="qt-field">
                <span>Tên lịch <small>(không bắt buộc)</small></span>
                <input value={form.name ?? ""} onChange={(e) => set({ name: e.target.value })} placeholder="VD: Mẹo vặt tối T2–T6" />
              </label>
              <ChannelPicker value={form.channel_id || null} onChange={(id) => set({ channel_id: id ?? 0, series: "" })} required label="Facebook Page" />
              {form.channel_id > 0 && !connected && (
                <p className="ap-warn">⚠ Kênh này chưa kết nối Facebook Page nên không tự đăng được — <Link to="/channels">kết nối ở trang Kênh</Link>.</p>
              )}
              <div className="qt-field">
                <span>Ngày đăng</span>
                <div className="ap-days" role="group" aria-label="Ngày đăng">
                  {DAYS.map((d, i) => (
                    <button key={d} type="button" className={`qt-chip qt-chip--sm${form.days.includes(i) ? " qt-chip--on" : ""}`}
                            aria-pressed={form.days.includes(i)} onClick={() => toggleDay(i)}>{d}</button>
                  ))}
                  <button type="button" className="qt-link" onClick={() => set({ days: [0, 1, 2, 3, 4, 5, 6] })}>Mỗi ngày</button>
                  <button type="button" className="qt-link" onClick={() => set({ days: [0, 1, 2, 3, 4] })}>T2–T6</button>
                </div>
              </div>
              <div className="qt-field">
                <span>Giờ đăng <small>(giờ Việt Nam)</small></span>
                <div className="ap-times">
                  {form.times.map((t, i) => (
                    <span key={i} className="ap-time">
                      <input type="time" value={t} onChange={(e) => setTime(i, e.target.value)} />
                      {form.times.length > 1 && <button type="button" aria-label="Bỏ giờ này" onClick={() => set({ times: form.times.filter((_, j) => j !== i) })}>×</button>}
                    </span>
                  ))}
                  <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" onClick={() => addTime("")}>＋ Giờ</button>
                </div>
                <div className="ap-quick">
                  {QUICK_TIMES.map((t) => (
                    <button key={t} type="button" className="qt-chip qt-chip--sm" disabled={form.times.includes(t)} onClick={() => addTime(t)}>+ {t}</button>
                  ))}
                </div>
              </div>
              <label className="qt-field">
                <span>Soạn bài trước giờ đăng</span>
                <select value={form.lead_minutes} onChange={(e) => set({ lead_minutes: Number(e.target.value) })}>
                  {LEADS.map(([m, label]) => <option key={m} value={m}>{label}</option>)}
                </select>
                <small className="qt-card__hint">Bài soạn xong nằm trong Bài đã lưu — sửa được trước giờ đăng. Soạn hỏng thì thử lại mỗi 10 phút; tới giờ vẫn chưa có bài thì bỏ khung đó.</small>
              </label>
              <label className="qt-check">
                <input type="checkbox" checked={form.fb_story} onChange={(e) => set({ fb_story: e.target.checked })} /> 📲 Thêm vào tin của Page mỗi lần đăng
              </label>
            </div>

            <div className="qt-posts__block">
              <div className="qt-posts__blockhead"><span className="qt-posts__num">3</span> AI viết</div>
              <div className="qt-posts__yesno" role="radiogroup" aria-label="AI viết">
                {(["claude", "gemini"] as AutoAi[]).map((ai) => (
                  <label key={ai} className={form.ai === ai ? "is-on" : ""}>
                    <input type="radio" name="ap-ai" checked={form.ai === ai} onChange={() => set({ ai })} />
                    {ai === "claude" ? " Claude CLI (đang dùng)" : " Gemini (API key)"}{aiDown(ai) ? " — chưa sẵn sàng" : ""}
                  </label>
                ))}
              </div>
              <small className="qt-card__hint">Cái được chọn viết trước; lỗi (hết lượt, mất mạng…) thì tự chuyển sang cái còn lại.</small>
            </div>
          </div>

          <div className="ap-col">
            <div className="qt-posts__block">
              <div className="qt-posts__blockhead"><span className="qt-posts__num">2</span> Đăng gì</div>
              <label className="qt-field">
                <span>Kiểu bài</span>
                <select value={form.brief.kind} onChange={(e) => setBrief({ kind: e.target.value })}>
                  {options.kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                </select>
              </label>
              <label className="qt-field">
                <span>Loạt truyện</span>
                <select value={newSeries ? "__new" : form.series} onChange={(e) => {
                  const v = e.target.value;
                  if (v === "__new") { setNewSeries(true); set({ series: "" }); return; }
                  setNewSeries(false);
                  set({ series: v });
                }}>
                  <option value="">Không — mỗi lần một bài mới</option>
                  {channelSeries.map((s) => <option key={s.name} value={s.name}>📖 {s.name} · đã có {s.episodes} tập</option>)}
                  <option value="__new">＋ Loạt truyện mới…</option>
                </select>
                {newSeries && <input value={form.series} autoFocus onChange={(e) => set({ series: e.target.value })} placeholder="Tên loạt mới, VD: Những thú vị về hệ mặt trời" />}
                {form.series && <small className="qt-card__hint">Mỗi khung giờ là tập kế tiếp — AI đọc các tập trước để viết nối tiếp.</small>}
              </label>
              <label className="qt-field">
                <span>Ý chính / chủ đề <small>(không bắt buộc)</small></span>
                <textarea className="qt-textarea" rows={3} value={form.brief.topic ?? ""} onChange={(e) => setBrief({ topic: e.target.value })}
                          placeholder="Để trống = AI tự chọn chủ đề theo định hướng của Page, không trùng các bài lịch này đã đăng" />
              </label>
              <div className="qt-posts__row">
                <label className="qt-field">
                  <span>Ảnh kèm</span>
                  <select value={String(form.brief.images ?? 0)} onChange={(e) => setBrief({ images: Number(e.target.value) })}>
                    <option value="0">Không ảnh</option>
                    {Array.from({ length: options.max_images }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n} ảnh AI (Flow)</option>)}
                  </select>
                </label>
                <label className="qt-field">
                  <span>Kêu gọi</span>
                  <select value={form.brief.cta} onChange={(e) => setBrief({ cta: e.target.value })}>
                    {options.ctas.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                </label>
              </div>
              {(form.brief.images ?? 0) > 0 && (
                <>
                  <label className="qt-field">
                    <span>Muốn ảnh thế nào <small>(không bắt buộc)</small></span>
                    <input value={form.brief.image_wish ?? ""} onChange={(e) => setBrief({ image_wish: e.target.value })} placeholder="VD: ảnh vũ trụ chân thực, màu tối" />
                  </label>
                  <small className="qt-card__hint">Ảnh vẽ bằng Flow: cần Chrome mở tab Flow + extension. Flow không vẽ được thì bài vẫn đăng (không ảnh).</small>
                </>
              )}
              <div className="qt-posts__row">
                <label className="qt-field">
                  <span>Giọng</span>
                  <select value={form.brief.tone} onChange={(e) => setBrief({ tone: e.target.value })}>
                    {options.tones.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                </label>
                <label className="qt-field">
                  <span>Độ dài</span>
                  <select value={form.brief.length} onChange={(e) => setBrief({ length: e.target.value })}>
                    {options.lengths.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                </label>
              </div>
              <div className="qt-field">
                <span>Sản phẩm</span>
                <div className="qt-posts__yesno ap-three" role="radiogroup" aria-label="Sản phẩm">
                  {([["none", "Không gắn"], ["fixed", "Một sản phẩm"], ["rotate", "Xoay vòng nhiều"]] as [ProductMode, string][]).map(([m, label]) => (
                    <label key={m} className={form.product_mode === m ? "is-on" : ""}>
                      <input type="radio" name="ap-product" checked={form.product_mode === m}
                             onChange={() => set({ product_mode: m, product_ids: m === "none" ? [] : m === "fixed" ? form.product_ids.slice(0, 1) : form.product_ids })} /> {label}
                    </label>
                  ))}
                </div>
                {form.product_mode === "fixed" && (
                  <select value={form.product_ids[0] ?? ""} onChange={(e) => set({ product_ids: e.target.value ? [Number(e.target.value)] : [] })}>
                    <option value="">— Chọn sản phẩm —</option>
                    {products.map((p) => <option key={p.id} value={p.id}>{p.name}{p.aff_link ? " · 🔗 có link aff" : ""}</option>)}
                  </select>
                )}
                {form.product_mode === "rotate" && (
                  <div className="ap-products">
                    {products.map((p) => {
                      const on = form.product_ids.includes(p.id);
                      return (
                        <label key={p.id} className={on ? "is-on" : ""}>
                          <input type="checkbox" checked={on} onChange={() => set({ product_ids: on ? form.product_ids.filter((x) => x !== p.id) : [...form.product_ids, p.id] })} />
                          {p.name}{p.aff_link ? " 🔗" : ""}
                        </label>
                      );
                    })}
                    {products.length === 0 && <small className="qt-card__hint">Chưa có sản phẩm nào.</small>}
                  </div>
                )}
                {form.product_mode !== "none" && <small className="qt-card__hint">Sản phẩm có link tiếp thị: link tự vào bình luận đầu tiên.{form.product_mode === "rotate" ? " Mỗi khung lấy sản phẩm lâu nhất chưa được nhắc." : ""}</small>}
              </div>
            </div>
          </div>
        </div>

        <div className="ap-actions">
          <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={!!problem || busy === "save" || (!dirty && selected !== "new")} onClick={() => void save()}
                  title={problem ?? undefined}>
            {busy === "save" ? "Đang lưu…" : selected === "new" ? "🤖 Lưu & bật lịch tự động" : "💾 Lưu thay đổi"}
          </button>
          {plan && (
            <>
              <button type="button" className="qt-btn" disabled={!plan.enabled || busy === "prepare" || dirty} onClick={() => void prepare(plan)}
                      title={dirty ? "Lưu thay đổi trước" : "Viết luôn bài cho khung giờ kế tiếp chưa có bài — để xem trước bài sẽ đăng"}>
                {busy === "prepare" ? "Đang gửi…" : "⚡ Soạn ngay bài kế tiếp"}
              </button>
              <button type="button" className="qt-btn qt-btn--ghost" disabled={busy === `toggle-${plan.id}`} onClick={() => void toggle(plan)}>
                {plan.enabled ? "⏸ Tạm dừng" : "▶ Bật lại"}
              </button>
              <button type="button" className="qt-btn qt-btn--danger" disabled={busy === "delete"} onClick={() => void remove(plan)} onBlur={() => setConfirmDelete(false)}>
                {confirmDelete ? "Bấm lần nữa để xoá" : "🗑 Xoá lịch"}
              </button>
            </>
          )}
          {problem && <small className="qt-posts__need">{problem}.</small>}
        </div>

        {plan && plan.enabled && plan.next.length > 0 && (
          <div className="ap-section">
            <h4>Sắp tới</h4>
            <ul className="ap-runs">
              {plan.next.map((n) => (
                <li key={n.at}>
                  <span className="ap-runs__when">{n.label}</span>
                  {n.run ? <RunChip run={n.run} /> : <span className="ap-chip ap-chip--off">Chưa soạn — soạn trước {LEADS.find(([m]) => m === plan.lead_minutes)?.[1] ?? `${plan.lead_minutes} phút`}</span>}
                  {n.run?.post_id ? <button type="button" className="qt-link ap-runs__post" onClick={() => navigate(`/posts?post=${n.run!.post_id}`)}>{n.run.post_title || `Bài #${n.run.post_id}`}</button> : null}
                  {n.run?.error && <small className="ap-runs__err">{n.run.error}</small>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {plan && (
          <div className="ap-section">
            <h4>Nhật ký <small>· {runs.length} khung gần nhất</small></h4>
            {runs.length === 0 ? <p className="qt-card__hint">Chưa có khung nào — bài đầu tiên được soạn trước giờ đăng {LEADS.find(([m]) => m === plan.lead_minutes)?.[1] ?? ""}.</p> : (
              <ul className="ap-runs">
                {runs.map((r) => (
                  <li key={r.id}>
                    <span className="ap-runs__when">{r.label}</span>
                    <RunChip run={r} />
                    {r.post_id ? <button type="button" className="qt-link ap-runs__post" onClick={() => navigate(`/posts?post=${r.post_id}`)}>{r.episode ? `Tập ${r.episode}: ` : ""}{r.post_title || `Bài #${r.post_id}`}</button> : null}
                    {r.images > 0 && <small>🖼 {r.images}</small>}
                    {r.ai && <small className="ap-runs__ai">{r.ai}</small>}
                    {r.link && <a className="qt-link" href={r.link} target="_blank" rel="noreferrer">Xem trên Facebook ↗</a>}
                    {(r.error || r.note) && <small className={r.error ? "ap-runs__err" : "ap-runs__note"}>{r.error || r.note}</small>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
