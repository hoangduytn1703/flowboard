import { useEffect, useState, type ReactNode } from "react";

/** Wait this long before showing the loader, so a fast load does not flash it. */
const SHOW_AFTER_MS = 150;

/**
 * Whole-page loading state, centred in the page: a ring spinner and a line
 * of text. Used where a page has nothing to show until its list arrives.
 */
export function PageLoading({ text = "Đang tải…", compact = false }: { text?: string; compact?: boolean }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setShown(true), SHOW_AFTER_MS);
    return () => window.clearTimeout(t);
  }, []);
  return (
    <div className={`qt-pagestate${compact ? " qt-pagestate--compact" : ""}${shown ? "" : " qt-pagestate--hidden"}`}
         role="status" aria-live="polite">
      <div className="qt-pagestate__loader" aria-hidden="true">
        <span className="qt-pagestate__ring" />
        <span className="qt-pagestate__core" />
      </div>
      <p className="qt-pagestate__text">{text}</p>
    </div>
  );
}

/**
 * Whole-page empty state, centred: an icon, a title, a line of help and
 * optionally the buttons that fill the page.
 */
export function PageEmpty({ icon, title, children, actions, compact = false }: {
  icon: string;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`qt-pagestate qt-pagestate--empty${compact ? " qt-pagestate--compact" : ""}`}>
      <div className="qt-pagestate__icon" aria-hidden="true">{icon}</div>
      <h3 className="qt-pagestate__title">{title}</h3>
      {children && <p className="qt-pagestate__hint">{children}</p>}
      {actions && <div className="qt-pagestate__actions">{actions}</div>}
    </div>
  );
}
