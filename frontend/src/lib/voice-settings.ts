export interface VoiceSettings {
  recognitionLanguage: 'zh' | 'en';
  outputLanguage: 'recognition' | 'zh' | 'en';
  characterId: 'jarvis-local' | 'mcu-jarvis';
  voiceProfileZh: string;
  voiceProfileEn: string;
  speechPauseMs: number;
  voiceIdleSeconds: number;
  interruptWords: string[];
}

export const defaultVoiceSettings: VoiceSettings = {
  recognitionLanguage: 'zh', outputLanguage: 'recognition', characterId: 'jarvis-local',
  voiceProfileZh: 'kokoro-zh-yunjian', voiceProfileEn: 'kokoro-en-george', speechPauseMs: 1800,
  voiceIdleSeconds: 30, interruptWords: ['停一下', '暂停', '别说了', 'stop', 'pause'],
};

export const VOICE_TIMING_VERSION = 2;

export function migrateSpeechPause(value: unknown, version: unknown): number {
  const needsMigration = typeof version !== 'number' || version < VOICE_TIMING_VERSION;
  if (needsMigration && value === 1400) return 1800;
  return typeof value === 'number' && Number.isFinite(value) ? value : 1800;
}

export function responseLanguage(settings: VoiceSettings): 'zh' | 'en' {
  return settings.outputLanguage === 'recognition' ? settings.recognitionLanguage : settings.outputLanguage;
}

export function selectedVoiceProfile(settings: VoiceSettings): string {
  return responseLanguage(settings) === 'zh' ? settings.voiceProfileZh : settings.voiceProfileEn;
}

export function characterPreset(characterId: VoiceSettings['characterId']): Partial<VoiceSettings> {
  return characterId === 'mcu-jarvis'
    ? { characterId, outputLanguage: 'en', voiceProfileEn: 'piper-mcu-jarvis' }
    : { characterId, outputLanguage: 'recognition', voiceProfileZh: 'kokoro-zh-yunjian', voiceProfileEn: 'kokoro-en-george' };
}
