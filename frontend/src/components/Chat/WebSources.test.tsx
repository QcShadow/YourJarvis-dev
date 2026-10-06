import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ToolCallInfo } from '../../types';

const state = vi.hoisted(() => ({ settings: { interfaceLanguage: 'zh-CN' } }));
vi.mock('../../lib/store', () => ({ useAppStore: (selector: (s: typeof state) => unknown) => selector(state) }));
import { WebSources } from './WebSources';

const search: ToolCallInfo = { id: '1', tool: 'web_search', arguments: '{}', status: 'success', metadata: {
  sources: [{ url: 'https://example.com/source', title: '原始来源', retrieved_at: '2026-10-01T00:00:00Z' }],
} };

describe('source panel', () => {
  beforeEach(() => { state.settings.interfaceLanguage = 'zh-CN'; });
  it('renders real records and explains the limits of verification in Chinese', () => {
    const html = renderToStaticMarkup(<WebSources calls={[search]} content="https://example.com/invented" />);
    expect(html).toContain('原始来源');
    expect(html).toContain('href="https://example.com/source"');
    expect(html).toContain('无法与已记录来源对应');
    expect(html).toContain('不代表每项事实均已核验');
    expect(html).not.toContain('href="https://example.com/invented"');
  });
  it('localizes failures and sources in English', () => {
    state.settings.interfaceLanguage = 'en';
    const html = renderToStaticMarkup(<WebSources calls={[search, { ...search, status: 'error' }]} content="" />);
    expect(html).toContain('Actually retrieved sources');
    expect(html).toContain('Some retrieval failed');
    expect(html).toContain('not claim-by-claim fact checks');
  });
  it('does not imply missing legacy records are proof a link was invented', () => {
    const html = renderToStaticMarkup(<WebSources calls={[{ ...search, metadata: undefined }]} content="https://example.com/old" />);
    expect(html).toContain('历史工具记录没有结构化来源');
    expect(html).not.toContain('未在本轮检索结果中出现');
  });
  it('does not show a search panel for ordinary conversation', () => {
    expect(renderToStaticMarkup(<WebSources content="你好" />)).toBe('');
  });
  it('labels inherited sources without pretending a new search occurred', () => {
    const html = renderToStaticMarkup(<WebSources inherited={search.metadata!.sources} content="https://example.com/source" />);
    expect(html).toContain('沿用资料不代表本轮已重新查询');
    expect(html).toContain('原始来源');
    expect(html).not.toContain('来源对应，已标注');
  });
});
