import { create } from 'zustand';
import { synthesizeSpeech, fetchTtsHealth, apiFetch } from './api';
import { PcmPlayer } from './pcm-player';
import { defaultVoiceSettings, responseLanguage, selectedVoiceProfile } from './voice-settings';

export type TtsState = 'idle' | 'loading' | 'speaking';

/**
 * Voice output is a single shared resource: one utterance at a time, for the
 * whole app. The state lives in one store rather than per component, because a
 * per-component hook would give every message its own audio element -- two
 * replies would then talk over each other, and autoplay would make that the
 * normal case rather than the exception.
 */
interface TtsStore {
  state: TtsState;
  /** id of the message currently loading or speaking, if any. */
  speakingId: string | null;
  error: string | null;
  /** Message whose read-aloud attempt failed, if any. */
  errorId: string | null;
  /** null until the health probe has answered. */
  available: boolean | null;
  /** Last message spoken by autoplay, so a re-render never repeats it. */
  autoSpokenId: string | null;
  speak: (id: string, text: string) => Promise<void>;
  stop: () => void;
  ensureHealth: () => Promise<void>;
  markAutoSpoken: (id: string) => void;
}

// Playback handles are not render state -- keeping them out of the store avoids
// re-rendering every subscriber when an audio element is swapped.
let audio: HTMLAudioElement | null = null;
let objectUrl: string | null = null;
let controller: AbortController | null = null;
let token = 0;
let healthProbe: Promise<void> | null = null;
let pcmPlayer: PcmPlayer | null = null;

function savedVoicePreferences(): { voiceId?: string; speed?: number; voiceProfile?: string; outputLanguage?: string; characterId?: string } {
  if (typeof localStorage === 'undefined') return {};
  try {
    const raw = localStorage.getItem('openjarvis-settings');
    if (!raw) return {};
    const settings = JSON.parse(raw) as { voiceId?: unknown; voiceSpeed?: unknown };
    const voiceSettings = { ...defaultVoiceSettings, ...settings };
    return {
      voiceId: typeof settings.voiceId === 'string' ? settings.voiceId : undefined,
      speed: typeof settings.voiceSpeed === 'number' ? settings.voiceSpeed : undefined,
      voiceProfile: selectedVoiceProfile(voiceSettings),
      outputLanguage: responseLanguage(voiceSettings),
      characterId: voiceSettings.characterId,
    };
  } catch {
    return {};
  }
}

/** Only a stream ending in the active conversation may trigger autoplay. */
export function shouldAutoplayFinishedReply(
  previousStreamingConversationId: string | null,
  activeId: string | null,
  streamIsActive: boolean,
  lastMessage: { id: string; role: string } | undefined,
  autoSpokenId: string | null,
): boolean {
  return previousStreamingConversationId !== null
    && previousStreamingConversationId === activeId
    && !streamIsActive
    && lastMessage !== undefined
    && lastMessage.role === 'assistant'
    && lastMessage.id !== autoSpokenId;
}

function teardown(): void {
  if (pcmPlayer) {
    pcmPlayer.stop();
    pcmPlayer = null;
  }
  if (audio) {
    // Detach first: clearing src re-runs the media load algorithm, which fails
    // on an empty source and dispatches an `error` event. With the handler
    // still attached that surfaces as a bogus "Playback failed" after every
    // successful utterance.
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio.src = '';
    audio = null;
  }
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  if (controller) {
    controller.abort();
    controller = null;
  }
}

export const useTtsStore = create<TtsStore>((set, get) => ({
  state: 'idle',
  speakingId: null,
  error: null,
  errorId: null,
  available: null,
  autoSpokenId: null,

  ensureHealth: () => {
    if (healthProbe) return healthProbe;
    healthProbe = fetchTtsHealth()
      .then((health) => {
        set({ available: health.available });
        if (!health.available) healthProbe = null;
      })
      .catch(() => {
        set({ available: false });
        healthProbe = null;
      });
    return healthProbe;
  },

  markAutoSpoken: (id: string) => set({ autoSpokenId: id }),

  speak: async (id: string, text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    // Bump before teardown so a synthesis still in flight is both aborted and
    // fenced off by the token, even if the abort loses the race.
    token += 1;
    const mine = token;
    teardown();
    set({ state: 'loading', speakingId: id, error: null, errorId: null });

    const ac = new AbortController();
    controller = ac;

    try {
      const voice = savedVoicePreferences();
      if (voice.voiceProfile === 'jarvis-multilingual' && voice.outputLanguage === 'zh') {
        const player = new PcmPlayer();
        pcmPlayer = player;
        const response = await apiFetch('/v1/speech/stream', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ac.signal,
          body: JSON.stringify({ text: trimmed, voice_profile: voice.voiceProfile,
            character_id: voice.characterId, output_language: 'zh', speed: voice.speed }),
        });
        if (mine !== token) { player.stop(); return; }
        if (response.ok && response.body) {
          if (response.headers.get('X-Voice-Id') !== 'jarvis-high') throw new Error('Unexpected streaming voice');
          const rate = Number(response.headers.get('X-Sample-Rate'));
          await player.play(response.body, rate, ac.signal, () => {
            if (mine === token) set({ state: 'speaking' });
          });
          if (mine === token) {
            teardown();
            set({ state: 'idle', speakingId: null });
          }
          return;
        }
        player.stop();
        pcmPlayer = null;
        if (![404, 501, 503].includes(response.status)) throw new Error(`Speech streaming failed: ${response.status}`);
      }
      const blob = await synthesizeSpeech(trimmed, {
        voiceId: voice.voiceId,
        speed: voice.speed,
        voiceProfile: voice.voiceProfile || defaultVoiceSettings.voiceProfileZh,
        outputLanguage: voice.outputLanguage || 'zh',
        characterId: voice.characterId || 'jarvis-local',
        signal: ac.signal,
      });
      if (mine !== token) return;

      const url = URL.createObjectURL(blob);
      objectUrl = url;
      const el = new Audio(url);
      audio = el;

      el.onended = () => {
        if (mine !== token) return;
        teardown();
        set({ state: 'idle', speakingId: null });
      };
      el.onerror = () => {
        if (mine !== token) return;
        teardown();
        set({ state: 'idle', speakingId: null, error: 'Playback failed', errorId: id });
      };

      await el.play();
      if (mine === token) set({ state: 'speaking', speakingId: id });
    } catch (err) {
      if (mine !== token) return;
      if (err instanceof DOMException && err.name === 'AbortError') return;
      teardown();
      set({
        state: 'idle',
        speakingId: null,
        error: err instanceof Error ? err.message : 'Speech synthesis failed',
        errorId: id,
      });
    }
  },

  stop: () => {
    token += 1;
    teardown();
    set({ state: 'idle', speakingId: null, error: null, errorId: null });
  },
}));

/** Test seam: reset module-level playback handles between cases. */
export function __resetTtsForTests(): void {
  teardown();
  token = 0;
  healthProbe = null;
  useTtsStore.setState({
    state: 'idle',
    speakingId: null,
    error: null,
    errorId: null,
    available: null,
    autoSpokenId: null,
  });
}
