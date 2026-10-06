import { describe, expect, it } from 'vitest';
import type { ToolCallInfo } from '../types';
import { authorityLabel, normalizeSourceUrl, webProvenance } from './web-provenance';

function search(overrides: Partial<ToolCallInfo> = {}): ToolCallInfo {
  return { id: 'search', tool: 'web_search', arguments: '{}', status: 'success', metadata: {
    engine: 'youcom', sources: [{ title: 'Source', url: 'https://example.com/page', retrieved_at: '2026-10-01T00:00:00Z' }],
  }, ...overrides };
}

describe('retrieval provenance', () => {
  it('matches recorded URLs including fragments without validating factual claims', () => {
    const value = webProvenance([search()], '[Source](https://example.com/page#section) and https://example.com/invented.');
    expect(value.sources).toHaveLength(1);
    expect([...value.unmatched]).toEqual(['https://example.com/invented']);
  });
  it('does not convert model-written links or snippet links into retrieved records', () => {
    const value = webProvenance([search({ result: 'Snippet https://example.com/snippet' })], 'https://example.com/snippet');
    expect(value.sources).toHaveLength(1);
    expect(value.unmatched.has('https://example.com/snippet')).toBe(true);
  });
  it('does not label normal links without a search or URLs in code as citations', () => {
    expect(webProvenance([], 'https://example.com').unmatched.size).toBe(0);
    const value = webProvenance([search()], '```js\nconst u="https://example.com/code";\n```\n`https://example.com/inline`');
    expect(value.unmatched.size).toBe(0);
  });
  it('retains failure, fallback, pending and old-record uncertainty separately', () => {
    const value = webProvenance([search({ status: 'error' }), search({ status: 'running' }), search({ metadata: { degraded: true, fallback_error: 'DNS down' } })]);
    expect(value.failed).toBe(true);
    expect(value.degraded).toBe(true);
    expect(value.fallbackFailed).toBe(true);
    expect(value.pending).toBe(true);
    expect(value.missingRecords).toBe(true);
    expect(value.sources).toEqual([]);
  });
  it('deduplicates canonical URLs and filters credential-bearing or non-web links', () => {
    const value = webProvenance([search(), search()]);
    expect(value.sources).toHaveLength(1);
    expect(normalizeSourceUrl('https://example.com/#fragment')).toBe('https://example.com');
    expect(normalizeSourceUrl('javascript:alert(1)')).toBe('');
    expect(normalizeSourceUrl('https://u:p@example.com')).toBe('');
  });
  it('labels authority as a candidate rather than a fact check', () => {
    expect(authorityLabel('official', true)).toBe('官方候选');
    expect(authorityLabel(undefined, false)).toBe('General source');
  });
});
