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
  push(kind: ToastKind, message: string, opts?: { duration?: number }): number;
  dismiss(id: number): void;
}

let nextId = 1;
const MAX_VISIBLE = 4;

/** A reader needs about 40 ms a character; errors stay longer than good news. */
function defaultDuration(kind: ToastKind, message: string): number {
  const base = { success: 4000, info: 5000, warning: 7000, error: 9000 }[kind];
  return Math.min(15000, base + message.length * 40);
}

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push(kind, message, opts) {
    const text = (message || "").trim();
    if (!text) return -1;
    // The same message again replaces the one on screen, so its timer restarts.
    const same = get().toasts.find((t) => t.kind === kind && t.message === text);
    const id = nextId++;
    const item: ToastItem = { id, kind, message: text, duration: opts?.duration ?? defaultDuration(kind, text) };
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
