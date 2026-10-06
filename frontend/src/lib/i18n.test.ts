import { describe, expect, it } from 'vitest';
import { t } from './i18n';

describe('interface language', () => {
  it('switches interface labels without changing model or conversation text', () => {
    expect(t('Settings', 'zh-CN')).toBe('设置');
    expect(t('Settings', 'en-US')).toBe('Settings');
    expect(t('qwen3.5:9b', 'zh-CN')).toBe('qwen3.5:9b');
  });
});
