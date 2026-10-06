import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PcmPlayer } from './pcm-player';

let nodes: Array<{ onended: (() => void) | null; stop: ReturnType<typeof vi.fn>; start: ReturnType<typeof vi.fn>; buffer: { samples: Float32Array } | null }>;
class FakeContext {
  currentTime = 0;
  destination = {};
  resume = async () => {};
  close = async () => {};
  createBuffer(_channels: number, length: number) {
    const samples = new Float32Array(length);
    return { samples, getChannelData: () => samples };
  }
  createBufferSource() {
    const node = { onended: null as (() => void) | null, buffer: null, connect: vi.fn(), stop: vi.fn(), start: vi.fn() };
    nodes.push(node);
    return node;
  }
}
beforeEach(() => { nodes = []; vi.stubGlobal('AudioContext', FakeContext); });
afterEach(() => vi.unstubAllGlobals());

describe('streaming PCM playback', () => {
  it('plays before the server finishes, even when a sample spans network chunks', async () => {
    let send!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(controller) { send = controller; } });
    const started = vi.fn();
    const player = new PcmPlayer();
    const done = player.play(body, 24000, new AbortController().signal, started);
    send.enqueue(new Uint8Array([0]));
    send.enqueue(new Uint8Array([64]));
    await vi.waitFor(() => expect(started).toHaveBeenCalledOnce());
    expect(nodes[0].buffer?.samples[0]).toBe(0.5);
    expect(nodes[0].start).toHaveBeenCalledOnce();
    send.close();
    await Promise.resolve();
    nodes[0].onended?.();
    await done;
    player.stop();
  });

  it('stops queued speech promptly when the utterance is cancelled', async () => {
    let send!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(controller) { send = controller; } });
    const abort = new AbortController();
    const player = new PcmPlayer();
    const done = player.play(body, 24000, abort.signal, () => {});
    send.enqueue(new Uint8Array([0, 64, 0, 64]));
    await vi.waitFor(() => expect(nodes).toHaveLength(1));
    const rejected = expect(done).rejects.toMatchObject({ name: 'AbortError' });
    abort.abort();
    await rejected;
    expect(nodes[0].stop).toHaveBeenCalledOnce();
    player.stop();
  });
});
