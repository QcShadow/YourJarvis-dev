/** Recover a stopped service, not a conversation paused into standby. */
export class VoiceRecovery {
  private nextAttempt = 0;
  private delay = 1000;

  reset(now: number) { this.nextAttempt = now + 3000; this.delay = 1000; }

  shouldRestart(enabled: boolean, running: boolean, now: number, desiredEnabled?: boolean | null, restoring = false): boolean {
    if (!enabled || running || desiredEnabled === false || restoring) { this.reset(now); return false; }
    if (now < this.nextAttempt) return false;
    this.nextAttempt = now + this.delay;
    this.delay = Math.min(this.delay * 2, 30000);
    return true;
  }
}
