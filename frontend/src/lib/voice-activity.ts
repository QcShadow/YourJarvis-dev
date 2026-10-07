import { create } from 'zustand';

export interface VoiceActivity {
  phase: string;
  inputLevel: number;
  heard: string;
  error: string;
  remaining?: number;
  foreground: boolean;
  speechDetail: 'brief' | 'full';
}

const initial: VoiceActivity = { phase: 'stopped', inputLevel: 0, heard: '', error: '', foreground: true, speechDetail: 'brief' };

// Transient microphone state only: never persist audio, levels or overheard speech.
export const useVoiceActivity = create<VoiceActivity & {
  update: (state: Partial<VoiceActivity>) => void;
  reset: () => void;
}>((set) => ({ ...initial, update: (state) => set(state), reset: () => set(initial) }));

export function voiceActivityLabel(phase: string, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    starting: ['正在连接麦克风', 'Connecting microphone'],
    listening: ['说“嘿贾维斯”唤醒', 'Say “Hey Jarvis” to wake'],
    armed: ['我在听，继续说', 'Listening — go ahead'],
    transcribing: ['正在识别语音', 'Recognizing speech'],
    thinking: ['正在处理，可说打断词', 'Working — interrupt phrases are available'],
    queuing: ['正在交给后台处理', 'Queuing background work'],
    searching: ['正在联网查询，可说打断词', 'Searching the web — interrupt phrases are available'],
    interrupting: ['已打断，正在收尾已开始的操作', 'Interrupted — draining already-started operations'],
    responding: ['正在回答，可说打断词', 'Responding — interrupt phrases are available'],
    synthesizing: ['正在准备朗读', 'Preparing speech'],
    speaking: ['正在朗读，可说打断词', 'Speaking — interrupt phrases are available'],
    error: ['语音暂时不可用', 'Voice unavailable'],
    stopped: ['接听未运行', 'Microphone is stopped'],
  };
  return (labels[phase] || labels.starting)[zh ? 0 : 1];
}
