import { useEffect } from 'react';
import zhCatalog from './zh-catalog.json';

export type InterfaceLanguage = 'zh-CN' | 'en-US';

const catalog = zhCatalog as Record<string, string>;
const originalText = new WeakMap<Text, string>();
const originalAttributes = new WeakMap<Element, Map<string, string>>();
const attributes = ['title', 'placeholder', 'aria-label', 'alt'];

export function t(value: string, language: InterfaceLanguage): string {
  if (language === 'en-US') return value;
  return (catalog[value] ?? value).replace(/您/g, '你');
}

/** Translate legacy static React UI without touching conversation content. */
export function useInterfaceLanguage(language: InterfaceLanguage): void {
  useEffect(() => {
    document.documentElement.lang = language;

    const translateNode = (root: Node) => {
      const visit = (node: Node) => {
        if (node instanceof Element) {
          if (node.closest('[data-i18n-ignore], .prose, code, pre, script, style')) return;
          let originals = originalAttributes.get(node);
          if (!originals) {
            originals = new Map();
            originalAttributes.set(node, originals);
          }
          for (const attribute of attributes) {
            const current = node.getAttribute(attribute);
            if (current === null) continue;
            let original = originals.get(attribute);
            if (original === undefined || (current !== original && current !== t(original, 'zh-CN'))) {
              original = current;
              originals.set(attribute, original);
            }
            const localized = t(original, language);
            if (localized !== current) node.setAttribute(attribute, localized);
          }
          for (const child of node.childNodes) visit(child);
        } else if (node instanceof Text) {
          if (node.parentElement?.closest('[data-i18n-ignore], .prose, code, pre, script, style')) return;
          const current = node.nodeValue ?? '';
          let original = originalText.get(node);
          if (original === undefined || (current !== original && current !== t(original.trim(), 'zh-CN'))) {
            original = current;
            originalText.set(node, original);
          }
          const trimmed = original.trim();
          const localized = t(trimmed, language);
          const next = trimmed === original ? localized : original.replace(trimmed, localized);
          if (next !== current) node.nodeValue = next;
        }
      };
      visit(root);
    };

    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === 'childList') {
          for (const node of record.addedNodes) translateNode(node);
        } else if (record.type === 'characterData') {
          translateNode(record.target);
        } else if (record.type === 'attributes') {
          translateNode(record.target);
        }
      }
    });
    translateNode(document.body);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: attributes,
    });
    return () => observer.disconnect();
  }, [language]);
}
