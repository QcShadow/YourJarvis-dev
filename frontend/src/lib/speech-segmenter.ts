/** Continuous PCM capture preserves the start of the wake phrase. */
export class SpeechSegmenter {
  private noise = 0.003;
  private pre: Float32Array[] = [];
  private frames: Float32Array[] = [];
  private voicedMs = 0;
  private quietMs = 0;
  private lengthMs = 0;
  private pauseMs = 0;
  private learnedPauseMs = 0;

  constructor(private readonly rate: number, private readonly silenceMs = 1800, private readonly adaptive = true) {}

  reset() {
    this.pre = []; this.frames = [];
    this.voicedMs = 0; this.quietMs = 0; this.lengthMs = 0;
    this.pauseMs = 0;
  }

  feed(samples: Float32Array): Blob | null {
    const copy = samples.slice();
    const ms = copy.length * 1000 / this.rate;
    let sum = 0;
    for (const sample of copy) sum += sample * sample;
    const level = Math.sqrt(sum / copy.length);
    const loud = level > Math.max(0.008, this.noise * 3);
    if (!loud) this.noise = this.noise * 0.98 + Math.min(level, 0.008) * 0.02;
    if (!this.frames.length) {
      this.pre.push(copy);
      while (this.pre.length * ms > 400) this.pre.shift();
      if (!loud) return null;
      this.frames = this.pre.slice();
    } else this.frames.push(copy);
    this.lengthMs += ms;
    if (loud) {
      if (this.quietMs >= 240) {
        this.pauseMs = Math.max(this.quietMs, this.pauseMs * 0.8);
        if (this.adaptive) {
          const bounded = Math.min(1400, this.quietMs);
          this.learnedPauseMs = this.learnedPauseMs
            ? this.learnedPauseMs * 0.75 + bounded * 0.25
            : bounded;
        }
      }
      this.voicedMs += ms; this.quietMs = 0;
    }
    else this.quietMs += ms;
    const spokenSpanMs = Math.max(0, this.lengthMs - this.quietMs);
    const durationAllowance = (spokenSpanMs >= 4000 ? 200 : 0) + (spokenSpanMs >= 8000 ? 200 : 0);
    const cadencePause = Math.max(this.pauseMs, this.learnedPauseMs);
    const extra = this.adaptive ? Math.min(800, Math.max(0, cadencePause * 1.5 - 600) + durationAllowance) : 0;
    if (this.quietMs < this.silenceMs + extra && this.lengthMs < 40000) return null;
    const result = this.voicedMs >= 160 ? pcmWav(this.frames, this.rate) : null;
    this.reset();
    return result;
  }
}

export function pcmWav(frames: Float32Array[], rate: number): Blob {
  const length = frames.reduce((sum, frame) => sum + frame.length, 0);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const label = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  label(0, 'RIFF'); view.setUint32(4, 36 + length * 2, true); label(8, 'WAVE');
  label(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  label(36, 'data'); view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const frame of frames) for (const sample of frame) {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clipped * (clipped < 0 ? 32768 : 32767), true); offset += 2;
  }
  return new Blob([buffer], { type: 'audio/wav' });
}
