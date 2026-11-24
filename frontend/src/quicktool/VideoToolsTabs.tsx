import { Link, useLocation } from "react-router-dom";
import { useFeature } from "../lib/features";

/**
 * One menu entry for everything done to videos you already have: "📥 Thêm video" (the one place to bring videos in)
 * and the tools behind it. Each tool page shows these tabs under its title, so the four tools read as one place.
 * "✏️ Chỉnh sửa" has no page of its own without videos: it opens "📥 Thêm video" with "Chỉnh sửa" picked, and the
 * tab stays lit there.
 */
export function VideoToolsTabs() {
  const dub = useFeature("dub");
  const cut = useFeature("cut");
  const clean = useFeature("clean");
  const { pathname, search } = useLocation();
  const editPicked = pathname === "/tools" && new URLSearchParams(search).get("do") === "edit";
  const tabs = [
    { to: "/tools", label: "📥 Thêm video", on: true, lit: pathname === "/tools" && !editPicked },
    { to: "/tools/dub", label: "🎙 Lồng tiếng", on: dub, lit: pathname.startsWith("/tools/dub") },
    { to: "/tools/cut", label: "✂️ Cắt video", on: cut, lit: pathname.startsWith("/tools/cut") },
    { to: "/tools?do=edit", label: "✏️ Chỉnh sửa", on: dub || cut, lit: editPicked || pathname.startsWith("/tools/edit") },
    { to: "/tools/clean", label: "🧽 Xoá chữ / logo", on: clean, lit: pathname.startsWith("/tools/clean") },
  ].filter((t) => t.on);
  return (
    <nav className="qt-tooltabs" aria-label="Xử lý video">
      {tabs.map((t) => (
        <Link key={t.to} to={t.to} aria-current={t.lit ? "page" : undefined}
              className={`qt-tooltabs__tab${t.lit ? " qt-tooltabs__tab--on" : ""}`}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
