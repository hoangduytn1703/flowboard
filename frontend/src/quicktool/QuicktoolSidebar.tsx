import { useLocation, useNavigate } from "react-router-dom";
import { AccountPanel } from "../components/AccountPanel";
import { useBoardStore } from "../store/board";
import { useSettingsStore } from "../store/settings";
import type { BoardTemplate } from "../api/client";

const TEMPLATE_ICONS: Record<string, string> = {
  fashion_ad: "👗",
  cosmetics_ad: "💄",
  fast_food_ad: "🍔",
  unboxing_review: "📦",
};

/**
 * Left rail of the Quicktool screen, modelled on the reference app: a
 * brand block, the quick tools (one per ad template), the libraries, and
 * the switch to the node canvas underneath.
 */
export function QuicktoolSidebar({
  templates,
  activeTemplateId,
}: {
  templates: BoardTemplate[];
  activeTemplateId: string | null;
}) {
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

        <div className="qt-nav__group">Công cụ nhanh</div>
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`qt-nav__item${activeTemplateId === t.id && !homeActive ? " qt-nav__item--active" : ""}`}
            onClick={() => navigate(`/clips/new?template=${t.id}`)}
            title={t.blurb}
          >
            <span className="qt-nav__icon">{TEMPLATE_ICONS[t.id] ?? "✨"}</span>
            {t.title}
            <span className="qt-nav__meta">{t.scenes} cảnh</span>
          </button>
        ))}
        {templates.length === 0 && <div className="qt-nav__empty">Đang tải mẫu…</div>}
        <button type="button" className={`qt-nav__item${is("/clips/from-video") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/clips/from-video")}
                title="Bỏ video quảng cáo có sẵn vào, AI viết lại kịch bản theo nhịp đó cho sản phẩm của bạn">
          <span className="qt-nav__icon">🎞️</span> Clip từ video mẫu
          <span className="qt-nav__meta">Gemini</span>
        </button>

        <div className="qt-nav__group">Thư viện</div>
        <button type="button" className={`qt-nav__item${is("/products") ? " qt-nav__item--active" : ""}`} onClick={() => navigate("/products")}>
          <span className="qt-nav__icon">🛍️</span> Sản phẩm đang bán
        </button>

        <div className="qt-nav__group">Nâng cao</div>
        <button type="button" className="qt-nav__item" onClick={() => { setUiMode("canvas"); navigate(boardId !== null ? `/canvas/${boardId}` : "/canvas"); }}
                title="Bảng node kéo thả — chỉnh từng node, nối dây, chat AI">
          <span className="qt-nav__icon">🧩</span> Canvas (node)
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
