import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  addMonths, agentDate, cancelUpgrade, dayText, discountPct, fileUpgrade, getAccountMe, getUpgradeOffer, quoteUpgrade, termLabel,
  timeLeft, vnd, type PlanTerm, type UpgradeOffer, type UpgradeQuote,
} from "../api/account";
import { useAccountStore } from "../store/account";
import { qrDataUrl } from "../lib/qr";
import { toast } from "../store/toast";

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`Đã copy ${what}.`);
  } catch {
    toast.warning("Không copy được — chọn chữ rồi Ctrl+C.");
  }
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return d.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}

function shortVnd(n: number): string {
  return n >= 1000 ? `${Math.round(n / 1000).toLocaleString("vi-VN")}k` : `${n}đ`;
}

/** The timed term with the lowest price per month, when there are at least two to compare. */
function bestValue(terms: PlanTerm[]): number | null {
  const timed = terms.filter((t) => t.months > 0);
  if (timed.length < 2) return null;
  return timed.reduce((a, b) => (b.price / b.months < a.price / a.months ? b : a)).months;
}

function defaultTerm(terms: PlanTerm[]): number {
  return bestValue(terms) ?? terms[0]?.months ?? 0;
}

/**
 * "⬆ Nâng cấp gói": the plans side by side — each with its terms (1 / 3 / 6 months, 1 / 2 years, forever), the price
 * with the list price struck through and the saving, what it costs per month, and the end date it buys → "Nâng cấp"
 * shows a VietQR with the amount and transfer text → "Tôi đã chuyển khoản" files a request; the admin checks the bank
 * statement and moves the account by hand. The plan the account is on can be renewed (time left is kept).
 */
export function UpgradeDialog({ onClose }: { onClose: () => void }) {
  const [offer, setOffer] = useState<UpgradeOffer | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<Record<string, number>>({});
  const [quote, setQuote] = useState<UpgradeQuote | null>(null);
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState("");

  const load = () => {
    // the plan may have changed since the page loaded (the admin approved an upgrade): refresh what the app shows
    void getAccountMe().then((me) => useAccountStore.getState().setMe(me)).catch(() => undefined);
    return getUpgradeOffer().then((o) => {
      setOffer(o);
      setPicked((prev) => Object.fromEntries(o.plans.map((p) => [p.id, p.terms.some((t) => t.months === prev[p.id]) ? prev[p.id] : defaultTerm(p.terms)])));
    }).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    setQr("");
    if (quote) void qrDataUrl(quote.qr, 300).then(setQr).catch(() => setQr(""));
  }, [quote]);

  async function pick(planId: string, months: number) {
    setBusy(planId);
    try {
      setQuote(await quoteUpgrade(planId, months));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function done() {
    if (!quote) return;
    setBusy("done");
    try {
      await fileUpgrade(quote.plan_id, quote.months);
      setQuote(null);
      await load();
      toast.success("Đã gửi yêu cầu. Người quản lý kiểm tra tiền xong sẽ nâng / gia hạn gói cho bạn.", { duration: 8000 });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function withdraw() {
    setBusy("cancel");
    try {
      await cancelUpgrade();
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  const currentEnd = agentDate(offer?.current.expires_at);
  /** where the term would end: renewing keeps the time left, another plan counts from today */
  const endFor = (planId: string, months: number): Date | null => {
    if (!months) return null;
    const now = new Date();
    const base = offer && planId === offer.current.id && currentEnd && currentEnd > now ? currentEnd : now;
    return addMonths(base, months);
  };
  const featureName = (key: string) => offer?.features.find((f) => f.key === key);
  const curLeft = timeLeft(offer?.current.expires_at);
  return createPortal(
    <div className="project-modal-backdrop up-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="project-modal up" role="dialog" aria-modal="true" aria-label="Nâng cấp gói">
        <div className="up__head">
          <h3>{quote ? `${quote.renew ? "↻ Gia hạn" : "⬆ Nâng cấp lên"} ${quote.plan_name} · ${quote.term}` : "⬆ Nâng cấp / gia hạn gói"}</h3>
          {offer && !quote && (
            <span className="up__current">Đang dùng: <b>{offer.current.name}</b>
              {offer.current.expires_at ? ` · ${curLeft.text} (tới ${dayText(offer.current.expires_at)})` : offer.current.trial ? "" : " · vĩnh viễn"}
            </span>
          )}
          <button type="button" className="up__close" aria-label="Đóng" onClick={onClose}>×</button>
        </div>

        {error && <div className="login__error">{error}</div>}
        {!offer && !error && <div className="up__loading">Đang tải các gói…</div>}

        {offer && !quote && (
          <>
            {offer.pending && (
              <div className="up__pending">
                ⏳ Đã gửi yêu cầu <b>{offer.pending.plan_name} · {offer.pending.term}</b> ({vnd(offer.pending.amount)}) lúc {when(offer.pending.created_at)} —
                người quản lý đang kiểm tra tiền.
                <button type="button" className="qt-link" disabled={busy === "cancel"} onClick={() => void withdraw()}>Huỷ yêu cầu</button>
              </div>
            )}
            {offer.current.trial && (
              <div className="up__trial">
                Bạn đang dùng thử — hết hạn là không đăng nhập được nữa. Chọn một gói dưới đây để dùng tiếp, không mất dữ liệu.
              </div>
            )}
            {!offer.current.trial && offer.current.expires_at && (
              <div className="up__trial">
                Gói <b>{offer.current.name}</b> hết hạn ngày <b>{dayText(offer.current.expires_at)}</b> — hết hạn là không đăng nhập được. Gia hạn ở thẻ
                “Đang dùng” (thời gian còn lại được cộng dồn) hoặc chọn gói khác.
              </div>
            )}
            {!offer.ready && <div className="up__pending">Người quản lý chưa cài đặt tài khoản nhận tiền — liên hệ người quản lý DFlow để nâng gói.</div>}
            <div className="up__plans">
              {offer.plans.map((p) => {
                const lifetimeNow = p.current && !offer.current.expires_at;
                const months = picked[p.id] ?? defaultTerm(p.terms);
                const term = p.terms.find((t) => t.months === months) ?? p.terms[0];
                const best = bestValue(p.terms);
                const end = term ? endFor(p.id, term.months) : null;
                const off = term ? discountPct(term) : 0;
                return (
                  <div key={p.id} className={`up__plan${p.current ? " up__plan--current" : ""}`}>
                    <div className="up__planhead">
                      <b>{p.name}</b>
                      {p.current && <span className="up__tag">Đang dùng</span>}
                    </div>
                    {lifetimeNow ? (
                      <div className="up__forever">✓ Bạn dùng gói này <b>vĩnh viễn</b></div>
                    ) : !term ? (
                      <div className="up__price">Liên hệ</div>
                    ) : (
                      <>
                        <div className="up__bigprice">
                          <span className="up__price">{vnd(term.price)}</span>
                          {term.list_price > term.price && <s className="up__list">{vnd(term.list_price)}</s>}
                          {off > 0 && <span className="up__off">-{off}%</span>}
                        </div>
                        <div className="up__ends">
                          {term.months ? <>Dùng <b>{termLabel(term.months)}</b> · hết hạn <b>{end ? dayText(end.toISOString()) : ""}</b></>
                            : <>Mua một lần, <b>dùng vĩnh viễn</b></>}
                          {term.months >= 3 && <span className="up__per"> · ≈ {shortVnd(Math.round(term.price / term.months))}/tháng</span>}
                        </div>
                        {p.terms.length > 1 && (
                          <div className="up__terms" role="radiogroup" aria-label={`Thời hạn gói ${p.name}`}>
                            {p.terms.map((t) => {
                              const d = discountPct(t);
                              return (
                                <button key={t.months} type="button" role="radio" aria-checked={t.months === term.months}
                                        className={`up__term${t.months === term.months ? " is-on" : ""}`}
                                        onClick={() => setPicked((s) => ({ ...s, [p.id]: t.months }))}>
                                  <span className="up__termname">{termLabel(t.months)}{best === t.months && <em>Tiết kiệm nhất</em>}</span>
                                  <span className="up__termprice">
                                    {t.list_price > t.price && <s>{shortVnd(t.list_price)}</s>}
                                    <b>{shortVnd(t.price)}</b>
                                    {d > 0 && <i>-{d}%</i>}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </>
                    )}
                    <ul className="up__feats">
                      {offer.features.map((f) => {
                        const on = p.features.includes(f.key);
                        return <li key={f.key} className={on ? "is-on" : ""}><span aria-hidden="true">{on ? "✓" : "—"}</span> {f.icon} {f.label}</li>;
                      })}
                    </ul>
                    {lifetimeNow ? (
                      <button type="button" className="qt-btn qt-btn--ghost" disabled>Gói hiện tại</button>
                    ) : (
                      <button type="button" className="qt-btn qt-btn--accent" disabled={!offer.ready || !term || busy !== ""}
                              title={!term ? "Gói này chưa có giá — liên hệ người quản lý" : undefined}
                              onClick={() => term && void pick(p.id, term.months)}>
                        {busy === p.id ? "Đang tạo mã…" : !term ? "Liên hệ người quản lý"
                          : `${p.current ? "Gia hạn" : "Nâng cấp lên"} ${p.name} · ${termLabel(term.months)}`}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="up__foot">Làm clip, sản phẩm, người mẫu, prompt thì gói nào cũng có. Hết hạn gói là không đăng nhập được cho tới khi gia hạn.</p>
          </>
        )}

        {quote && (
          <div className="up__pay">
            <div className="up__qr">
              {qr ? <img src={qr} alt={`Mã QR chuyển ${vnd(quote.amount)} tới ${quote.bank_name}`} width={300} height={300} /> : <div className="up__qrwait">Đang vẽ mã…</div>}
              <small>Mở app ngân hàng → Quét mã QR. Số tiền và nội dung đã điền sẵn.</small>
            </div>
            <dl className="up__info">
              <div><dt>Gói</dt><dd><b>{quote.plan_name}</b> · {quote.term}{quote.renew ? " (gia hạn, cộng dồn thời gian còn lại)" : ""}</dd></div>
              <div><dt>Hết hạn</dt><dd>{quote.ends_at ? <b>{dayText(quote.ends_at)}</b> : <b>Không bao giờ — dùng vĩnh viễn</b>}</dd></div>
              <div><dt>Ngân hàng</dt><dd>{quote.bank_name}</dd></div>
              <div><dt>Số tài khoản</dt><dd><b>{quote.account_no}</b> <button type="button" className="qt-link" onClick={() => void copy(quote.account_no, "số tài khoản")}>Copy</button></dd></div>
              {quote.account_name && <div><dt>Chủ tài khoản</dt><dd>{quote.account_name}</dd></div>}
              <div><dt>Số tiền</dt><dd><b className="up__amount">{vnd(quote.amount)}</b>
                {quote.list_price > quote.amount && <> <s className="up__list">{vnd(quote.list_price)}</s></>}
                {" "}<button type="button" className="qt-link" onClick={() => void copy(String(quote.amount), "số tiền")}>Copy</button></dd></div>
              <div><dt>Nội dung</dt><dd><b className="up__content">{quote.content}</b> <button type="button" className="qt-link" onClick={() => void copy(quote.content, "nội dung")}>Copy</button></dd></div>
              <div className="up__gets"><dt>Gói {quote.plan_name} có</dt>
                <dd>{(offer?.plans.find((p) => p.id === quote.plan_id)?.features ?? []).map((k) => featureName(k)).filter(Boolean).map((f) => `${f!.icon} ${f!.label}`).join(" · ") || "—"}</dd>
              </div>
              {quote.note && <p className="up__note">{quote.note}</p>}
              <p className="up__note">Chuyển <b>đúng số tiền và nội dung</b> để người quản lý nhận ra nhanh. Chuyển xong bấm nút dưới.</p>
              <div className="up__btns">
                <button type="button" className="qt-btn qt-btn--accent qt-btn--big" disabled={busy === "done"} onClick={() => void done()}>
                  {busy === "done" ? "Đang gửi…" : "✓ Tôi đã chuyển khoản"}
                </button>
                <button type="button" className="qt-btn qt-btn--ghost" disabled={busy === "done"} onClick={() => setQuote(null)}>← Chọn gói khác</button>
              </div>
            </dl>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
