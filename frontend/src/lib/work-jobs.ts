import { apiFetch } from './api';
import type { InferenceMessage } from './conversation-history';
import type { ToolCallInfo } from '../types';

export type WorkStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'cancelled' | 'interrupted' | 'failed';
export interface WorkJob {
  id: string;
  conversation_id: string;
  model: string;
  prompt: string;
  status: WorkStatus;
  phase: string;
  content: string;
  tool_calls: ToolCallInfo[];
  usage: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
  error: string;
  revision: number;
  created_at: number;
}
export interface WorkSubmission {
  conversation_id: string;
  request_key: string;
  completion: {
    model: string;
    messages: InferenceMessage[];
    stream: true;
    stream_mode: 'agent';
    max_tokens: number;
    num_ctx: number;
    temperature: number;
    character_id: 'jarvis-local' | 'mcu-jarvis';
    output_language: 'zh' | 'en';
    speech_detail: 'full';
  };
}
export interface WorkMetrics {
  total_jobs: number;
  active: number;
  total_tokens: number;
  by_status: Record<string, number>;
  by_model: Record<string, { jobs: number; completed: number; failed: number; interrupted: number; active: number; total_tokens: number; avg_duration_seconds: number | null }>;
  tools: Record<string, { calls: number; success: number; error: number }>;
}

export const workIsActive = (status: WorkStatus) => ['queued', 'running', 'cancelling'].includes(status);

async function result<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Work request failed (${response.status})`);
  }
  return response.json();
}
export async function listWorkJobs(signal?: AbortSignal): Promise<WorkJob[]> {
  const data = await result<{ jobs: WorkJob[] }>(await apiFetch('/v1/work/jobs', { signal }));
  return data.jobs;
}
export async function getWorkMetrics(signal?: AbortSignal): Promise<WorkMetrics> {
  return result(await apiFetch('/v1/work/jobs/metrics', { signal }));
}
export async function submitWork(body: WorkSubmission): Promise<WorkJob> {
  return result(await apiFetch('/v1/work/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));
}
export async function controlWork(id: string, action: 'cancel' | 'retry' | 'resume'): Promise<WorkJob> {
  return result(await apiFetch(`/v1/work/jobs/${encodeURIComponent(id)}/${action}`, { method: 'POST' }));
}

export function workStatusLabel(job: Pick<WorkJob, 'status' | 'phase'>, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    queued: ['排队中', 'Queued'], running: ['执行中', 'Running'], planning: ['规划中', 'Planning'],
    generating: ['生成中', 'Generating'], searching: ['检索中', 'Searching'], executing: ['工具执行中', 'Executing tool'],
    cancelling: ['正在停止，等待已开始的工具结束', 'Stopping; waiting for started tools'],
    completed: ['已完成', 'Completed'], cancelled: ['已取消', 'Cancelled'],
    interrupted: ['已中断，保留部分结果', 'Interrupted; partial result retained'], failed: ['失败', 'Failed'],
  };
  const key = job.status === 'running' ? job.phase : job.status;
  return (labels[key] || labels[job.status])[zh ? 0 : 1];
}
