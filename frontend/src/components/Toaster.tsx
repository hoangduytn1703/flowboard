import { useEffect, useRef, useState } from "react";
import { useBoardStore } from "../store/board";
import { useChatStore } from "../store/chat";
import { useGenerationStore } from "../store/generation";
import { usePipelineStore } from "../store/pipeline";
import { toastMs, useToastStore, type ToastKind } from "../store/toast";
import { humanizeBackendError } from "../api/client";

const ICON: Record<ToastKind, string> = { success: "✓", info: "i", warning: "!", error: "!" };
const LABEL: Record<ToastKind, string> = { success: "Thành công", info: "Thông báo", warning: "Lưu ý", error: "Lỗi" };

/** One toast: dismisses itself after ``duration``; hovering holds it. */
function Toast({ kind, message, duration, onClose }: { kind: ToastKind; message: string; duration: number; onClose: () => void }) {
  const [hover, setHover] = useState(false);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (hover) return;
    const t = setTimeout(() => closeRef.current(), duration);
    return () => clearTimeout(t);
  }, [hover, duration, message]);
  return (
    <div className={`toast toast--${kind}`} role={kind === "error" || kind === "warning" ? "alert" : "status"}
         onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <span className="toast__icon" aria-hidden="true">{ICON[kind]}</span>
      <div className="toast__body">
        <div className="toast__title">{LABEL[kind]}</div>
        <div className="toast__msg">{message}</div>
      </div>
      <button type="button" className="toast__close" onClick={onClose} aria-label="Đóng thông báo">×</button>
      {!hover && <span className="toast__bar" style={{ animationDuration: `${duration}ms` }} aria-hidden="true" />}
    </div>
  );
}

/**
 * The toast stack (bottom left). Shows the toasts pushed with `toast.*` and,
 * as error toasts, the `error` that the board / chat / generation / pipeline
 * stores raise (one at a time, in that priority).
 */
export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  const boardError = useBoardStore((s) => s.error);
  const chatError = useChatStore((s) => s.error);
  const genError = useGenerationStore((s) => s.error);
  const pipelineError = usePipelineStore((s) => s.error);
  const clearBoardError = useBoardStore((s) => s.clearError);
  const clearChatError = useChatStore((s) => s.clearError);
  const clearGenError = useGenerationStore((s) => s.clearError);
  const clearPipelineError = usePipelineStore((s) => s.clearError);

  // Priority: chat > pipeline > generation > board
  const storeError = chatError ?? pipelineError ?? genError ?? boardError;
  const clearStoreError =
    chatError !== null ? clearChatError
    : pipelineError !== null ? clearPipelineError
    : genError !== null ? clearGenError
    : clearBoardError;

  if (!storeError && toasts.length === 0) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {storeError && <Toast key={`store:${storeError}`} kind="error" message={humanizeBackendError(storeError) ?? storeError} duration={toastMs("error", storeError)} onClose={clearStoreError} />}
      {toasts.map((t) => (
        <Toast key={t.id} kind={t.kind} message={t.message} duration={t.duration} onClose={() => dismiss(t.id)} />
      ))}
    </div>
  );
}
