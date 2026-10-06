import { Mic, Pause } from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { useVoiceActivity, voiceActivityLabel } from '../../lib/voice-activity';
import { pauseVoiceConversation } from '../../lib/voice-controls';

export function VoiceActivity() {
  const enabled = useAppStore((s) => s.settings.speechEnabled && s.settings.wakeWordEnabled);
  const zh = useAppStore((s) => s.settings.interfaceLanguage === 'zh-CN');
  const activity = useVoiceActivity();
  if (!enabled) return null;
  const listening = activity.phase === 'armed' || activity.phase === 'listening';
  const active = !activity.error && activity.phase !== 'stopped';
  return <div className="jarvis-voice-composer mb-2 flex items-center gap-3 rounded-xl px-3 py-2 text-xs" data-i18n-ignore data-foreground={activity.foreground}
    style={{ background: 'var(--color-accent-subtle)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
    <Mic size={15} aria-hidden="true" style={{ color: 'var(--color-accent)' }} />
    <div className="jarvis-voice-bars flex h-6 items-center gap-0.5" data-active={active} data-listening={listening} aria-hidden="true">
      {Array.from({ length: 9 }, (_, i) => <span key={i} style={{
        height: `${4 + (listening ? activity.inputLevel * (20 - Math.abs(i - 4) * 3) : 7 + (i % 3) * 4)}px`,
        width: 3, borderRadius: 2, background: 'var(--color-accent)', animationDelay: `${i * 80}ms`,
      }} />)}
    </div>
    <div className="min-w-0 flex-1">
      <div role="status" className="truncate">{activity.error || voiceActivityLabel(activity.phase, zh)}
        {activity.foreground && <span className="ml-2 opacity-60">{activity.speechDetail === 'full' ? zh ? '详细朗读' : 'Full speech' : zh ? '简短朗读' : 'Brief speech'}</span>}
        {activity.phase === 'armed' && activity.remaining !== undefined && <span className="ml-2 opacity-60">{Math.ceil(activity.remaining)}s</span>}
      </div>
      {activity.heard && <div className="mt-1 truncate opacity-70" title={activity.heard}>{zh ? '最近听到：' : 'Last heard: '}{activity.heard}</div>}
    </div>
    <button type="button" className="rounded-md p-1.5" title={zh ? '暂停接听' : 'Pause listening'} aria-label={zh ? '暂停接听' : 'Pause listening'}
      onClick={() => void pauseVoiceConversation()}><Pause size={14} /></button>
  </div>;
}
