import type { AccountMe } from "../api/account";
import { useAccountStore } from "../store/account";

/**
 * Features a plan ("gói") can switch on or off — the same keys as agent/flowboard/plans.py. The agent also
 * refuses the matching API routes; hiding here keeps the UI from offering what the plan does not include.
 * Core clip making (clips, products, models, prompts, history, settings) is never gated.
 */
export type FeatureKey =
  | "auto_clip" | "dub" | "cut" | "grab" | "capcut" | "clean" | "posts" | "facebook" | "autopilot" | "swipes" | "assistant";

/** Taken out of sight for now (agent: plans.HIDDEN_FEATURES) — no menu, no page, whatever the plan says.
 *  "capcut" is to come back inside the video editor. */
const HIDDEN: FeatureKey[] = ["capcut"];

export function hasFeature(me: AccountMe | null, key: FeatureKey): boolean {
  if (HIDDEN.includes(key)) return false;
  if (!me || !me.auth || !me.features) return true; // no login / an older agent: nothing is gated
  return me.features.includes(key);
}

/** In a component: re-renders when the account (or its plan) changes. */
export function useFeature(key: FeatureKey): boolean {
  return useAccountStore((s) => hasFeature(s.me, key));
}

/** Outside React (effects, store actions). */
export function canUse(key: FeatureKey): boolean {
  return hasFeature(useAccountStore.getState().me, key);
}

export function planName(): string {
  return useAccountStore.getState().me?.plan?.name ?? "";
}
