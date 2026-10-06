import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn(), updateSettings: vi.fn() }));
vi.mock('./api', () => ({ apiFetch: mocks.apiFetch }));
vi.mock('./store', () => ({ useAppStore: { getState: () => ({ updateSettings: mocks.updateSettings }) } }));
import { initDeploymentSettings } from './deployment';

describe('recipient first-run preferences', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('localStorage', { getItem: () => null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('applies the saved lite/text preset to a fresh browser', async () => {
    const settings = { defaultModel: 'qwen2.5:0.5b', maxTokens: 256, voiceOutputEnabled: false };
    mocks.apiFetch.mockResolvedValue({ ok: true, json: async () => ({ configured: true, settings }) });
    await initDeploymentSettings();
    expect(mocks.updateSettings).toHaveBeenCalledWith(settings);
  });

  it('preserves the owner or an existing browser profile', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '{"defaultModel":"my-model"}' });
    await initDeploymentSettings();
    expect(mocks.apiFetch).not.toHaveBeenCalled();
    expect(mocks.updateSettings).not.toHaveBeenCalled();
  });

  it('does not change preferences for existing configs or older servers', async () => {
    mocks.apiFetch.mockResolvedValue({ ok: true, json: async () => ({ configured: false }) });
    await initDeploymentSettings();
    mocks.apiFetch.mockResolvedValue({ ok: false });
    await initDeploymentSettings();
    expect(mocks.updateSettings).not.toHaveBeenCalled();
  });
});
