import { describe, expect, it } from 'vitest';
import { SpeechSegmenter, pcmWav } from './speech-segmenter';

const frame = (level = 0) => new Float32Array(320).fill(level);

describe('continuous wake microphone segmentation', () => {
  it('preserves onset, allows a short pause, and completes on silence', async () => {
    const vad = new SpeechSegmenter(16000, 900);
    for (let i = 0; i < 20; i++) expect(vad.feed(frame())).toBeNull();
    for (let i = 0; i < 12; i++) expect(vad.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 20; i++) expect(vad.feed(frame())).toBeNull();
    for (let i = 0; i < 12; i++) expect(vad.feed(frame(0.2))).toBeNull();
    for (let i = 0; i < 44; i++) expect(vad.feed(frame())).toBeNull();
    const wav = vad.feed(frame());
    expect(wav).not.toBeNull();
    const view = new DataView(await wav!.arrayBuffer());
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getInt16(44, true)).toBe(0);
    const samples = new Int16Array(view.buffer, 44);
    expect(samples.some((x) => x === 3276)).toBe(true);
    expect(samples.some((x) => x === 6553)).toBe(true);
  });

  it('rejects clicks and creates a valid mono PCM header', async () => {
    const vad = new SpeechSegmenter(16000);
    vad.feed(frame(0.3));
    for (let i = 0; i < 50; i++) expect(vad.feed(frame())).toBeNull();
    const wav = pcmWav([frame(1)], 48000);
    const view = new DataView(await wav.arrayBuffer());
    expect(view.getUint32(24, true)).toBe(48000);
    expect(view.getUint32(40, true)).toBe(640);
    expect(view.getInt16(44, true)).toBe(32767);
  });

  it('does not cut off a slow speaker after an internal thinking pause', () => {
    const vad = new SpeechSegmenter(16000, 1400);
    for (let i = 0; i < 15; i++) expect(vad.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 40; i++) expect(vad.feed(frame())).toBeNull();
    for (let i = 0; i < 15; i++) expect(vad.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 99; i++) expect(vad.feed(frame())).toBeNull();
    expect(vad.feed(frame())).not.toBeNull();
  });

  it('gives a long request more endpointing room without delaying short commands', () => {
    const long = new SpeechSegmenter(16000, 1400);
    for (let i = 0; i < 410; i++) expect(long.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 89; i++) expect(long.feed(frame())).toBeNull();
    expect(long.feed(frame())).not.toBeNull();

    const short = new SpeechSegmenter(16000, 1400);
    for (let i = 0; i < 15; i++) expect(short.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 69; i++) expect(short.feed(frame())).toBeNull();
    expect(short.feed(frame())).not.toBeNull();
  });

  it('learns the speaker pause cadence across utterances in one listening session', () => {
    const vad = new SpeechSegmenter(16000, 1400);
    for (let i = 0; i < 15; i++) expect(vad.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 50; i++) expect(vad.feed(frame())).toBeNull();
    for (let i = 0; i < 15; i++) expect(vad.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 109; i++) expect(vad.feed(frame())).toBeNull();
    expect(vad.feed(frame())).not.toBeNull();

    for (let i = 0; i < 15; i++) expect(vad.feed(frame(0.1))).toBeNull();
    for (let i = 0; i < 109; i++) expect(vad.feed(frame())).toBeNull();
    expect(vad.feed(frame())).not.toBeNull();
  });
});
