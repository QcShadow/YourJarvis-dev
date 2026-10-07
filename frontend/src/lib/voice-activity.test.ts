import { describe, it, expect } from 'vitest';
import { useVoiceActivity, voiceActivityLabel } from './voice-activity';

describe('transient voice monitor', () => {
  it('updates input level without erasing the recognized phrase, then resets', () => {
    useVoiceActivity.getState().update({ heard: '打开浏览器', phase: 'armed' });
    useVoiceActivity.getState().update({ inputLevel: .5 });
    expect(useVoiceActivity.getState().heard).toBe('打开浏览器');
    useVoiceActivity.getState().reset();
    expect(useVoiceActivity.getState().heard).toBe('');
    expect(useVoiceActivity.getState().phase).toBe('stopped');
  });

  it('distinguishes a stopped microphone from wake-word standby', () => {
    expect(voiceActivityLabel('stopped', true)).toBe('接听未运行');
    expect(voiceActivityLabel('stopped', false)).toBe('Microphone is stopped');
    expect(voiceActivityLabel('listening', true)).toContain('嘿贾维斯');
    expect(voiceActivityLabel('listening', false)).toContain('Hey Jarvis');
  });
  it('provides localized phase labels', () => {
    expect(voiceActivityLabel('armed', true)).toContain('我在听');
    expect(voiceActivityLabel('queuing', true)).toContain('后台');
    expect(voiceActivityLabel('speaking', false)).toContain('interrupt');
    expect(voiceActivityLabel('unknown', true)).toBeTruthy();
  });
});
