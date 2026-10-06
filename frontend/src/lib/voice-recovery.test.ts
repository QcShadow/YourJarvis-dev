import { describe, expect, it } from 'vitest';
import { VoiceRecovery } from './voice-recovery';

describe('voice service recovery', () => {
  it('respects a server-side explicit off and does not race startup restoration', () => {
    const recovery = new VoiceRecovery();
    expect(recovery.shouldRestart(true, false, 10000, false)).toBe(false);
    expect(recovery.shouldRestart(true, false, 20000, true, true)).toBe(false);
    expect(recovery.shouldRestart(true, false, 23000, true, false)).toBe(true);
  });
  it('never restarts an explicitly disabled microphone or a live standby listener', () => {
    const recovery = new VoiceRecovery();
    expect(recovery.shouldRestart(false, false, 10000)).toBe(false);
    expect(recovery.shouldRestart(true, true, 20000)).toBe(false);
    expect(recovery.shouldRestart(true, false, 22000)).toBe(false);
    expect(recovery.shouldRestart(true, false, 23000)).toBe(true);
  });
  it('backs off failed recovery attempts instead of restarting on every poll', () => {
    const recovery = new VoiceRecovery();
    recovery.reset(0);
    expect(recovery.shouldRestart(true, false, 2999)).toBe(false);
    expect(recovery.shouldRestart(true, false, 3000)).toBe(true);
    expect(recovery.shouldRestart(true, false, 3500)).toBe(false);
    expect(recovery.shouldRestart(true, false, 4000)).toBe(true);
    expect(recovery.shouldRestart(true, false, 5000)).toBe(false);
    expect(recovery.shouldRestart(true, false, 6000)).toBe(true);
  });
  it('resets the backoff after the same live service recovers', () => {
    const recovery = new VoiceRecovery();
    expect(recovery.shouldRestart(true, false, 0)).toBe(true);
    expect(recovery.shouldRestart(true, false, 1000)).toBe(true);
    expect(recovery.shouldRestart(true, true, 2000)).toBe(false);
    expect(recovery.shouldRestart(true, false, 4999)).toBe(false);
    expect(recovery.shouldRestart(true, false, 5000)).toBe(true);
    expect(recovery.shouldRestart(true, false, 6000)).toBe(true);
  });
});
