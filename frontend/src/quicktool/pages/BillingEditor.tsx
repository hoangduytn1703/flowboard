import { useCallback, useEffect, useMemo, useState } from "react";
import {
  decideUpgrade, getBilling, saveBilling, vnd, type BillingData, type BillingSettings, type Plan, type UpgradeRequest,
} from "../../api/account";
import { askConfirm } from "../../components/Dialogs";
import { qrDataUrl } from "../../lib/qr";
import { toast } from "../../store/toast";

const OTHER = "__other__";
const STATUS: Record<string, string> = { pending: "⏳ Chờ duyệt", approved: "✓ Đã duyệt", rejected: "✗ Từ chối", cancelled: "Đã huỷ" };

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return d.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" });
}

/**
 * "💳 Thanh toán nâng cấp" (admin): where the money goes (bank + account), the transfer text template (the terms + prices
 * of each plan are on "📦 Gói & tính năng"), a sample QR to scan once with your own bank app, and the upgrade requests to approve by hand
 * after checking the bank statement (approving moves the account to that plan).
 */
export function BillingEditor({ plans, onDecided }: { plans: Plan[]; onDecided: () => void }) {
  const [data, setData] = useState<BillingData | null>(null);
  const [draft, setDraft] = useState<BillingSettings | null>(null);
  const [otherBin, setOtherBin] = useState(false);
  const [busy, setBusy] = useState("");
  const [qr, setQr] = useState("");
  const [showDone, setShowDone] = useState(false);

  const apply = useCallback((d: BillingData) => {
    setData(d);
    setDraft(d.settings);
    setOtherBin(!!d.settings.bank_bin && !d.banks.some((b) => b.bin === d.settings.bank_bin));
  }, []);
  useEffect(() => { getBilling().then(apply).catch((e) => toast.error(e instanceof Error ? e.message : String(e))); }, [apply]);
  useEffect(() => {
    setQr("");
    if (data?.sample.qr) void qrDataUrl(data.sample.qr, 220).then(setQr).catch(() => setQr(""));
  }, [data]);

  const dirty = useMemo(() => !!data && !!draft && JSON.stringify(draft) !== JSON.stringify(data.settings), [data, draft]);
  if (!data || !draft) return null;

  const set = (patch: Partial<BillingSettings>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const pending = data.requests.filter((r) => r.status === "pending");
  const done = data.requests.filter((r) => r.status !== "pending").slice(0, 30);
  const preview = (draft.template || data.default_template).replace("{username}", "tenkhach")
    .replace("{plan}", plans[plans.length - 1]?.name ?? "Premium").replace("{term}", "6 thang");

  async function save() {
    setBusy("save");
    try {
      apply(await saveBilling(draft!));
      toast.success("Đã lưu cài đặt thanh toán. Quét thử mã QR mẫu bằng app ngân hàng của bạn để chắc mã đúng.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function decide(r: UpgradeRequest, approve: boolean) {
    const { id, username, amount } = r;
    const planName = `${r.plan_name} · ${r.term}`;
    if (!(await askConfirm(approve
      ? `Đã nhận ${vnd(amount)} từ ${username}? Duyệt sẽ chuyển ${username} sang gói ${planName}${r.months ? " (nếu đang dùng đúng gói này thì cộng nối tiếp hạn cũ)" : ""}.`
      : `Từ chối yêu cầu ${planName} của ${username}? Gói của họ giữ nguyên.`,
    { ok: approve ? "Duyệt — nâng gói" : "Từ chối", danger: !approve }))) return;
    setBusy(`r${id}`);
    try {
      apply(await decideUpgrade(id, approve));
      toast.success(approve ? `Đã nâng ${username} lên gói ${planName}.` : "Đã từ chối yêu cầu.");
      onDecided();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  const bankValue = otherBin ? OTHER : draft.bank_bin;
  return (
    <section className="qt-card bill">
      <div className="qt-card__head">
        <div>
          <h3 className="qt-card__title">💳 Thanh toán nâng cấp {pending.length > 0 && <span className="bill__badge">{pending.length} chờ duyệt</span>}</h3>
          <p className="qt-card__hint">
            Người dùng bấm <b>⬆ Nâng cấp</b> → chọn gói → quét mã QR (số tiền + nội dung điền sẵn) → bấm <b>Tôi đã chuyển khoản</b>. Bạn kiểm tra
            tiền đã về chưa rồi bấm <b>Duyệt</b>: tài khoản lên gói đó ngay. Tool không tự kiểm tra tiền.
          </p>
        </div>
      </div>

      {data.signed === "invalid" && (
        <div className="acc-lic acc-lic--nokey">
          ⚠ Thông tin chuyển khoản trên cơ sở dữ liệu <b>không khớp chữ ký</b> (có thể bị sửa tay để đổi số tài khoản): khách sẽ không thấy mã QR cho tới khi
          bạn kiểm tra lại bên dưới rồi bấm <b>Lưu cài đặt thanh toán</b>.
        </div>
      )}
      {pending.length > 0 && (
        <div className="bill__requests">
          <h4>Yêu cầu chờ duyệt</h4>
          {pending.map((r) => (
            <div key={r.id} className="bill__req bill__req--pending">
              <span><b>{r.username}</b> → gói <b>{r.plan_name}</b> · {r.term}</span>
              <span className="bill__amount">{vnd(r.amount)}</span>
              <span className="bill__content" title="Nội dung chuyển khoản cần tìm trong sao kê">“{r.content}”</span>
              <span className="bill__when">{when(r.created_at)}</span>
              <span className="bill__acts">
                <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy !== ""}
                        onClick={() => void decide(r, true)}>✓ Duyệt</button>
                <button type="button" className="qt-btn qt-btn--small qt-btn--danger" disabled={busy !== ""}
                        onClick={() => void decide(r, false)}>✗ Từ chối</button>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="bill__grid">
        <div className="bill__form">
          <label className="qt-field">
            <span>Ngân hàng nhận tiền</span>
            <select value={bankValue} onChange={(e) => {
              if (e.target.value === OTHER) { setOtherBin(true); set({ bank_bin: "" }); }
              else { setOtherBin(false); set({ bank_bin: e.target.value }); }
            }}>
              <option value="">— Chọn ngân hàng —</option>
              {data.banks.map((b) => <option key={b.bin} value={b.bin}>{b.name}</option>)}
              <option value={OTHER}>Ngân hàng khác (nhập mã BIN)…</option>
            </select>
          </label>
          {otherBin && (
            <label className="qt-field">
              <span>Mã BIN của ngân hàng (6 số, tra theo chuẩn NAPAS / VietQR)</span>
              <input value={draft.bank_bin} inputMode="numeric" maxLength={8} placeholder="vd: 970436" onChange={(e) => set({ bank_bin: e.target.value.replace(/\D/g, "") })} />
            </label>
          )}
          <label className="qt-field">
            <span>Số tài khoản</span>
            <input value={draft.account_no} maxLength={19} inputMode="numeric" placeholder="vd: 0123456789" onChange={(e) => set({ account_no: e.target.value })} />
          </label>
          <label className="qt-field">
            <span>Tên chủ tài khoản (hiện cho người chuyển xem)</span>
            <input value={draft.account_name} maxLength={50} placeholder="vd: NGUYEN VAN A" onChange={(e) => set({ account_name: e.target.value })} />
          </label>
          <label className="qt-field">
            <span>Nội dung chuyển khoản</span>
            <input value={draft.template} maxLength={80} placeholder={data.default_template} onChange={(e) => set({ template: e.target.value })} />
            <small className="bill__hint"><code>{"{username}"}</code> = tên tài khoản, <code>{"{plan}"}</code> = tên gói, <code>{"{term}"}</code> = thời hạn mua. Ví dụ: “{preview}” — bỏ dấu tiếng Việt, tối đa {data.text_max} ký tự.
              {draft.template !== data.default_template && <> <button type="button" className="qt-link" onClick={() => set({ template: data.default_template })}>Về mặc định</button></>}</small>
          </label>
          <label className="qt-field">
            <span>Ghi chú hiện dưới mã QR (không bắt buộc)</span>
            <textarea rows={2} maxLength={300} value={draft.note} placeholder="vd: Chuyển xong nhắn Zalo 09xx để được duyệt nhanh"
                      onChange={(e) => set({ note: e.target.value })} />
          </label>
        </div>

        <div className="bill__sample">
          <h4>Mã QR mẫu</h4>
          {data.ready ? (
            <>
              {qr ? <img src={qr} alt="Mã QR mẫu" width={220} height={220} /> : <div className="bill__qrwait">Đang vẽ…</div>}
              <p>{data.bank_name} · {draft.account_no}<br />
                {data.sample.amount ? <>{data.sample.plan_name} · {data.sample.term} · {vnd(data.sample.amount)} · </> : <>chưa có giá · </>}“{data.sample.content}”</p>
              <small>Mở app ngân hàng của bạn quét thử (không cần chuyển) để chắc tên tài khoản, số tiền, nội dung hiện đúng.</small>
            </>
          ) : <p className="bill__hint">Chọn ngân hàng + số tài khoản rồi lưu để thấy mã mẫu.</p>}
        </div>
      </div>

      <p className="bill__hint">💰 Thời hạn & giá bán của từng gói đặt ở bảng <b>📦 Gói & tính năng</b> phía trên.</p>

      <div className="bill__save">
        <button type="button" className="qt-btn qt-btn--accent" disabled={!dirty || busy === "save"} onClick={() => void save()}>
          {busy === "save" ? "Đang lưu…" : dirty ? "💾 Lưu cài đặt thanh toán" : "✓ Đã lưu"}
        </button>
        {dirty && <button type="button" className="qt-btn qt-btn--ghost" onClick={() => apply(data)}>Huỷ thay đổi</button>}
      </div>

      {done.length > 0 && (
        <div className="bill__requests">
          <button type="button" className="qt-link" onClick={() => setShowDone((v) => !v)}>
            {showDone ? "▾" : "▸"} Lịch sử yêu cầu ({done.length})
          </button>
          {showDone && done.map((r) => (
            <div key={r.id} className={`bill__req bill__req--${r.status}`}>
              <span><b>{r.username}</b> → gói <b>{r.plan_name}</b> · {r.term}</span>
              <span className="bill__amount">{vnd(r.amount)}</span>
              <span className="bill__content">“{r.content}”</span>
              <span className="bill__when">{when(r.created_at)}</span>
              <span className="bill__acts">{STATUS[r.status] ?? r.status}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
