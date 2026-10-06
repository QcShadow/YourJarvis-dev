import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, LoaderCircle, Workflow } from 'lucide-react';
import { toast } from 'sonner';
import { useAppStore, generateId } from '../../lib/store';
import { buildConversationHistory } from '../../lib/conversation-history';
import { responseLanguage } from '../../lib/voice-settings';
import { isEmbedOnlyModel } from '../../lib/model-capabilities';
import { controlWork, getWorkMetrics, listWorkJobs, submitWork, workIsActive, workStatusLabel, type WorkJob, type WorkMetrics, type WorkSubmission } from '../../lib/work-jobs';
import { MessageBubble } from './MessageBubble';

export function WorkJobsPanel() {
  const zh = useAppStore((s) => s.settings.interfaceLanguage) === 'zh-CN';
  const models = useAppStore((s) => s.models);
  const selected = useAppStore((s) => s.selectedModel);
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<WorkJob[]>([]);
  const [metrics, setMetrics] = useState<WorkMetrics | null>(null);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const pending = useRef<{ fingerprint: string; body: WorkSubmission } | null>(null);
  const observed = useRef(new Map<string, string>());
  const imported = useRef(new Set<string>());
  const active = jobs.filter((job) => workIsActive(job.status)).length;

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    const poll = async () => {
      try {
        const next = await listWorkJobs(abort.signal);
        let aggregate: WorkMetrics | null = null;
        try { aggregate = await getWorkMetrics(abort.signal); } catch { /* metrics are optional observability */ }
        if (disposed) return;
        for (const job of next) {
          const previous = observed.current.get(job.id);
          if (previous && workIsActive(previous as WorkJob['status']) && job.status === 'completed') {
            toast.success(zh ? '后台工作已完成，可展开查看结果' : 'Background work completed; expand to view the result');
          }
          if (previous && workIsActive(previous as WorkJob['status']) && ['failed', 'interrupted'].includes(job.status)) {
            toast.error(zh ? '后台工作未完成，展开查看原因及保留的结果' : 'Background work did not finish; expand to review the reason and partial result');
          }
          observed.current.set(job.id, job.status);
        }
        setJobs(next);
        if (aggregate) setMetrics(aggregate);
        setError('');
      } catch (exc) {
        if (!disposed) setError(String(exc instanceof Error ? exc.message : exc));
      } finally {
        if (!disposed) timer = setTimeout(poll, 2000);
      }
    };
    void poll();
    return () => { disposed = true; abort.abort(); clearTimeout(timer); };
  }, [zh]);

  async function submit() {
    if (!input.trim() || submitting) return;
    const state = useAppStore.getState();
    const workModel = model || selected;
    if (!workModel) return;
    const conversationId = state.activeId || state.createConversation(workModel);
    const history = buildConversationHistory(useAppStore.getState().messages);
    const completion: WorkSubmission['completion'] = {
      model: workModel, messages: [...history, { role: 'user', content: input.trim() }],
      stream: true, stream_mode: 'agent', num_ctx: 8192,
      max_tokens: Math.min(16384, Math.max(2048, state.settings.maxTokens)),
      temperature: state.settings.temperature, character_id: state.settings.characterId,
      output_language: responseLanguage(state.settings), speech_detail: 'full',
    };
    const fingerprint = JSON.stringify({ conversationId, input: input.trim(), model: workModel, settings: state.settings });
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint,
      body: { conversation_id: conversationId, request_key: generateId(), completion } };
    setSubmitting(true);
    try {
      const job = await submitWork(pending.current.body);
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      observed.current.set(job.id, job.status);
      setExpanded(job.id);
      setInput('');
      pending.current = null;
      setError('');
    } catch (exc) {
      setError(String(exc instanceof Error ? exc.message : exc));
    } finally { setSubmitting(false); }
  }

  async function control(id: string, action: 'cancel' | 'retry' | 'resume') {
    try {
      const job = await controlWork(id, action);
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
    } catch (exc) { toast.error(String(exc instanceof Error ? exc.message : exc)); }
  }

  function importResult(job: WorkJob) {
    if (job.status !== 'completed' || imported.current.has(job.id)) return;
    const state = useAppStore.getState();
    // Import into the current conversation deliberately, never into a different
    // wake session merely because an old background task happened to finish.
    const id = state.activeId || state.createConversation(job.model);
    state.addMessage(id, { id: generateId(), role: 'user', content: job.prompt, timestamp: Date.now() });
    state.addMessage(id, { id: `work-result-${job.id}`, role: 'assistant', content: job.content,
      toolCalls: job.tool_calls, timestamp: Date.now() });
    imported.current.add(job.id);
    toast.success(zh ? '结果已加入当前对话，可继续追问' : 'Result added to this conversation for follow-up');
  }

  return <section className="shrink-0 border-b" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
    <button type="button" className="flex items-center gap-2 w-full px-4 py-2 text-xs text-left cursor-pointer" aria-expanded={open} onClick={() => setOpen(!open)}>
      <Workflow size={15} /> {zh ? '后台工作' : 'Background work'}
      {active > 0 && <span role="status" className="flex items-center gap-1" style={{ color: 'var(--color-accent)' }}><LoaderCircle size={12} className="animate-spin" />{active}</span>}
      <span className="ml-auto">{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
    </button>
    {open && <div className="px-4 pb-3 overflow-y-auto space-y-2" style={{ maxHeight: '45vh' }}>
      <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{zh
        ? '任务独立排队，期间可继续对话。共用显卡仍可能排队；重启不会自动重放已开始的操作。'
        : 'Tasks run in a separate queue while chat stays available. Shared GPU requests may still queue. Started operations are not replayed after restart.'}</p>
      {metrics && <p className="text-xs" role="status" style={{ color: 'var(--color-text-tertiary)' }}>
        {zh ? `累计 ${metrics.total_jobs} 个任务 · ${metrics.total_tokens.toLocaleString()} tokens · 活跃 ${metrics.active}` : `${metrics.total_jobs} jobs · ${metrics.total_tokens.toLocaleString()} tokens · ${metrics.active} active`}
      </p>}
      <textarea aria-label={zh ? '后台工作指令' : 'Background work instruction'} value={input} onChange={(event) => setInput(event.target.value)}
        rows={2} placeholder={zh ? '交给工作模型的任务…' : 'Task for the work model…'} className="w-full rounded-lg p-2 text-sm outline-none"
        style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-border)' }} />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select aria-label={zh ? '工作模型' : 'Work model'} value={model || selected} onChange={(event) => setModel(event.target.value)}
          className="rounded p-1 max-w-full" style={{ background: 'var(--color-bg-secondary)' }}>
          {models.filter((item) => !isEmbedOnlyModel(item.id)).map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
        </select>
        <button type="button" disabled={submitting || !input.trim() || !(model || selected)} onClick={() => void submit()}
          className="rounded px-3 py-1 cursor-pointer disabled:opacity-40" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
          {submitting ? (zh ? '提交中…' : 'Submitting…') : (zh ? '交给后台执行' : 'Run in background')}
        </button>
      </div>
      {error && <p role="alert" className="text-xs" style={{ color: 'var(--color-error)' }}>{error}</p>}
      {jobs.map((job) => <article key={job.id} className="rounded-lg border p-2 text-xs" style={{ borderColor: 'var(--color-border)' }}>
        <button type="button" onClick={() => setExpanded(expanded === job.id ? null : job.id)} aria-expanded={expanded === job.id} className="w-full text-left cursor-pointer">
          <span className="block truncate">{job.prompt}</span>
          <span style={{ color: 'var(--color-text-tertiary)' }}>{workStatusLabel(job, zh)} · {job.model}
            {job.usage.total_tokens ? ` · ${job.usage.total_tokens} tokens` : ''}</span>
        </button>
        {expanded === job.id && <div className="mt-2 space-y-2">
          {workIsActive(job.status) && <button type="button" disabled={job.status === 'cancelling'} onClick={() => void control(job.id, 'cancel')} className="underline cursor-pointer disabled:opacity-40">{zh ? '取消任务' : 'Cancel task'}</button>}
          {['failed', 'interrupted', 'cancelled'].includes(job.status) && <button type="button" onClick={() => void control(job.id, 'retry')} className="underline cursor-pointer">{zh ? '重新执行（检查是否可安全重试）' : 'Retry (checks replay safety)'}</button>}
          {['failed', 'interrupted', 'cancelled'].includes(job.status) && <button type="button" onClick={() => void control(job.id, 'resume')} className="underline cursor-pointer">{zh ? '从检查点恢复（仅只读工具）' : 'Resume checkpoint (read-only tools only)'}</button>}
          {job.status === 'completed' && <button type="button" onClick={() => importResult(job)} className="underline cursor-pointer">{zh ? '将结果加入当前对话' : 'Add result to this conversation'}</button>}
          {job.error && <p role="alert" style={{ color: 'var(--color-error)' }}>{job.error}</p>}
          {!workIsActive(job.status) && job.tool_calls.some((call) => call.status === 'running') && <p style={{ color: 'var(--color-text-tertiary)' }}>{zh
            ? '部分工具未返回可确认的结果；取消不等于撤销，请在重试前检查已发生的操作。'
            : 'Some tool results were not observed. Cancellation does not undo an operation; review side effects before retrying.'}</p>}
          {(job.content || job.tool_calls.length > 0) && <MessageBubble isLive={workIsActive(job.status)} message={{
            id: `background-${job.id}`, role: 'assistant', content: job.content, timestamp: job.created_at * 1000, toolCalls: job.tool_calls,
          }} />}
        </div>}
      </article>)}
    </div>}
  </section>;
}
