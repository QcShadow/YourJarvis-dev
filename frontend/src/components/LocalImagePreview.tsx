import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';

/** Fetch local output through the configured API, including desktop/auth. */
export function LocalImagePreview({ src, alt }: { src?: string; alt?: string }) {
  const local = !!src && /^\/v1\/local-images\/[0-9a-f]{32}\.png$/.test(src);
  const [preview, setPreview] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setPreview('');
    setFailed(false);
    if (!local || !src) return;
    const controller = new AbortController();
    let objectUrl = '';
    void apiFetch(src, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Image unavailable');
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      setPreview(objectUrl);
    }).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [src, local]);
  if (local && !preview) return <span>{alt || '本地图片'} · {failed ? '图片加载失败' : '加载中'}</span>;
  return <img src={local ? preview : src} alt={alt || ''} style={{ maxWidth: '100%', height: 'auto', borderRadius: 8 }} />;
}
