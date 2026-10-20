/**
 * Settings → "Nguồn tạo ảnh": image renderers other than Google Flow
 * (OpenAI GPT Image, xAI Grok Image). The backend keeps the API keys; the
 * selected provider is a local preference (store/settings.ts) sent with
 * each image dispatch as `params.image_provider`.
 */

export type ImageProviderId = "flow" | "openai" | "xai";

export interface ImageProviderInfo {
  id: ImageProviderId;
  label: string;
  model: string | null;
  configured: boolean;
  notes_vi: string;
}

export interface ImageProviderTestResult {
  ok: boolean;
  message: string;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    const detail = body?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
      return (detail as { message: string }).message;
    }
  } catch {
    // fall through
  }
  return `${res.status} ${res.statusText}`;
}

export async function listImageProviders(): Promise<ImageProviderInfo[]> {
  const res = await fetch("/api/image-providers");
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

/** Save (or remove, with an empty string) the key for one provider. */
export async function setImageProviderKey(id: ImageProviderId, key: string): Promise<ImageProviderInfo> {
  const res = await fetch(`/api/image-providers/${id}/key`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

/** Free probe (models endpoint). `key` tests an unsaved draft; omit to test the saved key. */
export async function testImageProvider(id: ImageProviderId, key?: string): Promise<ImageProviderTestResult> {
  const res = await fetch(`/api/image-providers/${id}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(key ? { key } : {}),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}
