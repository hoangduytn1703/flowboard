import { useState } from "react";
import { connectFacebookPage, disconnectFacebookPage, inspectFacebookToken, type Channel } from "../../api/channels";
import { toast } from "../../store/toast";
import { invalidateChannels } from "./ChannelPicker";
import "../schedule.css";
import { askConfirm } from "../../components/Dialogs";

/**
 * "Kết nối Facebook Page": paste an access token, see which pages it can
 * post to, pick one. From then on calendar slots on this channel can be
 * published automatically. Only Pages — profiles and groups have no API.
 */
export function FacebookConnect({ channel, onUpdated }: { channel: Channel; onUpdated: (c: Channel) => void }) {
  const [token, setToken] = useState("");
  const [pages, setPages] = useState<{ id: string; name: string }[] | null>(null);
  const [pageId, setPageId] = useState("");
  const [busy, setBusy] = useState(false);
  const isFb = channel.platforms.includes("facebook");

  async function inspect() {
    setBusy(true);
    try {
      const info = await inspectFacebookToken(token.trim());
      setPages(info.pages);
      setPageId(info.pages[0]?.id ?? "");
      toast.info(info.kind === "page" ? `Token của Page "${info.pages[0]?.name}".` : `Token của ${info.name} — quản lý ${info.pages.length} Page.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function connect() {
    setBusy(true);
    try {
      const row = await connectFacebookPage(channel.id, token.trim(), pageId || undefined);
      invalidateChannels();
      onUpdated(row);
      setToken(""); setPages(null);
      toast.success(`Đã kết nối Page "${row.fb_page_name}". Lịch đăng của kênh này giờ tự đăng được.`, { duration: 8000 });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function disconnect() {
    if (!await askConfirm(`Ngắt kết nối Page "${channel.fb_page_name}"? Lịch đang chờ tự đăng sẽ không đăng được nữa.`)) return;
    setBusy(true);
    try {
      const row = await disconnectFacebookPage(channel.id);
      invalidateChannels();
      onUpdated(row);
      toast.success("Đã ngắt kết nối Facebook Page.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="qt-card qt-fbconnect">
      <div className="qt-card__head">
        <div>
          <h3 className="qt-card__title">⚡ Tự đăng lên Facebook Page</h3>
          <small className="qt-card__hint">Kết nối một lần, sau đó lịch đăng của kênh này tự lên bài đúng giờ (bài kèm ảnh, clip kèm video, bình luận đầu kèm link).</small>
        </div>
      </div>
      {channel.fb_connected ? (
        <div className="qt-fbconnect__on">
          <span>✅ Đang kết nối Page <strong>{channel.fb_page_name || channel.fb_page_id}</strong> <small className="qt-card__hint">(id {channel.fb_page_id})</small></span>
          <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" disabled={busy} onClick={() => void disconnect()} style={{ marginLeft: "auto" }}>Ngắt kết nối</button>
        </div>
      ) : (
        <>
          {!isFb && <p className="qt-card__hint">Kênh này không có nền tảng Facebook — chỉ Facebook Page mới tự đăng được (TikTok / Instagram: tool nhắc giờ, bạn đăng tay).</p>}
          <label className="qt-field">
            <span>Access token của Page (hoặc token người dùng là admin Page)</span>
            <textarea className="qt-textarea" rows={2} value={token} onChange={(e) => { setToken(e.target.value); setPages(null); }} placeholder="EAAB… (dán nguyên chuỗi)" />
          </label>
          {pages && pages.length > 1 && (
            <div className="qt-field">
              <span>Chọn Page để kết nối</span>
              <div className="qt-fbconnect__pages">
                {pages.map((p) => <button key={p.id} type="button" className={`qt-chip${p.id === pageId ? " qt-chip--on" : ""}`} onClick={() => setPageId(p.id)}>{p.name}</button>)}
              </div>
            </div>
          )}
          <div className="qt-post__actions">
            {!pages ? (
              <button type="button" className="qt-btn" disabled={busy || token.trim().length < 20} onClick={() => void inspect()}>{busy ? "Đang kiểm tra…" : "Kiểm tra token"}</button>
            ) : (
              <button type="button" className="qt-btn qt-btn--accent" disabled={busy || !pageId} onClick={() => void connect()}>{busy ? "Đang kết nối…" : `Kết nối Page${pages.length === 1 ? ` "${pages[0].name}"` : ""}`}</button>
            )}
          </div>
          <details>
            <summary className="qt-link">Lấy token thế nào? (khoảng 10 phút, miễn phí)</summary>
            <ol>
              <li>Vào <code>developers.facebook.com</code> → <strong>My Apps</strong> → <strong>Create App</strong> (loại Business / Other, đặt tên tuỳ ý). Không cần gửi duyệt: bạn là admin Page nên app ở chế độ Development vẫn đăng được lên Page của bạn.</li>
              <li>Mở <strong>Tools → Graph API Explorer</strong>, chọn app vừa tạo. Ở <em>User or Page</em> chọn <strong>Get Page Access Token</strong> → chọn Page.</li>
              <li>Thêm quyền: <code>pages_show_list</code>, <code>pages_manage_posts</code>, <code>pages_read_engagement</code>, <code>pages_manage_engagement</code> → <strong>Generate Access Token</strong>, đồng ý các bước.</li>
              <li>Copy chuỗi token dán vào ô trên → <strong>Kiểm tra token</strong> → <strong>Kết nối Page</strong>.</li>
              <li>Token Page lấy theo cách này thường <strong>không hết hạn</strong>. Nếu một ngày tool báo "token hết hạn", lặp lại bước 2–4 là xong.</li>
            </ol>
          </details>
        </>
      )}
    </section>
  );
}
