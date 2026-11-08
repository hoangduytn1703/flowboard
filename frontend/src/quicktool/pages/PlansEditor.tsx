import { useEffect, useMemo, useState } from "react";
import { savePlans, type Plan, type PlanTerm, type PlansData } from "../../api/account";
import { askConfirm } from "../../components/Dialogs";
import { toast } from "../../store/toast";
import { TermsEditor, termsSummary } from "./TermsEditor";

function same(a: Plan[], b: Plan[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function newId(): string {
  return `goi-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * "📦 Gói & tính năng" (admin): features down, plans across — tick what each plan includes, rename / add / delete /
 * reorder plans; below, the terms each paid plan is sold for (1 month 49k, 1 year 490k, forever 980k…); then save once. The first column is the built-in trial ("Dùng thử"): every new account starts on it,
 * it is never bought, it cannot be moved or deleted, and its one extra setting is how many days it lasts.
 * Accounts on a deleted plan move to the trial (starting that day).
 */
export function PlansEditor({ data, onSaved }: { data: PlansData; onSaved: (next: PlansData) => void }) {
  const saved = useMemo(() => data.plans, [data]);
  const [draft, setDraft] = useState<Plan[]>(saved);
  const [busy, setBusy] = useState(false);
  useEffect(() => setDraft(saved), [saved]);

  const dirty = !same(draft, saved);
  const names = draft.map((p) => p.name.trim().toLowerCase());
  const problem = draft.some((p) => !p.name.trim()) ? "Mỗi gói cần có tên."
    : new Set(names).size !== names.length ? "Hai gói trùng tên — đặt tên khác nhau."
    : "";
  const isTrial = (p: Plan) => p.id === data.trial_id;
  const trial = draft.find(isTrial);
  const trialName = trial?.name || "Dùng thử";

  function edit(id: string, patch: Partial<Plan>) {
    setDraft((d) => d.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }
  function toggle(id: string, key: string) {
    setDraft((d) => d.map((p) => p.id !== id ? p : {
      ...p, features: p.features.includes(key) ? p.features.filter((k) => k !== key) : data.features.map((f) => f.key).filter((k) => k === key || p.features.includes(k)),
    }));
  }
  /** move a paid plan one place left / right (the trial stays first) */
  function move(id: string, step: -1 | 1) {
    setDraft((d) => {
      const i = d.findIndex((p) => p.id === id);
      const j = i + step;
      if (i < 0 || j < 0 || j >= d.length || isTrial(d[i]) || isTrial(d[j])) return d;
      const next = [...d];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }
  function addPlan() {
    if (draft.length >= data.max_plans) { toast.warning(`Tối đa ${data.max_plans} gói.`); return; }
    let n = draft.length;
    while (names.includes(`gói ${n}`)) n += 1;
    setDraft((d) => [...d, { id: newId(), name: `Gói ${n}`, features: [], terms: [] }]);
  }
  function setTerms(id: string, terms: PlanTerm[]) {
    edit(id, { terms });
  }
  function removePlan(id: string) {
    setDraft((d) => d.filter((p) => p.id !== id || isTrial(p)));
  }

  async function save() {
    if (problem) { toast.warning(problem); return; }
    const kept = new Set(draft.map((p) => p.id));
    const moving = saved.filter((p) => !kept.has(p.id) && (data.counts[p.id] ?? 0) > 0);
    if (moving.length) {
      const list = moving.map((p) => `${p.name} (${data.counts[p.id]} tài khoản)`).join(", ");
      if (!(await askConfirm(
        `Xoá gói ${list}? Các tài khoản đó sẽ chuyển về gói "${trialName}" (${trial?.days ?? 7} ngày tính từ hôm nay) — hết hạn là không đăng nhập được.`,
        { ok: "Xoá và lưu", danger: true },
      ))) return;
    }
    setBusy(true);
    try {
      const next = await savePlans(draft.map((p) => ({ ...p, name: p.name.trim() })));
      onSaved(next);
      toast.success("Đã lưu các gói. Tài khoản đang mở app nhận gói mới khi tải lại trang (máy khác trong vòng 5 phút).");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const paid = draft.filter((p) => !isTrial(p));
  return (
    <section className="qt-card plans">
      <div className="qt-card__head">
        <div>
          <h3 className="qt-card__title">📦 Gói & tính năng</h3>
          <p className="qt-card__hint">
            Tick tính năng cho từng gói, rồi chọn gói cho từng tài khoản ở bảng trên. Làm clip, sản phẩm, người mẫu, prompt, lịch sử thì gói
            nào cũng có. Tài khoản quản trị (bạn) luôn có mọi tính năng. Thứ tự cột là thứ tự khách thấy ở màn hình nâng cấp — đổi bằng ◀ ▶.
          </p>
        </div>
        <button type="button" className="qt-btn qt-btn--small" disabled={draft.length >= data.max_plans} onClick={addPlan}>＋ Thêm gói</button>
      </div>

      {data.signed === "invalid" && (
        <div className="acc-lic acc-lic--nokey">
          ⚠ Bảng gói trên cơ sở dữ liệu <b>không khớp chữ ký</b> (có thể bị sửa tay): khách không xem được bảng giá và máy không ký quyền mới cho tới khi
          bạn kiểm tra bảng dưới rồi bấm <b>💾 Lưu gói</b>.
        </div>
      )}
      {data.can_sign === false && data.signed !== "missing" && (
        <p className="qt-card__hint">🔒 Máy này không có khoá ký — chỉ xem; sửa gói trên máy có khoá.</p>
      )}
      <div className="plans__wrap">
        <table className="plans__table">
          <thead>
            <tr>
              <th className="plans__featcol">Tính năng</th>
              {draft.map((p) => {
                const trialCol = isTrial(p);
                const k = paid.indexOf(p);
                return (
                  <th key={p.id} className={`plans__plan${trialCol ? " plans__plan--trial" : ""}`}>
                    <div className="plans__top">
                      {trialCol ? <span className="plans__tag" title="Gói có sẵn: tài khoản mới luôn bắt đầu ở đây, không bán, không xoá được">Dùng thử · mặc định</span>
                        : (
                          <span className="plans__order">
                            <button type="button" className="plans__mv" disabled={k <= 0} aria-label={`Đưa ${p.name} sang trái`} title="Đưa sang trái"
                                    onClick={() => move(p.id, -1)}>◀</button>
                            <span>#{k + 1}</span>
                            <button type="button" className="plans__mv" disabled={k >= paid.length - 1} aria-label={`Đưa ${p.name} sang phải`} title="Đưa sang phải"
                                    onClick={() => move(p.id, 1)}>▶</button>
                          </span>
                        )}
                    </div>
                    <input className="plans__name" value={p.name} maxLength={40} aria-label="Tên gói"
                           onChange={(e) => edit(p.id, { name: e.target.value })} />
                    {trialCol && (
                      <label className="plans__days" title="Tài khoản mới (và lần gia hạn) dùng thử bao nhiêu ngày. Hết hạn = không đăng nhập được.">
                        Hết hạn sau
                        <select value={p.days ?? 7} onChange={(e) => edit(p.id, { days: Number(e.target.value) })}>
                          {data.trial_days.map((n) => <option key={n} value={n}>{n} ngày</option>)}
                        </select>
                      </label>
                    )}
                    {!trialCol && <div className={`plans__price${p.terms?.length ? "" : " plans__price--none"}`} title="Sửa ở bảng Thời hạn & giá bán bên dưới">{termsSummary(p.terms)}</div>}
                    <div className="plans__meta"><span>{data.counts[p.id] ?? 0} tài khoản</span></div>
                    <div className="plans__quick">
                      <button type="button" className="qt-link" onClick={() => edit(p.id, { features: data.features.map((f) => f.key) })}>tất cả</button>
                      <button type="button" className="qt-link" onClick={() => edit(p.id, { features: [] })}>bỏ hết</button>
                      {!trialCol && (
                        <button type="button" className="qt-link plans__del" title="Xoá gói này" onClick={() => removePlan(p.id)}>🗑 xoá</button>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {data.features.map((f) => (
              <tr key={f.key}>
                <td className="plans__featcol">
                  <b>{f.icon} {f.label}</b>
                  <small>{f.desc}</small>
                </td>
                {draft.map((p) => {
                  const on = p.features.includes(f.key);
                  return (
                    <td key={p.id} className={`plans__cell${isTrial(p) ? " plans__cell--trial" : ""}`}>
                      <label className={`plans__tick${on ? " is-on" : ""}`} title={`${p.name}: ${on ? "có" : "không có"} ${f.label}`}>
                        <input type="checkbox" checked={on} onChange={() => toggle(p.id, f.key)} />
                        <span aria-hidden="true">{on ? "✓" : "—"}</span>
                      </label>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <TermsEditor plans={paid} termMonths={data.term_months} onChange={setTerms} />

      <p className="qt-card__hint">
        Gói <b>{trialName}</b>: tài khoản mới bắt đầu ở đây, không bán (không có ở màn hình nâng cấp). Đổi số ngày chỉ áp cho tài khoản tạo sau đó
        và lần bấm <b>Gia hạn</b> — tài khoản đang dùng thử giữ hạn cũ.
      </p>

      {(dirty || problem) && (
        <div className="plans__save">
          <span>{problem || "Có thay đổi chưa lưu."}</span>
          <button type="button" className="qt-btn qt-btn--accent" disabled={busy || !!problem} onClick={() => void save()}>
            {busy ? "Đang lưu…" : "💾 Lưu gói"}
          </button>
          <button type="button" className="qt-btn qt-btn--ghost" disabled={busy} onClick={() => setDraft(saved)}>Huỷ thay đổi</button>
        </div>
      )}
    </section>
  );
}
