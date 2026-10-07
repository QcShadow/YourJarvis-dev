import { afterEach, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({ apiFetch: vi.fn(), synthesizeSpeech: vi.fn(), fetchTtsHealth: vi.fn() }));
vi.mock('./pcm-player', () => ({ PcmPlayer: class { stop() {} async play() {} } }));
import { apiFetch, synthesizeSpeech } from './api';
import { useTtsStore, __resetTtsForTests } from './tts';

afterEach(() => { __resetTtsForTests(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

it('previews a custom English voice without modifying saved settings', async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(new Uint8Array([0, 0]), {
    headers: { 'X-Voice-Id': 'user-one', 'X-Sample-Rate': '24000' },
  }));
  await useTtsStore.getState().speak('preview', 'Hello.', {
    voiceProfile: 'user-one', outputLanguage: 'en', characterId: 'jarvis-local',
  });
  expect(JSON.parse(vi.mocked(apiFetch).mock.calls[0][1]?.body as string)).toMatchObject({
    voice_profile: 'user-one', output_language: 'en',
  });
  expect(synthesizeSpeech).not.toHaveBeenCalled();
  expect(useTtsStore.getState().error).toBeNull();
});

it('falls back to WAV for a custom Piper voice while keeping its identity', async () => {
  vi.stubGlobal('Audio', class { onended = null; onerror = null; src = ''; pause() {} async play() {} });
  vi.stubGlobal('URL', { createObjectURL: () => 'blob:test', revokeObjectURL() {} });
  vi.mocked(apiFetch).mockResolvedValue(new Response('{}', { status: 501 }));
  vi.mocked(synthesizeSpeech).mockResolvedValue(new Blob(['wave']));
  await useTtsStore.getState().speak('preview', 'Hello.', {
    voiceProfile: 'user-piper', outputLanguage: 'en', characterId: 'jarvis-local',
  });
  expect(synthesizeSpeech).toHaveBeenCalledWith('Hello.', expect.objectContaining({
    voiceProfile: 'user-piper', outputLanguage: 'en',
  }));
  expect(useTtsStore.getState().error).toBeNull();
});
