// Flow credit balance shared across the app. One module-level cache, one
// in-flight fetch at a time, and every mounted `useFlowCredits()` re-renders
// from the same snapshot — no store library needed (useSyncExternalStore).
//
// `/api/auth/me` is cheap but polled from several places; the cache keeps a
// 60 s freshness window so a badge in the sidebar and a confirm dialog never
// double-fetch. `refresh()` is the user's explicit "check now": it runs
// `POST /api/auth/scan` (which re-reads `/v1/credits` when the tier is
// missing) and then re-reads `/me` regardless of the window.
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { getAuthMe, scanExtension, type AuthMe } from "../api/client";

export const CREDITS_TTL_MS = 60_000;

export interface FlowCreditsSnapshot {
  credits: number | null;
  tier: AuthMe["paygate_tier"];
  sku: string | null;
  email: string | null;
  loading: boolean;
  /** Epoch ms of the last successful `/me`; 0 = never. */
  fetchedAt: number;
  error: string | null;
}

let snapshot: FlowCreditsSnapshot = {
  credits: null,
  tier: null,
  sku: null,
  email: null,
  loading: false,
  fetchedAt: 0,
  error: null,
};

const listeners = new Set<() => void>();
let inflight: Promise<void> | null = null;

function emit(next: Partial<FlowCreditsSnapshot>) {
  snapshot = { ...snapshot, ...next };
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return snapshot;
}

async function fetchMe(): Promise<void> {
  const me = await getAuthMe();
  if (me === null) {
    emit({ loading: false, error: "Không đọc được tài khoản Flow" });
    return;
  }
  emit({
    credits: typeof me.credits === "number" ? me.credits : null,
    tier: me.paygate_tier,
    sku: me.sku,
    email: me.email,
    loading: false,
    fetchedAt: Date.now(),
    error: null,
  });
}

/** Fetch `/me` unless a fresh copy (< TTL) is already cached. */
export function ensureFlowCredits(force = false): Promise<void> {
  if (inflight) return inflight;
  if (!force && snapshot.fetchedAt && Date.now() - snapshot.fetchedAt < CREDITS_TTL_MS) {
    return Promise.resolve();
  }
  emit({ loading: true });
  inflight = fetchMe()
    .catch((err) => {
      emit({ loading: false, error: err instanceof Error ? err.message : String(err) });
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** `POST /api/auth/scan` (nudges the extension, re-reads /v1/credits) then `/me`. */
export function refreshFlowCredits(): Promise<void> {
  if (inflight) return inflight;
  emit({ loading: true, error: null });
  inflight = scanExtension()
    .catch(() => undefined)
    .then(() => fetchMe())
    .catch((err) => {
      emit({ loading: false, error: err instanceof Error ? err.message : String(err) });
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** Test / debug hook: drop the cache so the next read refetches. */
export function resetFlowCreditsCache() {
  snapshot = { ...snapshot, fetchedAt: 0 };
}

export interface FlowCredits {
  credits: number | null;
  tier: AuthMe["paygate_tier"];
  sku: string | null;
  email: string | null;
  loading: boolean;
  error: string | null;
  refresh(): Promise<void>;
}

/**
 * Current Flow credit balance (shared cache, fetched at most once per 60 s
 * across every mount). `refresh()` forces a scan + re-read.
 */
export function useFlowCredits(): FlowCredits {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  // Kick the first (or a stale) fetch on mount; a no-op while the cache is
  // fresh. In an effect, not during render, so the emit never updates
  // another component mid-render.
  useEffect(() => {
    void ensureFlowCredits();
  }, []);
  const refresh = useCallback(() => refreshFlowCredits(), []);
  return {
    credits: snap.credits,
    tier: snap.tier,
    sku: snap.sku,
    email: snap.email,
    loading: snap.loading,
    error: snap.error,
    refresh,
  };
}

/** "Ultra" / "Pro" / "—" for a title or a confirm prompt. */
export function tierLabel(tier: AuthMe["paygate_tier"], sku?: string | null): string {
  if (sku) {
    const s = sku.toUpperCase();
    if (s.includes("ULTRA")) return "Ultra";
    if (s.includes("PRO")) return "Pro";
  }
  if (tier === "PAYGATE_TIER_TWO") return "Ultra";
  if (tier === "PAYGATE_TIER_ONE") return "Pro";
  return "—";
}
