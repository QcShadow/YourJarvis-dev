import { afterEach, expect, it, vi } from 'vitest';
import { preloadModel } from './api';
import { resolveChatEngine } from './chat-telemetry';

afterEach(() => vi.unstubAllGlobals());

it('does not try to load third-party models into Ollama', async () => {
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  await preloadModel('third-party/qwen-chat', 'third_party_api');
  await preloadModel('third-party/vendor/model');
  expect(fetch).not.toHaveBeenCalled();
});

it('preloads local models through the owning backend instead of port 11434', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true });
  vi.stubGlobal('fetch', fetch);
  await preloadModel('qwen3.5:9b', 'ollama');
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][0]).toBe('/v1/models/preload');
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ model: 'qwen3.5:9b' });
});

it('reports the third-party source while the primary server remains local', () => {
  expect(resolveChatEngine({ serverEngine: 'ollama', selectedModel: 'third-party/qwen-chat', selectedOwner: 'third_party_api' })).toBe('third_party_api');
});
