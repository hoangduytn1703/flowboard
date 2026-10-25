// Channels ("Kênh") — `/api/channels` (routes/channels.py): the pages the
// seller posts to, and the brainstorm that turns their first posts into a
// direction the post writer follows.
import { api, extractErrorMessage } from "./client";
import { toast } from "../store/toast";

export interface ChannelOption {
  key: string;
  label: string;
}

export interface ChannelOptions {
  platforms: ChannelOption[];
  categories: ChannelOption[];
  brainstorm_min_posts: number;
  /** a page picks up to this many categories (3, like Facebook) */
  max_categories: number;
}

export interface Brainstorm {
  positioning: string;
  audience: string;
  voice: string;
  post_mix: string;
  summary: string;
  pillars: { name: string; note: string }[];
  do: string[];
  dont: string[];
  hashtags: string[];
  ideas: string[];
  at: string;
  post_count: number;
  clip_count: number;
}

/** The LLM's review of the channel's live page ("🔎 Xem & đánh giá kênh"). */
export interface PageReview {
  page_name: string;
  followers: string;
  summary: string;
  score: number;
  criteria: { name: string; score: number; note: string }[];
  strengths: string[];
  weaknesses: string[];
  suggestions: string[];
  /** how the page's real posts are written — the writer matches it */
  house_style: string;
  sample_hooks: string[];
  posts_seen: number;
  at: string;
  url: string;
  /** "chrome" (read through the extension) or "fetch" (public page) */
  via: string;
}

export interface Channel {
  id: number;
  name: string;
  platforms: string[];
  /** first of `categories` (legacy) */
  category: string;
  categories: string[];
  description: string;
  audience: string;
  goal: string;
  /** the page itself (optional) */
  link: string;
  page_review: PageReview | null;
  brainstorm: Brainstorm | null;
  posts: number;
  clips: number;
  /** Enough posts for a first brainstorm, or the profile is 5+ posts old. */
  brainstorm_due: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export type ChannelInput = Partial<Pick<Channel, "name" | "platforms" | "category" | "categories" | "description" | "audience" | "goal" | "link">>;

let optionsCache: Promise<ChannelOptions> | null = null;

export function getChannelOptions(): Promise<ChannelOptions> {
  optionsCache ??= api<ChannelOptions>("/api/channels/options").catch((e) => {
    optionsCache = null;
    throw e;
  });
  return optionsCache;
}

export function listChannels(): Promise<Channel[]> {
  return api<Channel[]>("/api/channels");
}

export function getChannel(id: number): Promise<Channel> {
  return api<Channel>(`/api/channels/${id}`);
}

export async function createChannel(input: ChannelInput): Promise<Channel> {
  const res = await fetch("/api/channels", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function updateChannel(id: number, input: ChannelInput): Promise<Channel> {
  const res = await fetch(`/api/channels/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export function deleteChannel(id: number): Promise<{ ok: true }> {
  return api<{ ok: true }>(`/api/channels/${id}`, { method: "DELETE" });
}

export async function brainstormChannel(id: number): Promise<Channel> {
  const res = await fetch(`/api/channels/${id}/brainstorm`, { method: "POST" });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

/** Read the channel's link through Chrome and let the AI review the page (~30–90 s). */
export async function reviewChannelPage(id: number): Promise<Channel> {
  const res = await fetch(`/api/channels/${id}/review`, { method: "POST" });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

const running = new Set<number>();

/**
 * After a post is saved to a channel: when the channel has enough posts for
 * its first brainstorm (or the profile is stale), run it in the background
 * and tell the user. Returns the refreshed channel when a brainstorm ran.
 */
export async function brainstormIfDue(channelId: number | null | undefined): Promise<Channel | null> {
  if (!channelId || running.has(channelId)) return null;
  let ch: Channel;
  try {
    ch = await getChannel(channelId);
  } catch {
    return null;
  }
  if (!ch.brainstorm_due) return null;
  running.add(channelId);
  toast.info(ch.brainstorm
    ? `Kênh "${ch.name}" có thêm bài mới — AI đang cập nhật định hướng kênh…`
    : `Kênh "${ch.name}" đã đủ ${ch.posts} bài — AI đang brainstorm định hướng cho kênh…`, { duration: 8000 });
  try {
    const out = await brainstormChannel(channelId);
    toast.success(`Đã có định hướng cho kênh "${out.name}". Các bài sau sẽ bám theo — xem ở Kênh của tôi.`, { duration: 9000 });
    return out;
  } catch (e) {
    toast.warning(`Chưa brainstorm được kênh: ${e instanceof Error ? e.message : e}`);
    return null;
  } finally {
    running.delete(channelId);
  }
}

export function platformLabel(key: string, options?: ChannelOptions | null): string {
  return options?.platforms.find((p) => p.key === key)?.label ?? key;
}
