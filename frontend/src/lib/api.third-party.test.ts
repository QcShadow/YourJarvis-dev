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

it('reports the third-party source while the primary server remains local', () => {
  expect(resolveChatEngine({ serverEngine: 'ollama', selectedModel: 'third-party/qwen-chat', selectedOwner: 'third_party_api' })).toBe('third_party_api');
});
