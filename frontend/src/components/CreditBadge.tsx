// Small pill showing the Flow credit balance. Click = re-scan the extension
// and re-read the balance. Styles live in quicktool/history.css
// (`.credit-badge*`) so the page and the sidebar share one import.
import "../quicktool/history.css";
import { tierLabel, useFlowCredits } from "./credits";

export const LOW_CREDITS_THRESHOLD = 100;

interface CreditBadgeProps {
  className?: string;
}

export function CreditBadge({ className }: CreditBadgeProps) {
  const { credits, tier, sku, email, loading, error, refresh } = useFlowCredits();
  const known = typeof credits === "number";
  const low = known && credits < LOW_CREDITS_THRESHOLD;
  const text = known ? credits.toLocaleString("vi-VN") : "—";
  const titleParts = [
    `Gói Flow: ${tierLabel(tier, sku)}`,
    email ? `Tài khoản: ${email}` : "Tài khoản: chưa đọc được",
    known ? `${text} credit còn lại` : "Chưa đọc được số credit (mở tab flow.google.com rồi bấm để quét lại)",
    error ? `Lỗi: ${error}` : null,
    "Bấm để cập nhật",
  ].filter(Boolean);
  const cls = [
    "credit-badge",
    low ? "credit-badge--low" : "",
    loading ? "credit-badge--busy" : "",
    className ?? "",
  ].filter(Boolean).join(" ");

  return (
    <button
      type="button"
      className={cls}
      title={titleParts.join("\n")}
      aria-label={`Credit Flow: ${text}. Bấm để cập nhật`}
      onClick={() => { void refresh(); }}
      disabled={loading}
    >
      {loading ? <span className="credit-badge__spinner" aria-hidden="true" /> : <span aria-hidden="true">⚡</span>}
      <span className="credit-badge__num">{text}</span>
      <span className="credit-badge__unit">credit</span>
    </button>
  );
}

export default CreditBadge;
