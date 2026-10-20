import {
  getLlmConfig,
  getLlmProviders,
  type LLMConfig,
  type LLMProviderInfo,
} from "../api/client";

/**
 * One shared, time-limited copy of `GET /api/llm/config` (and
 * `/api/llm/providers`) for every component that watches it — the badge,
 * the forced-setup gate, the chat dock and the Settings section. Each of
 * them used to poll on its own 30 s timer plus a refresh on every
 * tab-visibility change, which added up to dozens of identical requests a
 * minute. Now a value is reused for `TTL_MS`, concurrent callers share one
 * in-flight request, and `fresh: true` (after the user applies a change)
 * drops the copy so the next read hits the network once.
 */

const TTL_MS = 60_000;

type Entry<T> = { at: number; value: T };

function cached<T>(load: () => Promise<T>) {
  let entry: Entry<T> | null = null;
  let inflight: Promise<T> | null = null;
  return (opts?: { fresh?: boolean }): Promise<T> => {
    if (opts?.fresh) entry = null;
    if (entry && Date.now() - entry.at < TTL_MS) return Promise.resolve(entry.value);
    if (inflight) return inflight;
    inflight = load()
      .then((value) => {
        entry = { at: Date.now(), value };
        return value;
      })
      .finally(() => {
        inflight = null;
      });
    return inflight;
  };
}

/** The LLM config, at most one request a minute across the whole app. */
export const getLlmConfigCached: (opts?: { fresh?: boolean }) => Promise<LLMConfig> =
  cached(getLlmConfig);

/** The provider catalog, same policy. */
export const getLlmProvidersCached: (opts?: { fresh?: boolean }) => Promise<LLMProviderInfo[]> =
  cached(getLlmProviders);

/** How often a watcher re-reads the cache; the cache itself decides
 *  whether that turns into a request. */
export const LLM_CONFIG_POLL_MS = TTL_MS;
