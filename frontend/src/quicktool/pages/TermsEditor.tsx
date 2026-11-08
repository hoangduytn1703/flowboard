import { discountPct, termLabel, vnd, type Plan, type PlanTerm } from "../../api/account";

function digits(text: string): number {
  return Number(text.replace(/\D/g, "")) || 0;
}

/** "49k / 1 tháng · 490k / 1 năm · 980k vĩnh viễn" — a plan's terms in one line (plan table header). */
export function termsSummary(terms: PlanTerm[] | undefined): string {
  if (!terms?.length) return "chưa có giá";
  const k = (n: number) => (n >= 1000 ? `${Math.round(n / 1000).toLocaleString("vi-VN")}k` : `${n}đ`);
  return terms.map((t) => (t.months ? `${k(t.price)}/${termLabel(t.months)}` : `${k(t.price)} vĩnh viễn`)).join(" · ");
}

/**
 * "💰 Thời hạn & giá bán" (part of "📦 Gói & tính năng"): every paid plan lists the terms it is sold for — 1 / 3 / 6
 * months, 1 / 2 years, forever — each with a price and an optional list price (struck through, to show the saving), with
 * a preview of what the buyer sees. A plan with no term shows "Liên hệ" and cannot be bought in the app.
 */
export function TermsEditor({ plans, termMonths, onChange }: {
  plans: Plan[];
  termMonths: number[];
  onChange: (planId: string, terms: PlanTerm[]) => void;
}) {
  return (
    <div className="bill__pricing">
      <h4>💰 Thời hạn & giá bán của từng gói</h4>
      <p className="bill__hint">
        Một gói bán được nhiều thời hạn, ví dụ VIP: 1 tháng 49.000đ · 1 năm 490.000đ · Vĩnh viễn 980.000đ. <b>Giá gốc</b> là giá trước khi giảm — khách thấy gạch
        ngang kèm % giảm và giá quy ra mỗi tháng. Khách mua thời hạn nào thì tài khoản được dùng tới hết thời hạn đó (bạn đổi được ở bảng tài khoản); hết hạn là
        không đăng nhập được. Gói không có dòng giá nào = “Liên hệ” (khách không tự mua được). Gói Dùng thử không bán.
      </p>
      {plans.map((p) => {
        const terms = p.terms ?? [];
        const used = new Set(terms.map((t) => t.months));
        const free = termMonths.filter((m) => !used.has(m));
        const set = (next: PlanTerm[]) => onChange(p.id, next);
        return (
          <div key={p.id} className="bill__plan">
            <div className="bill__planhead">
              <b>{p.name}</b>
              <span>{terms.length ? termsSummary(terms) : "chưa có giá — khách thấy “Liên hệ”"}</span>
              <button type="button" className="qt-btn qt-btn--small" disabled={!free.length}
                      onClick={() => set([...terms, { months: free[0], price: 0, list_price: 0 }])}>＋ Thêm thời hạn</button>
            </div>
            {terms.length > 0 && (
              <div className="bill__terms" role="table">
                <div className="bill__term bill__term--head" role="row">
                  <span>Thời hạn</span><span>Giá bán</span><span>Giá gốc (gạch ngang)</span><span>Khách thấy</span><span />
                </div>
                {terms.map((t, i) => {
                  const off = discountPct(t);
                  const edit = (patch: Partial<PlanTerm>) => set(terms.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                  return (
                    <div key={`${t.months}-${i}`} className="bill__term" role="row">
                      <select value={t.months} aria-label="Thời hạn" onChange={(e) => edit({ months: Number(e.target.value) })}>
                        {termMonths.filter((m) => m === t.months || !used.has(m)).map((m) => <option key={m} value={m}>{termLabel(m)}</option>)}
                      </select>
                      <label className="bill__money">
                        <input value={t.price ? t.price.toLocaleString("vi-VN") : ""} inputMode="numeric" placeholder="vd: 49.000" aria-label="Giá bán"
                               onChange={(e) => edit({ price: digits(e.target.value) })} />
                        <span>đ</span>
                      </label>
                      <label className="bill__money">
                        <input value={t.list_price ? t.list_price.toLocaleString("vi-VN") : ""} inputMode="numeric" placeholder="không giảm giá" aria-label="Giá gốc"
                               onChange={(e) => edit({ list_price: digits(e.target.value) })} />
                        <span>đ</span>
                      </label>
                      <span className="bill__seen">
                        {!t.price ? <i className="bill__warn">nhập giá bán (trống sẽ bỏ khi lưu)</i> : (
                          <>
                            {t.list_price > t.price && <s>{vnd(t.list_price)}</s>} <b>{vnd(t.price)}</b>
                            {off > 0 && <em>-{off}%</em>}
                            {t.list_price > 0 && t.list_price <= t.price && <i className="bill__warn">giá gốc phải cao hơn giá bán</i>}
                            {t.months >= 3 && <small>≈ {vnd(Math.round(t.price / t.months / 1000) * 1000)}/tháng</small>}
                          </>
                        )}
                      </span>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--danger" aria-label={`Bỏ thời hạn ${termLabel(t.months)}`}
                              onClick={() => set(terms.filter((_, j) => j !== i))}>🗑</button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
