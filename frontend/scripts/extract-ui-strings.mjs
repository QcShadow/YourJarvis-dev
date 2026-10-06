import fs from 'node:fs';
import path from 'node:path';
import { parse } from '@babel/parser';

const sourceRoot = path.resolve(import.meta.dirname, '../src');
const entries = new Set();
const attributeNames = new Set([
  'title', 'placeholder', 'aria-label', 'label', 'description', 'alt',
]);

function looksLikeUiText(value) {
  const text = value.replace(/\s+/g, ' ').trim();
  return text.length >= 2 && text.length <= 240
    && /[A-Za-z]/.test(text)
    && !/^(https?:|\/|[A-Z_]+$|[a-z]+[-_:][\w-]+$)/.test(text)
    && !/[{}<>]/.test(text);
}

function visitFiles(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      visitFiles(fullPath);
      continue;
    }
    if (!entry.name.endsWith('.tsx') || entry.name.endsWith('.test.tsx')) continue;
    const source = parse(fs.readFileSync(fullPath, 'utf8'), {
      sourceType: 'module', plugins: ['typescript', 'jsx'],
    });
    function visit(node) {
      if (!node || typeof node !== 'object') return;
      if (node.type === 'JSXText') {
        const text = node.value.replace(/\s+/g, ' ').trim();
        if (looksLikeUiText(text)) entries.add(text);
      } else if (node.type === 'JSXAttribute' && attributeNames.has(node.name.name)) {
        if (node.value?.type === 'StringLiteral') {
          const text = node.value.value.trim();
          if (looksLikeUiText(text)) entries.add(text);
        }
      } else if (node.type === 'StringLiteral') {
        const text = node.value.trim();
        if (looksLikeUiText(text)
          && (/^[A-Z][a-z]/.test(text) || /[A-Za-z]+\s+[A-Za-z]+/.test(text))
          && !/(?:\b(?:flex|items|justify|rounded|border|hover|text|bg|px|py|gap|shadow|opacity)-\w+){2,}/.test(text)
          && !text.includes('var(--')) entries.add(text);
      }
      for (const value of Object.values(node)) {
        if (Array.isArray(value)) value.forEach(visit);
        else if (value && typeof value === 'object' && value.type) visit(value);
      }
    }
    visit(source);
  }
}

visitFiles(sourceRoot);
process.stdout.write(JSON.stringify([...entries].sort(), null, 2));
