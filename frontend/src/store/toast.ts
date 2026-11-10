import { useEffect } from "react";
import { create } from "zustand";

export type ToastKind = "success" | "info" | "warning" | "error";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  /** ms before it goes away on its own; hovering pauses it. */
  duration: number;
}

interface ToastState {
  toasts: ToastItem[];
  /** ``opts`` is still accepted by callers but ignored: all toasts last TOAST_MS. */
  push(kind: ToastKind, message: string, opts?: { duration?: number }): number;
  dismiss(id: number): void;
}

let nextId = 1;
const MAX_VISIBLE = 4;

/** Every toast stays this long (the user asked for 1.5 s); hovering one holds it so a long message can still be read. */
export const TOAST_MS = 1500;

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push(kind, message) {
    const text = (message || "").trim();
    if (!text) return -1;
    // The same message again replaces the one on screen, so its timer restarts.
    const same = get().toasts.find((t) => t.kind === kind && t.message === text);
    const id = nextId++;
    const item: ToastItem = { id, kind, message: text, duration: TOAST_MS };
    set((s) => ({ toasts: [...s.toasts.filter((t) => t !== same), item].slice(-MAX_VISIBLE) }));
    return id;
  },
  dismiss(id) {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));

/** ``toast.success("Đã lưu")`` from anywhere, hooks or not. */
export const toast = {
  success: (m: string, o?: { duration?: number }) => useToastStore.getState().push("success", m, o),
  info: (m: string, o?: { duration?: number }) => useToastStore.getState().push("info", m, o),
  warning: (m: string, o?: { duration?: number }) => useToastStore.getState().push("warning", m, o),
  error: (m: string, o?: { duration?: number }) => useToastStore.getState().push("error", m, o),
};

/**
 * Show ``message`` as a toast whenever it becomes non-empty, then call
 * ``clear`` so the same text can be shown again next time. Lets a component
 * that keeps its feedback in state ("saved", "failed") put it on screen
 * instead of drawing a faint line inside the page.
 */
export function useToastOn(message: string | null | undefined, kind: ToastKind, clear?: () => void) {
  useEffect(() => {
    if (!message) return;
    toast[kind](message);
    clear?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message]);
}
