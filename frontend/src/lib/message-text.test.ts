import { describe, expect, it } from 'vitest';
import { spokenSummary, speechDetailSwitch } from './message-text';

describe('spokenSummary', () => {
  it('switches to complete natural speech without losing screen content', () => {
    const full = '东湖可以散步。'.repeat(30) + '```python\nsecret()\n```';
    expect(spokenSummary(full, 'full')).toBe('东湖可以散步。'.repeat(30));
    expect(speechDetailSwitch('具体说说')).toBe('full');
    expect(speechDetailSwitch('简单一点，先说重点')).toBe('brief');
    expect(speechDetailSwitch('我刚才说过详细一点这句话')).toBeNull();
  });
  it('keeps only a brief spoken lead while the caller retains full text', () => {
    const full = '我已经找到文件了。接下来会检查内容。\n## 详细步骤\n1. 第一项。2. 第二项。';
    expect(spokenSummary(full)).toBe('我已经找到文件了。接下来会检查内容。');
    expect(full).toContain('详细步骤');
  });

  it('does not read reasoning, code, or uppercase brand spelling', () => {
    expect(spokenSummary('<think>secret</think>我是 JARVIS。```bash\necho hi\n```')).toBe('我是 贾维斯。');
  });

  it('caps long spoken replies without truncating the written answer', () => {
    const full = '这是第一部分，'.repeat(30) + '结束。';
    expect(spokenSummary(full).length).toBeLessThanOrEqual(73);
    expect(full.length).toBeGreaterThan(73);
  });
});
