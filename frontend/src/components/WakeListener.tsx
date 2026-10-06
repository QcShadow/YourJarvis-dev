import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { useAppStore } from '../lib/store';
import { transcribeAudio } from '../lib/api';
import { useTtsStore } from '../lib/tts';
import { extractWakeCommand, extractInterrupt } from '../lib/wake-word';
import { SpeechSegmenter } from '../lib/speech-segmenter';
import { responseLanguage } from '../lib/voice-settings';
import { useVoiceActivity } from '../lib/voice-activity';
import { speechDetailSwitch } from '../lib/message-text';
import { pauseVoiceConversation } from '../lib/voice-controls';

type WakeStatus = 'starting' | 'listening' | 'armed' | 'transcribing' | 'error';

/** Browser listener; native desktop capture is owned by Python instead. */
export function WakeListener() {
  const enabled = useAppStore((s) => s.settings.wakeWordEnabled && s.settings.speechEnabled);
  const language = useAppStore((s) => s.settings.recognitionLanguage);
  const interfaceLanguage = useAppStore((s) => s.settings.interfaceLanguage);
  const silenceMs = useAppStore((s) => s.settings.speechPauseMs);
  const idleSeconds = useAppStore((s) => s.settings.voiceIdleSeconds);
  const navigate = useNavigate();
  const [status, setStatus] = useState<WakeStatus>('starting');
  const [error, setError] = useState('');
  const [heard, setHeard] = useState('');

  useEffect(() => {
    if (!enabled) { useVoiceActivity.getState().reset(); return; }
    let disposed = false;
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    let processor: ScriptProcessorNode | null = null;
    let mute: GainNode | null = null;
    let recognizing = false;
    let armedUntil = 0;
    let resetCapture = () => {};
    const standby = () => { armedUntil = 0; resetCapture(); setStatus('listening');
      useVoiceActivity.getState().update({ foreground: false, phase: 'listening', remaining: 0 }); };
    window.addEventListener('jarvis-voice-standby', standby);
    const submit = async (audio: Blob, controlsOnly: boolean) => {
      recognizing = true;
      if (!controlsOnly) setStatus('transcribing');
      let failed = false;
      try {
        const result = await transcribeAudio(audio, 'wake.wav', language);
        if (disposed) return;
        const spoken = result.text?.trim() ?? '';
        const wake = extractWakeCommand(spoken);
        const interrupt = extractInterrupt(spoken, useAppStore.getState().settings.interruptWords);
        if (/^(先暂停(一下)?吧?|暂停对话|回到后台|切回文字|stop listening|pause conversation)[。.!！\s]*$/i.test(spoken)) {
          if (controlsOnly || Date.now() < armedUntil) await pauseVoiceConversation();
          return;
        }
        if (controlsOnly && !wake.woke && !interrupt.interrupted) return;
        if (interrupt.interrupted && !controlsOnly && Date.now() >= armedUntil) return;
        setHeard(spoken); setError('');
        if (controlsOnly || interrupt.interrupted) {
          useTtsStore.getState().stop();
          window.dispatchEvent(new Event('jarvis-interrupt-response'));
        }
        let command = wake.command;
        if (interrupt.interrupted) {
          armedUntil = Date.now() + idleSeconds * 1000;
          command = interrupt.command;
        }
        if (wake.woke) {
          useVoiceActivity.getState().update({ foreground: true, speechDetail: 'brief' });
          const store = useAppStore.getState();
          const replyLanguage = responseLanguage(store.settings);
          const id = store.createConversation(store.selectedModel || store.settings.defaultModel);
          if (!command) {
            const now = Date.now();
            store.addMessage(id, { id: crypto.randomUUID(), role: 'user', content: spoken, timestamp: now });
            store.addMessage(id, { id: crypto.randomUUID(), role: 'assistant', content: replyLanguage === 'zh' ? '我在。' : "I'm here.", timestamp: now });
          }
          navigate('/');
          if (store.settings.voiceOutputEnabled) {
            await useTtsStore.getState().speak('wake-' + id, replyLanguage === 'zh' ? '我在。' : "I'm here.");
          }
          if (disposed) return;
          armedUntil = Date.now() + idleSeconds * 1000;
        } else if (!interrupt.interrupted && Date.now() < armedUntil) command = spoken;
        if (/^(?:停止接听|结束对话|不用了|再见|stop listening|goodbye)[。.!！\s]*$/i.test(command)) {
          standby();
        } else if (command) {
          const detail = speechDetailSwitch(command);
          if (detail) useVoiceActivity.getState().update({ speechDetail: detail });
          armedUntil = Date.now() + idleSeconds * 1000;
          useAppStore.getState().queueVoiceCommand(command);
          navigate('/');
        }
      } catch (reason) {
        failed = true;
        if (!disposed) setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        recognizing = false;
        if (!disposed) setStatus(failed ? 'error' : Date.now() < armedUntil ? 'armed' : 'listening');
      }
    };

    const start = async () => {
      try {
        setError(''); setHeard(''); setStatus('starting');
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access is unavailable');
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        if (disposed) { stream.getTracks().forEach((track) => track.stop()); return; }
        context = new AudioContext();
        await context.resume();
        if (disposed) return;
        const source = context.createMediaStreamSource(stream);
        const vad = new SpeechSegmenter(context.sampleRate, silenceMs);
        const controlVad = new SpeechSegmenter(context.sampleRate, 700);
        resetCapture = () => { vad.reset(); controlVad.reset(); };
        let wasBusy = false;
        // Continuous capture + pre-roll prevents losing "Hey" / "嘿".
        processor = context.createScriptProcessor(2048, 1, 1);
        mute = context.createGain(); mute.gain.value = 0;
        source.connect(processor); processor.connect(mute); mute.connect(context.destination);
        processor.onaudioprocess = (event) => {
          if (disposed) return;
          const busy = useTtsStore.getState().state !== 'idle' || useAppStore.getState().streamState.isStreaming;
          if (busy && armedUntil) armedUntil = Date.now() + idleSeconds * 1000;
          if (recognizing) { vad.reset(); controlVad.reset(); return; }
          if (busy !== wasBusy) {
            vad.reset(); controlVad.reset(); wasBusy = busy;
          }
          if (armedUntil && Date.now() >= armedUntil) standby();
          const samples = event.inputBuffer.getChannelData(0);
          const level = Math.min(1, Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length) * 4);
          useVoiceActivity.getState().update({ inputLevel: level,
            remaining: Math.max(0, (armedUntil - Date.now()) / 1000),
            ...(busy ? { phase: useTtsStore.getState().state !== 'idle' ? 'speaking' : 'thinking' } : {}),
          });
          const audio = (busy ? controlVad : vad).feed(samples);
          if (audio) void submit(audio, busy);
        };
        setStatus('listening');
      } catch (reason) {
        if (!disposed) { setError(reason instanceof Error ? reason.message : String(reason)); setStatus('error'); }
        stream?.getTracks().forEach((track) => track.stop());
        void context?.close();
      }
    };
    void start();
    return () => {
      disposed = true;
      window.removeEventListener('jarvis-voice-standby', standby);
      if (processor) { processor.onaudioprocess = null; processor.disconnect(); }
      mute?.disconnect(); stream?.getTracks().forEach((track) => track.stop());
      void context?.close();
    };
  }, [enabled, language, navigate, silenceMs, idleSeconds]);

  useEffect(() => {
    if (enabled) useVoiceActivity.getState().update({ phase: status, heard, error });
  }, [enabled, status, heard, error]);

  if (!enabled) return null;
  const zh = interfaceLanguage === 'zh-CN';
  const label = error ? (zh ? '语音错误: ' : 'Voice error: ') + error
    : status === 'armed' ? zh ? '我在听，可以继续说' : 'Listening — go ahead'
    : status === 'transcribing' ? zh ? '正在识别' : 'Recognizing'
    : status === 'starting' ? zh ? '正在启动麦克风' : 'Starting microphone'
    : zh ? '说“嘿贾维斯”' : 'Say “Hey Jarvis”';
  return <div role="status" className="fixed bottom-3 left-3 z-50 flex max-w-xl items-center gap-3 rounded-xl px-3 py-2 text-xs shadow-md"
    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
    <div><div>{label}</div>{heard && <div className="mt-1 opacity-70" data-i18n-ignore>{zh ? '最近听到：' : 'Last heard: '}{heard}</div>}</div>
    <button onClick={() => void pauseVoiceConversation()}>{zh ? '暂停对话' : 'Pause conversation'}</button>
  </div>;
}
