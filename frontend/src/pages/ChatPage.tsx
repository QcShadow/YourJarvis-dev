import { ChatArea } from '../components/Chat/ChatArea';
import { SystemPanel } from '../components/Chat/SystemPanel';
import { useAppStore } from '../lib/store';
import { WorkJobsPanel } from '../components/Chat/WorkJobsPanel';
import { SpeechResources } from '../components/SpeechResources';

export function ChatPage() {
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1 min-w-0 flex flex-col">
        <SpeechResources homepage />
        <WorkJobsPanel />
        <div className="flex-1 min-h-0"><ChatArea /></div>
      </div>
      {systemPanelOpen && <SystemPanel />}
    </div>
  );
}
