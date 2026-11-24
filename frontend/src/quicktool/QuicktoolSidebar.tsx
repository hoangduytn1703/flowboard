import { useLocation, useNavigate } from "react-router-dom";
import { AccountPanel } from "../components/AccountPanel";
import { UserChip } from "../components/UserChip";
import { FlowPill } from "../components/SetupGuide";
import { useAccountStore } from "../store/account";
import { hasFeature } from "../lib/features";
import { useBoardStore } from "../store/board";
import { useSettingsStore } from "../store/settings";

/**
 * Left rail of the Quicktool screen, modelled on the reference app: a
 * brand block, "Clip của tôi" (its page has the "+ Clip mới" button that opens the dialog that picks
 * the clip kind), the libraries, and the switch to the node canvas underneath.
 */
/** Canvas is hidden from the menu for now (the route /canvas still works); set true to show it again. */
const CANVAS_IN_MENU = false;

export function QuicktoolSidebar() {
  const setUiMode = useSettingsStore((s) => s.setUiMode);
  const boardId = useBoardStore((s) => s.boardId);
  const isAdmin = useAccountStore((s) => !!s.me?.is_admin);
  const me = useAccountStore((s) => s.me);
  const on = (key: Parameters<typeof hasFeature>[1]) => hasFeature(me, key);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const homeActive = pathname === "/clips" || pathname === "/clips/new" || pathname === "/clips/from-video";
  const is = (path: string) => pathname === path || pathname.startsWith(path + "/");
  // "🎞 Xử lý video" is one entry for the hub and every tool behind its tabs
  const videoTools = pathname === "/tools" || ["/tools/dub", "/tools/cut", "/tools/edit", "/tools/clean"].some(is);
  return (
    <aside className="qt-sidebar">
      <div className="qt-brand">
        <img className="qt-brand__logo" src="/dflow-logo.png" alt="" />
        <span className="qt-brand__name dflow-wordmark" aria-label="DFlow"><span className="dflow-wordmark__d">D</span>FLOW</span>
      </div>

      <nav className="qt-nav">
        <button type="button" className={`qt-nav__item${is("/today") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/today")}>
          <span className="qt-nav__icon">📋</span> Hôm nay
        </button>
        <button
          type="button"
          className={`qt-nav__item${homeActive ? " qt-nav__item--active" : ""}`}
          onClick={() => navigate("/clips")}
        >
          <span className="qt-nav__icon">🎬</span> Clip của tôi
        </button>

        {(on("dub") || on("cut") || on("clean") || on("grab")) && <div className="qt-nav__group">Video có sẵn</div>}
        {(on("dub") || on("cut") || on("clean")) && (
          <button type="button" className={`qt-nav__item${videoTools ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/tools")}
                  title="Video bạn đã có (link, file, clip): lồng tiếng Việt, thêm phụ đề, cắt thành video ngắn, chỉnh sửa, xoá chữ / logo">
            <span className="qt-nav__icon">🎞</span> Xử lý video
          </button>
        )}
        {on("grab") && <button type="button" className={`qt-nav__item${is("/tools/grab") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/tools/grab")}
                title="Dán link kênh YouTube / TikTok / Douyin → xem video kèm lượt xem, ngày đăng; lọc hoặc nhờ AI chọn rồi đem lồng tiếng / cắt">
          <span className="qt-nav__icon">📡</span> Cào video kênh
        </button>}
        {on("capcut") && <button type="button" className={`qt-nav__item${is("/tools/capcut") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/tools/capcut")}
                title="Biến video lồng tiếng / clip / video của bạn thành dự án CapCut: phụ đề, chữ nhấn mạnh, zoom, âm thanh — mở CapCut chỉnh tiếp">
          <span className="qt-nav__icon">🎞</span> Edit auto CapCut
        </button>}

        <div className="qt-nav__group">Đăng bài</div>
        {on("posts") && <button type="button" className={`qt-nav__item${is("/posts") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/posts")}
                title="Viết bài đăng Facebook (AI viết theo sản phẩm, kênh, clip), đăng ngay, lên lịch hoặc để tool tự đăng theo lịch">
          <span className="qt-nav__icon qt-nav__icon--fb" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M13.5 21v-7.5h2.5l.4-3h-2.9V8.6c0-.9.3-1.4 1.5-1.4h1.5V4.5c-.3 0-1.2-.1-2.2-.1-2.2 0-3.7 1.3-3.7 3.8v2.3H8.1v3h2.5V21h2.9z" /></svg>
          </span> Bài viết Facebook
        </button>}
        {on("facebook") && <button type="button" className={`qt-nav__item${is("/schedule") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/schedule")}
                title="Lịch tuần: bài viết và clip đăng lúc nào, giờ vàng theo nền tảng, nhắc đến giờ, tự đăng lên Facebook Page">
          <span className="qt-nav__icon">📅</span> Lịch đăng
        </button>}
        <button type="button" className={`qt-nav__item${is("/channels") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/channels")}
                title="Các page / tài khoản bạn đăng bài: bán gì, cho ai, giọng nào — AI bám theo khi viết bài, và tự brainstorm định hướng sau vài bài">
          <span className="qt-nav__icon">📣</span> Kênh của tôi
        </button>
        {on("swipes") && <button type="button" className={`qt-nav__item${is("/swipes") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/swipes")}
                title="Dán link bài / video đang viral → AI chỉ ra vì sao nó chạy, rồi viết bài / clip của bạn theo cấu trúc đó">
          <span className="qt-nav__icon">🔥</span> Học bài viral
        </button>}

        <div className="qt-nav__group">Kho của bạn</div>
        <button type="button" className={`qt-nav__item${is("/products") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/products")}>
          <span className="qt-nav__icon">🛍️</span> Sản phẩm đang bán
        </button>
        <button type="button" className={`qt-nav__item${is("/models") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/models")}
                title="Người mẫu đã lưu ở bước 1 — dùng lại cho sản phẩm khác">
          <span className="qt-nav__icon">👤</span> Người mẫu đã lưu
        </button>
        <button type="button" className={`qt-nav__item${is("/voices") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/voices")}
                title="Thu ~10 giây giọng của bạn — giọng đó đọc lời thoại, lồng tiếng… (VieNeu, chạy trên máy)">
          <span className="qt-nav__icon">🧬</span> Giọng nhân bản
        </button>
        <button type="button" className={`qt-nav__item${is("/prompts") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/prompts")}
                title="Prompt ảnh / chuyển động / lời thoại đã lưu ở bước 2 — dùng lại cho clip khác">
          <span className="qt-nav__icon">📚</span> Prompt đã lưu
        </button>

        <div className="qt-nav__group">Khác</div>
        <button type="button" className={`qt-nav__item${is("/history") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/history")}
                title="Mọi lần tạo ảnh/video/ghép: trạng thái, credit, tải lại media, thử lại">
          <span className="qt-nav__icon">🕘</span> Lịch sử & credit
        </button>
        {CANVAS_IN_MENU && (
          <button type="button" className="qt-nav__item" onClick={() => { setUiMode("canvas"); navigate(boardId !== null ? `/canvas/${boardId}` : "/canvas"); }}
                  title="Bảng node kéo thả — chỉnh từng node, nối dây, chat AI">
            <span className="qt-nav__icon">🧩</span> Canvas (kéo thả node)
          </button>
        )}
        {isAdmin && me?.site?.admin && (
          <a className="qt-nav__item" href={me.site.admin} target="_blank" rel="noreferrer"
             title={`Tài khoản, gói, giá và yêu cầu nâng cấp: quản lý trên ${me.site.host}`}>
            <span className="qt-nav__icon">👥</span> Quản lý tài khoản ↗
          </a>
        )}
        {isAdmin && !me?.site && (
          <button type="button" className={`qt-nav__item${is("/accounts") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/accounts")}
                  title="Chỉ tài khoản quản trị: tạo tài khoản cho người khác, đặt lại mật khẩu, khoá / mở khoá">
            <span className="qt-nav__icon">👥</span> Quản lý tài khoản
          </button>
        )}
        <button type="button" className={`qt-nav__item${is("/settings") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/settings")}
                title="Kiểu tạo ảnh / video, AI viết, dự án Flow, thư mục lưu video">
          <span className="qt-nav__icon">⚙</span> Cài đặt
        </button>
      </nav>

      {/* the footer: credit + who is signed in, the Flow account, then © + version as one block */}
      <div className="qt-sidebar__foot">
        <div className="qt-sidebar__credit"><FlowPill /></div>
        <UserChip />
        <AccountPanel />
      </div>
    </aside>
  );
}
