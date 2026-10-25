// Facebook posts ("Bài viết") — `/api/posts` (routes/posts.py): the LLM
// writes / revises a post from a brief or a chat message; saved posts live
// in the account's library.
import { api, extractErrorMessage } from "./client";

export interface PostOption {
  key: string;
  label: string;
}

export interface PostOptions {
  kinds: PostOption[];
  tones: PostOption[];
  lengths: PostOption[];
  ctas: PostOption[];
  max_images: number;
}

/** Form fields; every one is optional. */
export interface PostBrief {
  kind?: string;
  topic?: string;
  audience?: string;
  tone?: string;
  length?: string;
  cta?: string;
  images?: number;
  image_wish?: string;
}

export interface PostDraft {
  title: string;
  body: string;
  hashtags: string[];
  image_prompts: string[];
  /** "Bình luận đầu tiên": friendly line + affiliate link, pasted under the post */
  first_comment?: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

export interface WritePostResult {
  reply: string;
  post: PostDraft;
  product_id: number | null;
  channel_id: number | null;
  series: string;
  episode: number;
}

export interface SavedPost {
  id: number;
  kind: string | null;
  title: string | null;
  body: string;
  /** Space-separated, e.g. "#comchay #anvat". */
  hashtags: string | null;
  first_comment: string;
  product_id: number | null;
  board_id: number | null;
  channel_id: number | null;
  /** story series name + episode number (0 = not part of one) */
  series: string;
  episode: number;
  images: string[];
  image_prompts: string[];
  brief: PostBrief;
  created_at: string | null;
  updated_at: string | null;
}

export type SavedPostInput = Partial<Omit<SavedPost, "id" | "created_at" | "updated_at">>;

let optionsCache: Promise<PostOptions> | null = null;

export function getPostOptions(): Promise<PostOptions> {
  optionsCache ??= api<PostOptions>("/api/posts/options").catch((e) => {
    optionsCache = null;
    throw e;
  });
  return optionsCache;
}

export async function writePost(body: {
  brief: PostBrief;
  product_id?: number | null;
  board_id?: number | null;
  channel_id?: number | null;
  series?: string | null;
  current?: PostDraft | null;
  message?: string;
  history?: ChatTurn[];
}): Promise<WritePostResult> {
  const res = await fetch("/api/posts/write", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export function listPosts(boardId?: number, channelId?: number): Promise<SavedPost[]> {
  const q = new URLSearchParams();
  if (boardId != null) q.set("board_id", String(boardId));
  if (channelId != null) q.set("channel_id", String(channelId));
  const qs = q.toString();
  return api<SavedPost[]>(qs ? `/api/posts?${qs}` : "/api/posts");
}

export interface PostSeries {
  name: string;
  episodes: number;
  last_episode: number;
  last_title: string;
  channel_id: number | null;
}

export function listSeries(channelId?: number | null): Promise<PostSeries[]> {
  return api<PostSeries[]>(channelId != null ? `/api/posts/series?channel_id=${channelId}` : "/api/posts/series");
}

/** "✨ Sửa theo yêu cầu" on a post image: the English prompt rewritten from a Vietnamese wish. */
export async function reviseImagePrompt(prompt: string, request: string): Promise<{ prompt: string }> {
  return api<{ prompt: string }>("/api/posts/revise-image", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, request }),
  });
}

export function savePost(input: SavedPostInput): Promise<SavedPost> {
  return api<SavedPost>("/api/posts", { method: "POST", body: JSON.stringify(input) });
}

export function updatePost(id: number, input: SavedPostInput): Promise<SavedPost> {
  return api<SavedPost>(`/api/posts/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deletePost(id: number): Promise<{ ok: true }> {
  return api<{ ok: true }>(`/api/posts/${id}`, { method: "DELETE" });
}

/** "#a #b" ⇄ ["#a", "#b"]. */
export function splitTags(text: string | null | undefined): string[] {
  return (text ?? "").split(/[\s,]+/).map((t) => t.replace(/^#*/, "")).filter(Boolean).map((t) => `#${t}`);
}

/** What goes to the clipboard / Facebook: body, a blank line, hashtags. */
export function postText(body: string, hashtags: string[]): string {
  const tags = hashtags.join(" ").trim();
  return tags ? `${body.trim()}\n\n${tags}` : body.trim();
}
