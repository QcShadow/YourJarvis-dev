import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../types';
import { buildConversationHistory, inheritedRetrievalSources } from './conversation-history';

function answer(id = 'a', result = 'Actual detail'): ChatMessage {
  return { id, role: 'assistant', timestamp: 0, content: 'Model-written claim', toolCalls: [{
    id: 'tool', tool: 'web_search', arguments: '{"query":"武汉旅游"}', status: 'success', result,
    metadata: { sources: [{ url: 'https://example.com/source', title: 'Source', retrieved_at: '2026-09-30T01:00:00Z' }] },
  }] };
}

describe('grounded follow-up history', () => {
  it('preserves paired tool records, original dates and a separate assistant answer', () => {
    const messages = [answer(), { id: 'u', role: 'user', timestamp: 1, content: '具体说说' } as ChatMessage];
    const original = JSON.stringify(messages);
    const history = buildConversationHistory(messages);
    expect(history.map((m) => m.role)).toEqual(['assistant', 'tool', 'assistant', 'user']);
    expect(history[0].tool_calls?.[0].id).toBe(history[1].tool_call_id);
    expect(history[1].content).toContain('not a new search');
    const payload = JSON.parse(history[1].content.split('\n')[1]);
    expect(payload.data).toBe('Actual detail');
    expect(payload.sources[0].retrieved_at).toBe('2026-09-30T01:00:00Z');
    expect(history[2].content).toBe('Model-written claim');
    expect(JSON.stringify(messages)).toBe(original);
    expect(inheritedRetrievalSources(messages)).toHaveLength(1);
  });
  it('replays only the latest retrieval-bearing turn and bounds page text', () => {
    const history = buildConversationHistory([answer('old', 'Old detail'), answer('new', 'A'.repeat(7000))]);
    expect(history.filter((m) => m.role === 'tool')).toHaveLength(1);
    expect(JSON.stringify(history)).not.toContain('Old detail');
    const payload = JSON.parse(history.find((m) => m.role === 'tool')!.content.split('\n')[1]);
    expect(payload.data).toHaveLength(6000);
    expect(payload.truncated).toBe(true);
  });
  it('retains failures, excludes running tools and never copies local action results', () => {
    const first = answer();
    first.toolCalls![0].status = 'error';
    const second = answer('running');
    second.toolCalls![0].status = 'running';
    second.toolCalls!.push({ id: 'shell', tool: 'shell_exec', arguments: '{}', status: 'success', result: 'Private file' });
    const history = buildConversationHistory([first, second]);
    expect(history.filter((m) => m.role === 'tool')).toHaveLength(1);
    expect(JSON.stringify(history)).not.toContain('Private file');
    expect(inheritedRetrievalSources([first, second])).toEqual([]);
  });
  it('does not turn unsupported model citations into source records', () => {
    const message = answer();
    message.toolCalls = undefined;
    message.content = 'Source https://example.com/invented';
    expect(inheritedRetrievalSources([message])).toEqual([]);
    expect(buildConversationHistory([message])).toHaveLength(1);
  });
});
