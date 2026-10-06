import { describe, expect, it } from 'vitest';
import { extractWakeCommand, extractInterrupt } from '../lib/wake-word';

describe('wake command parsing', () => {
  it('matches configurable leading interrupts, including a revised request', () => {
    expect(extractInterrupt('停一下，改成英文', ['停一下'])).toEqual({ interrupted: true, command: '改成英文' });
    expect(extractInterrupt('STOP. Read the next file', ['stop'])).toEqual({ interrupted: true, command: 'Read the next file' });
    expect(extractInterrupt('stopping the process is risky', ['stop']).interrupted).toBe(false);
    expect(extractInterrupt('告诉我暂停的方法', ['暂停']).interrupted).toBe(false);
    expect(extractInterrupt('停一下', []).interrupted).toBe(false);
  });
  it('recognizes Chinese and English phrases', () => {
    expect(extractWakeCommand('嘿贾维斯，打开浏览器')).toEqual({ woke: true, command: '打开浏览器' });
    expect(extractWakeCommand('Hey Jarvis, what time is it?')).toEqual({ woke: true, command: 'what time is it?' });
  });

  it('ignores speech without the wake phrase', () => {
    expect(extractWakeCommand('打开浏览器').woke).toBe(false);
    expect(extractWakeCommand('They Jarvis is a name').woke).toBe(false);
    expect(extractWakeCommand('Hey Jarvison').woke).toBe(false);
  });

  it('accepts traditional characters and spaces from recognition', () => {
    expect(extractWakeCommand('嘿，賈維斯。')).toEqual({ woke: true, command: '' });
    expect(extractWakeCommand('黑贾维斯。')).toEqual({ woke: true, command: '' });
    expect(extractWakeCommand('嘿 贾 维 思，打开浏览器')).toEqual({ woke: true, command: '打开浏览器' });
  });
});
