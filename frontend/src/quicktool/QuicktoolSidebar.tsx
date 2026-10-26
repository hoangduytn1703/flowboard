import { useLocation, useNavigate } from "react-router-dom";
import { AccountPanel } from "../components/AccountPanel";
import { UserChip } from "../components/UserChip";
import { CreditBadge } from "../components/CreditBadge";
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
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const homeActive = pathname === "/clips" || pathname === "/clips/new" || pathname === "/clips/from-video";
  const is = (path: string) => pathname === path || pathname.startsWith(path + "/");
  return (
    <aside className="qt-sidebar">
      <div className="qt-brand">
        <span className="qt-brand__logo">⚡</span>
        <span className="qt-brand__name">Flowboard</span>
        <span className="qt-brand__badge">Quicktool</span>
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

        <div className="qt-nav__group">Công cụ</div>
        <button type="button" className={`qt-nav__item${is("/tools/dub") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/tools/dub")}
                title="Dán link video nước ngoài → bỏ tiếng gốc, đọc lại bằng giọng Việt, in phụ đề hộp vàng, lưu thành clip">
          <span className="qt-nav__icon">🎙</span> Lồng tiếng video
        </button>
        <button type="button" className={`qt-nav__item${is("/schedule") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/schedule")}
                title="Lịch tuần: bài viết và clip đăng lúc nào, giờ vàng theo nền tảng, nhắc đến giờ, tự đăng lên Facebook Page">
          <span className="qt-nav__icon">📅</span> Lịch đăng
        </button>
        <button type="button" className={`qt-nav__item${is("/posts") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/posts")}
                title="Viết bài đăng Facebook kiếm tương tác: điền mẫu hoặc chat với AI, tạo ảnh kèm">
          <span className="qt-nav__icon">✍️</span> Bài viết Facebook
        </button>
        <button type="button" className={`qt-nav__item${is("/swipes") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/swipes")}
                title="Dán link bài / video đang hot → AI chỉ ra vì sao nó chạy, rồi viết bài / clip của bạn theo cấu trúc đó">
          <span className="qt-nav__icon">🔥</span> Mẫu đang hot
        </button>
        <button type="button" className={`qt-nav__item${is("/tools/clean") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/tools/clean")}
                title="Xoá logo, watermark, phụ đề cứng khỏi video có sẵn">
          <span className="qt-nav__icon">🧽</span> Xoá chữ / logo
        </button>

        <div className="qt-nav__group">Thư viện</div>
        <button type="button" className={`qt-nav__item${is("/channels") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/channels")}
                title="Các page / tài khoản bạn đăng bài: bán gì, cho ai, giọng nào — AI bám theo khi viết bài, và tự brainstorm định hướng sau vài bài">
          <span className="qt-nav__icon">📣</span> Kênh của tôi
        </button>
        <button type="button" className={`qt-nav__item${is("/products") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/products")}>
          <span className="qt-nav__icon">🛍️</span> Sản phẩm đang bán
        </button>
        <button type="button" className={`qt-nav__item${is("/models") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/models")}
                title="Người mẫu đã lưu ở bước 1 — dùng lại cho sản phẩm khác">
          <span className="qt-nav__icon">👤</span> Người mẫu đã lưu
        </button>
        <button type="button" className={`qt-nav__item${is("/prompts") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/prompts")}
                title="Prompt ảnh / chuyển động / lời thoại đã lưu ở bước 2 — dùng lại cho clip khác">
          <span className="qt-nav__icon">📚</span> Prompt đã lưu
        </button>
        <button type="button" className={`qt-nav__item${is("/history") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/history")}
                title="Mọi lần tạo ảnh/video/ghép: trạng thái, credit, tải lại media, thử lại">
          <span className="qt-nav__icon">🕘</span> Lịch sử & credit
        </button>

        <div className="qt-nav__group">Nâng cao</div>
        {CANVAS_IN_MENU && (
          <button type="button" className="qt-nav__item" onClick={() => { setUiMode("canvas"); navigate(boardId !== null ? `/canvas/${boardId}` : "/canvas"); }}
                  title="Bảng node kéo thả — chỉnh từng node, nối dây, chat AI">
            <span className="qt-nav__icon">🧩</span> Canvas (kéo thả node)
          </button>
        )}
        <button type="button" className={`qt-nav__item${is("/settings") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/settings")}
                title="Model ảnh/video, AI provider, Flow project">
          <span className="qt-nav__icon">⚙</span> Cài đặt
        </button>
      </nav>

      <div className="qt-sidebar__credit"><CreditBadge /></div>
      <UserChip />
      <AccountPanel />
    </aside>
  );
}
