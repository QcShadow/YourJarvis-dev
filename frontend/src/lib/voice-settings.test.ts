import { describe, expect, it } from 'vitest';
import { characterPreset, defaultVoiceSettings, migrateSpeechPause, responseLanguage, selectedVoiceProfile, VOICE_TIMING_VERSION, type VoiceSettings } from './voice-settings';

const settings: VoiceSettings = {
  ...defaultVoiceSettings,
  recognitionLanguage: 'zh', outputLanguage: 'recognition', characterId: 'jarvis-local',
  voiceProfileZh: 'kokoro-zh-yunjian', voiceProfileEn: 'kokoro-en-george', speechPauseMs: 1400,
};
describe('explicit voice and persona bindings', () => {
  it('migrates only the old endpointing default and preserves custom timing', () => {
    expect(defaultVoiceSettings.speechPauseMs).toBe(1800);
    expect(migrateSpeechPause(1400, undefined)).toBe(1800);
    expect(migrateSpeechPause(1400, VOICE_TIMING_VERSION)).toBe(1400);
    expect(migrateSpeechPause(1400, VOICE_TIMING_VERSION + 1)).toBe(1400);
    expect(migrateSpeechPause(2100, undefined)).toBe(2100);
  });
  it('keeps Chinese voice stable regardless of English words in a transcript', () => {
    expect(responseLanguage(settings)).toBe('zh');
    expect(selectedVoiceProfile(settings)).toBe('kokoro-zh-yunjian');
  });
  it('selects MCU English persona, source and language without changing recognition', () => {
    const mcu = { ...settings, ...characterPreset('mcu-jarvis') };
    expect(mcu.recognitionLanguage).toBe('zh');
    expect(responseLanguage(mcu)).toBe('en');
    expect(selectedVoiceProfile(mcu)).toBe('piper-mcu-jarvis');
  });
  it('allows explicit Chinese output with MCU style and the Chinese voice', () => {
    const mcu: VoiceSettings = { ...settings, ...characterPreset('mcu-jarvis'), outputLanguage: 'zh' };
    expect(selectedVoiceProfile(mcu)).toBe('kokoro-zh-yunjian');
  });
});
