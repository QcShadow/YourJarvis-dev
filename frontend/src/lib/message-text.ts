/** Text helpers shared between the message renderer and voice output. */

/** Remove <think> reasoning blocks so they are neither shown nor spoken. */
export function stripThinkTags(text: string): string {
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>\s*/gi, '');
  cleaned = cleaned.replace(/^[\s\S]*?<\/think>\s*/i, '');
  return cleaned.trim();
}

/** Keep the full answer on screen, but read only a short conversational lead. */
export function spokenSummary(text: string, detail: 'brief' | 'full' = 'brief'): string {
  const cleaned = stripThinkTags(text)
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/^\s{0,3}(?:#{1,6}\s*|[-*+]\s+|\d+[.)、]\s*)/gm, '')
    .replace(/[\*_`>|]/g, '')
    .replace(/\s*\n+\s*/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
  const chinese = /[\u3400-\u9fff]/.test(cleaned);
  if (detail === 'full') return cleaned.replace(/\bJARVIS\b/gi, chinese ? '贾维斯' : 'Jarvis');
  const limit = chinese ? 72 : 145;
  const sentences = cleaned.match(/[^。！？.!?]+[。！？.!?]?/g) ?? [];
  let spoken = '';
  for (const sentence of sentences.slice(0, 2)) {
    if (spoken && spoken.length + sentence.length > limit) break;
    spoken += sentence;
    if (spoken.length >= limit * 0.6) break;
  }
  if (!spoken) spoken = cleaned.slice(0, limit);
  if (spoken.length > limit) spoken = spoken.slice(0, limit).replace(/[,，、;；]\s*[^,，、;；]*$/, '');
  spoken = spoken.trim();
  spoken = spoken.replace(/\bJARVIS\b/gi, chinese ? '贾维斯' : 'Jarvis');
  if (spoken && !/[。！？.!?]$/.test(spoken)) spoken += chinese ? '。' : '.';
  return spoken;
}

export function speechDetailSwitch(text: string): 'brief' | 'full' | null {
  if (/^(具体说说|展开说说|详细一点|详细说说|讲详细点|go into detail|tell me more|explain in detail)/i.test(text.trim())) return 'full';
  if (/^(简单一点|大致说说|简短一点|简单说说|说重点|keep it brief|briefly|summarize)/i.test(text.trim())) return 'brief';
  return null;
}
