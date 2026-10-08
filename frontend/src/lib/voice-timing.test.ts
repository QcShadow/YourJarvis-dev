import { describe, expect, it } from 'vitest';
import { voiceTurnTimingLabel } from './voice-timing';

describe('voiceTurnTimingLabel', () => {
  it('shows the route, first token, spoken reply and completed turn in Chinese', () => {
    expect(voiceTurnTimingLabel({
      model_route_ms: 120,
      first_token_ms: 810,
      reply_audio_ms: 1650,
      model_complete_ms: 2100,
      turn_total_ms: 3000,
    }, true)).toBe('路由 0.12s · 首字 0.81s · 开口 1.65s · 模型完成 2.10s · 整轮 3.00s');
  });

  it('labels wake acknowledgement and voice warmup without inventing zeros', () => {
    expect(voiceTurnTimingLabel({
      ack_audio_ms: 75,
      speech_warmup_ms: 35_880,
    }, false)).toBe('ack 0.07s · voice warmup 35.9s');
    expect(voiceTurnTimingLabel({}, true)).toBe('');
  });
});
