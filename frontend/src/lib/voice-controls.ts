import { apiFetch, isNativeDesktop } from './api';
import { useVoiceActivity } from './voice-activity';
import { useTtsStore } from './tts';

export async function pauseVoiceConversation() {
  useTtsStore.getState().stop();
  window.dispatchEvent(new Event('jarvis-interrupt-response'));
  window.dispatchEvent(new Event('jarvis-voice-standby'));
  useVoiceActivity.getState().update({ foreground: false, phase: 'listening', remaining: 0 });
  if (isNativeDesktop()) {
    try {
      const response = await apiFetch('/v1/voice/standby', { method: 'POST' });
      if (!response.ok) throw new Error(`Voice standby failed: ${response.status}`);
    } catch (error) {
      useVoiceActivity.getState().update({ error: String(error) });
    }
  }
}
