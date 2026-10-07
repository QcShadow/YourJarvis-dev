import { apiFetch } from './api';

export interface VoiceProfile {
  id: string; name: string; languages: string[]; characters: string[];
  backend: string; installed: boolean; experimental: boolean; note?: string;
  user_owned?: boolean; kind?: 'reference' | 'piper-model'; status?: string;
}

async function checked(response: Response): Promise<Response> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Voice library: ${response.status}`);
  }
  return response;
}

export async function importVoicePack(files: File[], name: string, transcript: string,
  referenceLanguage: string, speakerId: number): Promise<VoiceProfile> {
  const body = new FormData();
  files.forEach((file) => body.append('files', file));
  body.append('name', name); body.append('transcript', transcript);
  body.append('reference_language', referenceLanguage); body.append('speaker_id', String(speakerId));
  return (await checked(await apiFetch('/v1/speech/packs/import', { method: 'POST', body }))).json();
}

export async function renameVoicePack(id: string, name: string): Promise<void> {
  await checked(await apiFetch(`/v1/speech/packs/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  }));
}

export async function deleteVoicePack(id: string): Promise<void> {
  await checked(await apiFetch(`/v1/speech/packs/${encodeURIComponent(id)}`, { method: 'DELETE' }));
}

export async function exportVoicePack(id: string): Promise<Blob> {
  return (await checked(await apiFetch(`/v1/speech/packs/${encodeURIComponent(id)}/export`))).blob();
}
