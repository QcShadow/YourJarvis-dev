import { useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { apiFetch } from '../lib/api';
import { useAppStore } from '../lib/store';
import type { ChatMessage } from '../types';
import { responseLanguage, selectedVoiceProfile } from '../lib/voice-settings';
import { useVoiceActivity } from '../lib/voice-activity';
import { pauseVoiceConversation } from '../lib/voice-controls';
import { VoiceRecovery } from '../lib/voice-recovery';

interface VoiceState {
  running: boolean;
  phase: string;
  error?: string;
  revision: number;
  session_id?: string;
  model?: string;
  messages: ChatMessage[];
  last_transcript?: string;
  input_level?: number;
  followup_remaining?: number;
  foreground?: boolean;
  speech_detail?: 'brief' | 'full';
  desired_enabled?: boolean | null;
  restoring?: boolean;
}

/** Python owns recording and playback; hiding this window has no audio effect. */
export function BackgroundVoiceListener() {
  const settings = useAppStore((s) => s.settings);
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [recoveryAttempt, setRecoveryAttempt] = useState(0);
  const recovery = useRef(new VoiceRecovery());
  const controlQueue = useRef<Promise<void>>(Promise.resolve());
  const lastRevision = useRef('');
  const lastUserId = useRef('');
  const navigate = useNavigate();
  const location = useLocation();
  const enabled = settings.speechEnabled && settings.wakeWordEnabled;

  useEffect(() => {
    recovery.current.reset(Date.now());
    if (!enabled) useVoiceActivity.getState().reset();
    else useVoiceActivity.getState().update({ phase: 'starting', error: '' });
  }, [enabled]);

  useEffect(() => {
    const bridge = (window as unknown as { chrome?: { webview?: { postMessage: (data: unknown) => void } } }).chrome?.webview;
    bridge?.postMessage({ type: 'language', language: settings.interfaceLanguage });
  }, [settings.interfaceLanguage]);

  useEffect(() => {
    const pause = () => void pauseVoiceConversation();
    window.addEventListener('jarvis-pause-listening', pause);
    return () => window.removeEventListener('jarvis-pause-listening', pause);
  }, []);

  useEffect(() => {
    let disposed = false;
    const control = async () => {
      if (disposed) return;
      try {
        setError('');
        const res = await apiFetch(`/v1/voice/${enabled ? 'start' : 'stop'}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(enabled ? {
            language: settings.recognitionLanguage,
            voice_id: settings.voiceId, speed: settings.voiceSpeed,
            voice_profile: selectedVoiceProfile(settings),
            output_language: responseLanguage(settings), character_id: settings.characterId,
            silence_ms: settings.speechPauseMs,
            followup_seconds: settings.voiceIdleSeconds, interrupt_words: settings.interruptWords,
            speak: settings.voiceOutputEnabled && settings.voiceAutoplay,
            automatic_routing: settings.automaticModelRouting,
            fast_model: settings.defaultModel,
          } : {}),
        });
        if (!res.ok) {
          const details = await res.json().catch(() => ({}));
          throw new Error(details.detail || `Voice service: ${res.status}`);
        }
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : String(reason));
      }
    };
    controlQueue.current = controlQueue.current.catch(() => {}).then(control);
    return () => { disposed = true; };
  }, [enabled, settings.recognitionLanguage, settings.voiceId, settings.voiceSpeed,
    settings.voiceOutputEnabled, settings.voiceAutoplay, settings.automaticModelRouting, settings.defaultModel,
    settings.outputLanguage, settings.characterId, settings.voiceProfileZh, settings.voiceProfileEn, settings.speechPauseMs,
    settings.voiceIdleSeconds, settings.interruptWords, recoveryAttempt]);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await apiFetch('/v1/voice/state');
        if (!response.ok) throw new Error(`Voice service: ${response.status}`);
        const state = await response.json() as VoiceState;
        if (disposed) return;
        if (recovery.current.shouldRestart(enabled, state.running, Date.now(), state.desired_enabled, state.restoring)) {
          setRecoveryAttempt((attempt) => attempt + 1);
        }
        setVoice(state);
        useVoiceActivity.getState().update({ phase: state.restoring ? 'starting' : state.phase, inputLevel: state.input_level || 0,
          heard: state.last_transcript || '', error: state.error || '', remaining: state.followup_remaining,
          foreground: state.running ? state.foreground ?? true : false, speechDetail: state.speech_detail || 'brief' });
        setPollError('');
        const key = `${state.session_id}/${state.revision}`;
        if (state.session_id && state.messages.length && key !== lastRevision.current) {
          lastRevision.current = key;
          const lastUser = [...state.messages].reverse().find((m) => m.role === 'user');
          const isNew = !!lastUser && lastUser.id !== lastUserId.current;
          if (lastUser) lastUserId.current = lastUser.id;
          const select = isNew && !useAppStore.getState().streamState.isStreaming;
          useAppStore.getState().syncVoiceConversation({
            id: state.session_id,
            title: settings.interfaceLanguage === 'zh-CN' ? '与贾维斯对话' : 'Talking to Jarvis',
            model: state.model || settings.defaultModel,
            createdAt: state.messages[0].timestamp, updatedAt: Date.now(),
            messages: state.messages,
          }, select);
          if (select) navigate('/');
        }
      } catch (reason) {
        if (!disposed) setPollError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        if (!disposed) timer = setTimeout(poll, 500);
      }
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [enabled, navigate, settings.interfaceLanguage, settings.defaultModel]);

  useEffect(() => {
    if (error || pollError) useVoiceActivity.getState().update({ error: error || pollError, foreground: false });
  }, [error, pollError]);

  if (!enabled || location.pathname === '/') return null;
  const zh = settings.interfaceLanguage === 'zh-CN';
  const labels: Record<string, string> = zh ? {
    starting: '正在启动接听', listening: '说“嘿贾维斯”', armed: '我在听，可以继续说',
    transcribing: '正在识别', thinking: '正在处理', queuing: '正在交给后台处理', responding: '正在回答',
    searching: '正在联网查询', interrupting: '已打断，正在收尾',
    synthesizing: '正在准备语音', speaking: '贾维斯正在说话', stopped: '接听未运行',
  } : {
    starting: 'Starting microphone', listening: 'Say “Hey Jarvis”', armed: 'Listening — go ahead',
    transcribing: 'Recognizing', thinking: 'Working', queuing: 'Queuing background work', responding: 'Responding',
    searching: 'Searching the web', interrupting: 'Interrupted — finishing safely',
    synthesizing: 'Preparing speech', speaking: 'Jarvis is speaking', stopped: 'Microphone is stopped',
  };
  const problem = error || pollError || voice?.error;
  // The chat composer contains the full live monitor. Keep this compact control
  // on other pages without overlapping the input area or repeating transcripts.
  return <div role="status" className="fixed bottom-3 left-3 z-50 flex max-w-xl items-center gap-3 rounded-xl px-3 py-2 text-xs shadow-md"
    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
    <div><div>{problem || labels[voice?.phase || 'starting'] || voice?.phase}</div>
      <meter min={0} max={1} value={voice?.input_level || 0} aria-label={zh ? '麦克风音量' : 'Microphone level'} className="mt-1 h-1 w-20" />
      {voice?.last_transcript && <div className="mt-1 opacity-70" data-i18n-ignore>{zh ? '最近听到：' : 'Last heard: '}{voice.last_transcript}</div>}
    </div>
    <button onClick={() => void pauseVoiceConversation()}
      aria-label={zh ? '暂停语音接听' : 'Pause listening'}>{zh ? '暂停' : 'Pause'}</button>
  </div>;
}
