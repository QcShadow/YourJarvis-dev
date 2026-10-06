export function extractWakeCommand(transcript: string): { woke: boolean; command: string } {
  const text = transcript.trim();
  const match = /(?:\bhey\b|\bhi\b|嘿|嗨|黑)[，,。.!！\s]*(?:jarvis\b|[贾賈][，,\s]*[维維][，,\s]*(?:斯|思)|[杰傑][维維]斯|加[维維]斯)/i.exec(text);
  if (!match) return { woke: false, command: '' };
  return { woke: true, command: text.slice(match.index + match[0].length).replace(/^[，,。.!！?？\s]+/, '').trim() };
}

export function extractInterrupt(transcript: string, words: string[]): { interrupted: boolean; command: string } {
  const text = transcript.trim();
  for (const word of [...words].sort((a, b) => b.length - a.length)) {
    const phrase = word.trim();
    if (!phrase || !text.toLocaleLowerCase().startsWith(phrase.toLocaleLowerCase())) continue;
    const rest = text.slice(phrase.length);
    if (/^[\x00-\x7F]+$/.test(phrase) && rest && !/^[\s，,。.!！?？：:；;]/.test(rest)) continue;
    const command = rest.replace(/^[\s，,。.!！?？：:；;]+/, '').trim();
    return { interrupted: true, command: /^(一下|吧|一下吧|一下啊)[。.!！\s]*$/.test(command) ? '' : command };
  }
  return { interrupted: false, command: '' };
}
