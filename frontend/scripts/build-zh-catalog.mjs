import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const node = process.execPath;
const extract = path.resolve(import.meta.dirname, 'extract-ui-strings.mjs');
const target = path.resolve(import.meta.dirname, '../src/lib/zh-catalog.json');
const strings = JSON.parse(execFileSync(node, [extract], { encoding: 'utf8' }));
const catalog = fs.existsSync(target) ? JSON.parse(fs.readFileSync(target, 'utf8')) : {};
const pending = strings.filter((value) => !(value in catalog));

async function translateBatch(batch) {
  const response = await fetch('http://127.0.0.1:11434/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'qwen3.5:9b', stream: false, think: false, format: 'json',
      options: { temperature: 0, num_predict: 1800, num_ctx: 8192 },
      messages: [
        { role: 'system', content: 'Translate UI strings to concise natural Simplified Chinese. Return ONLY a JSON object mapping every exact input string to its Chinese translation. Preserve brand names, model IDs, variable-looking tokens, punctuation, numbers and URLs. No explanations.' },
        { role: 'user', content: JSON.stringify(batch) },
      ],
    }),
    signal: AbortSignal.timeout(120000),
  });
  if (!response.ok) throw new Error(`Ollama HTTP ${response.status}`);
  const output = await response.json();
  return JSON.parse(output.message.content);
}

for (let index = 0; index < pending.length; index += 16) {
  const batch = pending.slice(index, index + 16);
  let translated;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      translated = await translateBatch(batch);
      break;
    } catch (error) {
      if (attempt === 2) throw error;
    }
  }
  for (const original of batch) {
    const candidate = translated[original];
    if (typeof candidate === 'string' && candidate.trim()) {
      catalog[original] = candidate.trim();
    }
  }
  fs.writeFileSync(target, JSON.stringify(catalog, null, 2) + '\n');
  process.stdout.write(`Translated ${Math.min(index + 16, pending.length)}/${pending.length}; catalog ${Object.keys(catalog).length}\n`);
}
