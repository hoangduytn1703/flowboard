// "🧬 Giọng nhân bản" — `/api/voices/clones` (routes/voices.py, services/voice_clone.py): voices VieNeu learns from
// the seller's short recordings. A cloned voice id (`vieneu:clone:<uid>`) goes wherever a voice id goes.
import { api, extractErrorMessage, refreshVoiceGroups } from "./client";

export type CloneGender = "" | "male" | "female";

export interface VoiceClone {
  uid: string;
  /** the voice id for every picker / reader */
  voice: string;
  name: string;
  gender: CloneGender;
  /** "Giọng của mình (nam)" */
  label: string;
  /** seconds of speech heard in the recording */
  speech_s: number;
  created_at: string | null;
}

export const listVoiceClones = () => api<VoiceClone[]>("/api/voices/clones");

/** Learn a voice from a recording (a file, or what the microphone took). Takes ~10–60 s on the agent. */
export async function createVoiceClone(audio: Blob, fileName: string, name: string, gender: CloneGender,
                                       consent: boolean): Promise<VoiceClone> {
  const form = new FormData();
  form.append("file", audio, fileName);
  form.append("name", name);
  form.append("gender", gender);
  form.append("consent", consent ? "true" : "false");
  const res = await fetch("/api/voices/clones", { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  const v = await res.json() as VoiceClone;
  refreshVoiceGroups();
  return v;
}

export async function updateVoiceClone(uid: string, patch: { name?: string; gender?: CloneGender }): Promise<VoiceClone> {
  const v = await api<VoiceClone>(`/api/voices/clones/${uid}`, { method: "PATCH", body: JSON.stringify(patch) });
  refreshVoiceGroups();
  return v;
}

export async function deleteVoiceClone(uid: string): Promise<void> {
  await api(`/api/voices/clones/${uid}`, { method: "DELETE" });
  refreshVoiceGroups();
}
