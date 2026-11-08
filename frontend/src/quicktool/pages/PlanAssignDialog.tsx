import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  addMonths, agentDate, dayText, termLabel, timeLeft, updateAccount, vnd, type ManagedAccount, type PlansData,
} from "../../api/account";
import { toast } from "../../store/toast";

function endText(end: Date | null): string {
  return end ? `hết hạn ${dayText(end.toISOString())}` : "không bao giờ hết hạn";
}

/** "YYYY-MM-DD" of a date in local time (what <input type=date> wants). */
function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

type Pick = { kind: "months"; months: number } | { kind: "days"; days: number } | { kind: "date" };

/**
 * "Gói & thời hạn" of one account (admin): pick the plan, then how long. A paid plan offers first the terms it is sold for
 * (with their price, from "📦 Gói & tính năng"), then the other lengths, then any end date; the trial offers 3 / 7 / 14 /
 * 30 days. The end date is shown before saving. Staying on the same plan can add the time onto what is left.
 */
export function PlanAssignDialog({ account, plans, onClose, onSaved }: {
  account: ManagedAccount;
  plans: PlansData;
  onClose: () => void;
  onSaved: () => void;
}) {
  const valid = (id: string | null) => !!id && plans.plans.some((p) => p.id === id);
  const startPlan = valid(account.plan) ? account.plan! : plans.default;
  const trialDays = plans.plans.find((p) => p.id === plans.trial_id)?.days ?? 7;
  const currentEnd = agentDate(account.plan_expires);
  const firstPick = (planId: string): Pick => {
    if (planId === plans.trial_id) return { kind: "days", days: trialDays };
    const sold = plans.plans.find((p) => p.id === planId)?.terms ?? [];
    return { kind: "months", months: sold[0]?.months ?? 1 };
  };
  const [planId, setPlanId] = useState(startPlan);
  const [pick, setPick] = useState<Pick>(() => firstPick(startPlan));
  const [day, setDay] = useState(() => isoDay(currentEnd && currentEnd > new Date() ? currentEnd : addMonths(new Date(), 1)));
  const [stack, setStack] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const plan = plans.plans.find((p) => p.id === planId);
  const trial = planId === plans.trial_id;
  const sold = plan?.terms ?? [];
  const others = plans.term_months.filter((m) => !sold.some((t) => t.months === m));
  const now = new Date();
  const samePlan = planId === startPlan;
  const timed = pick.kind === "days" || (pick.kind === "months" && pick.months > 0);
  const canStack = pick.kind !== "date" && samePlan && !!currentEnd && currentEnd > now && timed;
  const base = canStack && stack ? currentEnd! : now;
  const end = pick.kind === "date" ? new Date(`${day}T23:59:59`)
    : pick.kind === "days" ? new Date(base.getTime() + pick.days * 86_400_000)
      : pick.months ? addMonths(base, pick.months) : null;
  const pastDate = pick.kind === "date" && !!end && end < now;
  const left = timeLeft(account.plan_expires);
  const planName = plan?.name ?? planId;
  const pickText = pick.kind === "date" ? "chọn ngày" : pick.kind === "days" ? `${pick.days} ngày` : termLabel(pick.months);

  function choosePlan(id: string) {
    setPlanId(id);
    setPick(pick.kind === "date" ? pick : firstPick(id));
  }

  async function save() {
    if (pick.kind === "date" && !day) { toast.warning("Chọn ngày hết hạn."); return; }
    setBusy(true);
    try {
      const st = canStack && stack;
      await updateAccount(account.username, pick.kind === "date" ? { plan: planId, expires_on: day }
        : pick.kind === "days" ? { plan: planId, days: pick.days, stack: st } : { plan: planId, months: pick.months, stack: st });
      toast.success(`${account.username}: gói ${planName} · ${pickText}, ${endText(end)}.`);
      onSaved();
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  const chip = (on: boolean, label: ReactNode, onClick: () => void, extra = "") => (
    <button type="button" role="radio" aria-checked={on} className={`pa__chip${on ? " is-on" : ""}${extra}`} onClick={onClick}>{label}</button>
  );
  return createPortal(
    <div className="project-modal-backdrop pa-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <form className="project-modal pa" role="dialog" aria-modal="true" aria-label={`Gói của ${account.username}`}
            onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <h3 className="pa__title">Gói & thời hạn — {account.username}</h3>
        <p className="pa__now">
          Đang dùng: <b>{plans.plans.find((p) => p.id === startPlan)?.name ?? startPlan}</b>
          {account.plan_expires ? (left.over ? ` · đã hết hạn ${dayText(account.plan_expires)}` : ` · ${left.text} (tới ${dayText(account.plan_expires)})`) : " · vĩnh viễn"}
        </p>

        <div className="pa__label">Gói</div>
        <div className="pa__chips" role="radiogroup" aria-label="Gói">
          {plans.plans.map((p) => chip(p.id === planId, p.name, () => choosePlan(p.id), p.id === plans.trial_id ? " pa__chip--trial" : ""))}
        </div>

        <div className="pa__label">Thời hạn</div>
        <div className="pa__chips" role="radiogroup" aria-label="Thời hạn">
          {trial
            ? plans.trial_days.map((n) => chip(pick.kind === "days" && pick.days === n, `${n} ngày`, () => setPick({ kind: "days", days: n })))
            : sold.map((t) => chip(pick.kind === "months" && pick.months === t.months,
              <><span>{termLabel(t.months)}</span><small>{vnd(t.price)}</small></>,
              () => setPick({ kind: "months", months: t.months }), " pa__chip--sold"))}
          {chip(pick.kind === "date", "📅 Chọn ngày", () => setPick({ kind: "date" }), " pa__chip--date")}
        </div>
        {!trial && (
          <div className="pa__others">
            <span>{sold.length ? "Thời hạn khác (gói không bán, chỉ bạn gán):" : "Gói này chưa có giá — chọn thời hạn:"}</span>
            {others.map((m) => chip(pick.kind === "months" && pick.months === m, termLabel(m), () => setPick({ kind: "months", months: m }), " pa__chip--small"))}
          </div>
        )}
        {pick.kind === "date" && (
          <label className="pa__date">
            <span>Hết hạn vào cuối ngày</span>
            <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
        )}

        {canStack && (
          <label className="pa__stack">
            <input type="checkbox" checked={stack} onChange={(e) => setStack(e.target.checked)} />
            <span>Cộng nối tiếp thời gian còn lại (đang tới {dayText(account.plan_expires)}) — bỏ tick thì tính lại từ hôm nay</span>
          </label>
        )}

        <div className={`pa__result${end ? "" : " pa__result--forever"}${pastDate ? " pa__result--past" : ""}`}>
          <div>→ <b>{planName}</b> · {pickText} — <b>{endText(end)}</b></div>
          {pastDate ? <small>Ngày đã qua: tài khoản bị khoá ngay khi lưu.</small>
            : end && <small>Hết hạn là tài khoản không đăng nhập được cho tới khi bạn gia hạn.</small>}
        </div>

        <div className="pa__actions">
          <button type="button" className="qt-btn qt-btn--ghost" disabled={busy} onClick={onClose}>Huỷ</button>
          <button type="submit" className="qt-btn qt-btn--accent" disabled={busy}>{busy ? "Đang lưu…" : "💾 Lưu gói"}</button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
