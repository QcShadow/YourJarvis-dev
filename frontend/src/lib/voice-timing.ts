export interface VoiceTurnTiming {
  model_route_ms?: number;
  first_token_ms?: number;
  model_complete_ms?: number;
  ack_audio_ms?: number;
  reply_audio_ms?: number;
  turn_total_ms?: number;
  speech_warmup_ms?: number;
}

function seconds(value: number): string {
  return `${(value / 1000).toFixed(value >= 10_000 ? 1 : 2)}s`;
}

export function voiceTurnTimingLabel(metrics: VoiceTurnTiming, zh: boolean): string {
  const entries: Array<[string, number | undefined]> = zh
    ? [
        ['路由', metrics.model_route_ms],
        ['首字', metrics.first_token_ms],
        [metrics.reply_audio_ms ? '开口' : '确认', metrics.reply_audio_ms || metrics.ack_audio_ms],
        ['模型完成', metrics.model_complete_ms],
        ['整轮', metrics.turn_total_ms],
        ['音色预热', metrics.speech_warmup_ms],
      ]
    : [
        ['route', metrics.model_route_ms],
        ['first token', metrics.first_token_ms],
        [metrics.reply_audio_ms ? 'speech' : 'ack', metrics.reply_audio_ms || metrics.ack_audio_ms],
        ['model done', metrics.model_complete_ms],
        ['turn', metrics.turn_total_ms],
        ['voice warmup', metrics.speech_warmup_ms],
      ];
  return entries
    .filter((entry): entry is [string, number] => Number.isFinite(entry[1]) && (entry[1] || 0) > 0)
    .map(([label, value]) => `${label} ${seconds(value)}`)
    .join(' · ');
}
