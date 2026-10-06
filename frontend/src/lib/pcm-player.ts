/** Play mono signed 16-bit PCM as it arrives; stop all queued audio on cancel. */
export class PcmPlayer {
  private context = new AudioContext();
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private stopped = false;

  constructor() { void this.context.resume().catch(() => {}); }

  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    for (const source of this.sources) {
      source.onended = null;
      source.stop();
    }
    this.sources.clear();
    void this.context.close();
  }

  async play(body: ReadableStream<Uint8Array>, rate: number, signal: AbortSignal, onStart: () => void): Promise<void> {
    if (!(rate > 0 && Number.isFinite(rate))) throw new Error('Invalid speech sample rate');
    const reader = body.getReader();
    let carry: number | undefined;
    let started = false;
    let readDone = false;
    let finish: () => void = () => {};
    let reject: (reason: unknown) => void = () => {};
    const ended = new Promise<void>((resolve, fail) => { finish = resolve; reject = fail; });
    // Avoid an unhandled rejection while a read is still unwinding after abort.
    void ended.catch(() => {});
    const abort = () => {
      this.stop();
      void reader.cancel();
      reject(new DOMException('Speech stopped', 'AbortError'));
    };
    signal.addEventListener('abort', abort, { once: true });
    try {
      if (signal.aborted || this.stopped) throw new DOMException('Speech stopped', 'AbortError');
      for (;;) {
        const { done, value } = await reader.read();
        if (signal.aborted || this.stopped) throw new DOMException('Speech stopped', 'AbortError');
        if (done) break;
        let bytes = value;
        if (carry !== undefined) {
          bytes = new Uint8Array(value.length + 1);
          bytes[0] = carry;
          bytes.set(value, 1);
        }
        const count = Math.floor(bytes.length / 2);
        carry = bytes.length % 2 ? bytes[bytes.length - 1] : undefined;
        if (!count) continue;
        const buffer = this.context.createBuffer(1, count, rate);
        const samples = buffer.getChannelData(0);
        const data = new DataView(bytes.buffer, bytes.byteOffset, count * 2);
        for (let index = 0; index < count; index++) samples[index] = data.getInt16(index * 2, true) / 32768;
        const source = this.context.createBufferSource();
        source.buffer = buffer;
        source.connect(this.context.destination);
        this.sources.add(source);
        source.onended = () => {
          this.sources.delete(source);
          if (readDone && this.sources.size === 0) finish();
        };
        const start = Math.max(this.context.currentTime + 0.035, this.nextTime);
        this.nextTime = start + count / rate;
        source.start(start);
        if (!started) { started = true; onStart(); }
      }
      if (carry !== undefined) throw new Error('Speech stream ended with an incomplete sample');
      readDone = true;
      if (this.sources.size === 0) finish();
      await ended;
    } catch (error) {
      this.stop();
      throw error;
    } finally {
      signal.removeEventListener('abort', abort);
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}
