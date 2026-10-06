import { describe, it, expect, vi, afterEach } from 'vitest';
import { controlWork, getWorkMetrics, submitWork, workIsActive, workStatusLabel, type WorkSubmission } from './work-jobs';

const { fetchApi } = vi.hoisted(() => ({ fetchApi: vi.fn() }));
vi.mock('./api', () => ({ apiFetch: fetchApi }));
afterEach(() => vi.resetAllMocks());

describe('background work', () => {
  it('does not mistake cancelling or interruption for completion', () => {
    expect(workIsActive('cancelling')).toBe(true);
    expect(workIsActive('interrupted')).toBe(false);
    expect(workStatusLabel({ status: 'cancelling', phase: 'generating' }, true)).toContain('等待已开始的工具');
    expect(workStatusLabel({ status: 'interrupted', phase: 'interrupted' }, false)).toContain('partial result retained');
  });
  it('submits a stable idempotency key through the authenticated API helper', async () => {
    fetchApi.mockResolvedValue(new Response(JSON.stringify({ id: 'job', status: 'queued' }), { status: 202 }));
    const body = { request_key: 'stable', conversation_id: 'chat', completion: { model: 'worker' } } as WorkSubmission;
    expect((await submitWork(body)).id).toBe('job');
    expect(fetchApi.mock.calls[0][0]).toBe('/v1/work/jobs');
    expect(JSON.parse(fetchApi.mock.calls[0][1].body).request_key).toBe('stable');
  });
  it('surfaces unsafe retry rejection rather than claiming resume succeeded', async () => {
    fetchApi.mockResolvedValue(new Response(JSON.stringify({ detail: 'Side-effecting operation; review first' }), { status: 409 }));
    await expect(controlWork('id', 'retry')).rejects.toThrow('review first');
  });
  it('uses a distinct checkpoint resume endpoint', async () => {
    fetchApi.mockResolvedValue(new Response(JSON.stringify({ id: 'resumed', status: 'queued' }), { status: 202 }));
    await controlWork('id', 'resume');
    expect(fetchApi.mock.calls[0][0]).toBe('/v1/work/jobs/id/resume');
  });
  it('loads aggregate metrics without exposing task content', async () => {
    fetchApi.mockResolvedValue(new Response(JSON.stringify({ total_jobs: 2, active: 1, total_tokens: 30, by_status: {}, by_model: {}, tools: {} }), { status: 200 }));
    expect((await getWorkMetrics()).total_tokens).toBe(30);
    expect(fetchApi.mock.calls[0][0]).toBe('/v1/work/jobs/metrics');
  });
});
