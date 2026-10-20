import { useLocation, useNavigate } from "react-router-dom";
import { AccountPanel } from "../components/AccountPanel";
import { useBoardStore } from "../store/board";
import { useSettingsStore } from "../store/settings";

/**
 * Left rail of the Quicktool screen, modelled on the reference app: a
 * brand block, the one "Công cụ nhanh" entry (its dialog picks the clip
 * kind), the libraries, and the switch to the node canvas underneath.
 */
export function QuicktoolSidebar() {
  const setUiMode = useSettingsStore((s) => s.setUiMode);
  const boardId = useBoardStore((s) => s.boardId);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const homeActive = pathname === "/clips";
  const is = (path: string) => pathname === path || pathname.startsWith(path + "/");
  return (
    <aside className="qt-sidebar">
      <div className="qt-brand">
        <span className="qt-brand__logo">⚡</span>
        <span className="qt-brand__name">Flowboard</span>
        <span className="qt-brand__badge">Quicktool</span>
      </div>

      <nav className="qt-nav">
        <button
          type="button"
          className={`qt-nav__item${homeActive ? " qt-nav__item--active" : ""}`}
          onClick={() => navigate("/clips")}
        >
          <span className="qt-nav__icon">🎬</span> Clip của tôi
        </button>

        <button
          type="button"
          className={`qt-nav__item${is("/clips/new") || is("/clips/from-video") ? " qt-nav__item--active" : ""}`}
          onClick={() => navigate("/clips/new")}
          title="Tạo clip quảng cáo mới: chọn sản phẩm và kiểu clip (mỹ phẩm, quần áo, đồ ăn, review, theo video mẫu, theo link)"
        >
          <span className="qt-nav__icon">⚡</span> Công cụ nhanh
        </button>

        <div className="qt-nav__group">Thư viện</div>
        <button type="button" className={`qt-nav__item${is("/products") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/products")}>
          <span className="qt-nav__icon">🛍️</span> Sản phẩm đang bán
        </button>

        <div className="qt-nav__group">Nâng cao</div>
        <button type="button" className="qt-nav__item" onClick={() => { setUiMode("canvas"); navigate(boardId !== null ? `/canvas/${boardId}` : "/canvas"); }}
                title="Bảng node kéo thả — chỉnh từng node, nối dây, chat AI">
          <span className="qt-nav__icon">🧩</span> Canvas (kéo thả node)
        </button>
        <button type="button" className={`qt-nav__item${is("/settings") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/settings")}
                title="Model ảnh/video, AI provider, Flow project">
          <span className="qt-nav__icon">⚙</span> Cài đặt
        </button>
      </nav>

      <AccountPanel />
    </aside>
  );
}
