import { apiFetch } from './api';
import { useAppStore, type Settings } from './store';

/** Apply a recipient's preset only to a new browser profile. */
export async function initDeploymentSettings(): Promise<void> {
  try {
    if (localStorage.getItem('openjarvis-settings')) return;
    const response = await apiFetch('/v1/deployment/bootstrap', { signal: AbortSignal.timeout(3000) });
    if (!response.ok) return;
    const value = await response.json() as { configured?: boolean; settings?: Partial<Settings> };
    if (value.configured && value.settings && !localStorage.getItem('openjarvis-settings')) {
      useAppStore.getState().updateSettings(value.settings);
    }
  } catch { /* The existing app defaults cover older/offline servers. */ }
}
