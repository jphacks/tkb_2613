"use client";

import { useEffect, useState } from "react";

import type { Size } from "@/lib/region";

/**
 * 写真を先に読み込んでおき、読めた実寸を返す。読めるまでと読めなかったときは null。
 * 読み込む前に枠だけを出すと、読めなかったときに空の枠が一瞬見えてから消えるので、こうする。
 */
export function useLoadedSize(url: string | null): Size | null {
  const [loaded, setLoaded] = useState<{ url: string; size: Size } | null>(null);
  useEffect(() => {
    if (!url) return;
    const img = new Image();
    img.referrerPolicy = "no-referrer";
    img.onload = () => setLoaded({ url, size: { width: img.naturalWidth, height: img.naturalHeight } });
    img.src = url;
    return () => {
      img.onload = null;
    };
  }, [url]);
  return loaded && loaded.url === url ? loaded.size : null;
}
