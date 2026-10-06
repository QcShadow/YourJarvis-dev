import type { ToolCallInfo } from '../types';

export type SourceAuthority = 'official' | 'academic' | 'institutional' | 'general';
export interface RetrievedSource {
  url: string;
  title: string;
  domain?: string;
  authority?: SourceAuthority;
  retrieved_at?: string;
}

export function normalizeSourceUrl(value: string): string {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
    url.hash = '';
    return url.toString().replace(/\/$/, '');
  } catch { return ''; }
}

export function webProvenance(calls: ToolCallInfo[] = [], content = '', inherited: RetrievedSource[] = []) {
  const searches = calls.filter((call) => call.tool === 'web_search');
  const sources = new Map<string, RetrievedSource>();
  for (const source of inherited) {
    const key = normalizeSourceUrl(source.url);
    if (key) sources.set(key, source);
  }
  for (const call of searches.filter((call) => call.status === 'success')) {
    for (const source of call.metadata?.sources || []) {
      const key = normalizeSourceUrl(source.url);
      if (key && !sources.has(key)) sources.set(key, source);
    }
  }
  const unmatched = new Set<string>();
  const pending = searches.some((call) => call.status === 'running');
  const missingRecords = searches.some((call) => call.status === 'success' && !Array.isArray(call.metadata?.sources));
  if (searches.length || sources.size) {
    // Only compare explicit links, not the model's factual accuracy. Code
    // samples are not presented as citations and must not trigger warnings.
    const prose = content.replace(/```[\s\S]*?```/g, '').replace(/`[^`]*`/g, '');
    for (const match of prose.matchAll(/https?:\/\/[^\s<>\])}，。；！]+/g)) {
      const link = match[0].replace(/[.,;!?]+$/, '');
      const key = normalizeSourceUrl(link);
      if (key && !sources.has(key)) unmatched.add(key);
    }
  }
  return { searched: searches.length > 0 || sources.size > 0, sources: [...sources.values()], unmatched, pending, missingRecords,
    carried: inherited.length > 0,
    failed: searches.some((call) => call.status === 'error'),
    degraded: searches.some((call) => call.metadata?.degraded),
    fallbackFailed: searches.some((call) => Boolean(call.metadata?.fallback_error)),
  };
}

export function authorityLabel(authority: SourceAuthority | undefined, zh: boolean): string {
  const labels: Record<SourceAuthority, [string, string]> = {
    official: ['官方候选', 'Official candidate'],
    academic: ['学术候选', 'Academic candidate'],
    institutional: ['机构候选', 'Institutional candidate'],
    general: ['普通来源', 'General source'],
  };
  return labels[authority || 'general'][zh ? 0 : 1];
}
