import { paced } from "@/lib/motion";

import "./decode.css";

/** 回す文字。地名に使われる漢字だけにする */
export const PLACE_KANJI = "東西南北京都府県市区町村郡丁目番駅前橋川山田谷野原台坂沢島本中新大小上下宮森崎浜岡井口江戸松木花寺池港関長高";

/** 解読が終わるまでの長さ（秒）。左の文字が先に止まり、最後の文字が 0.5〜0.8 秒で止まる */
const FIRST_LOCK = 0.5;
const LAST_LOCK = 0.8;
/** 1 文字あたりの最大のずらし（短い値で間延びしないように） */
const MAX_LOCK_STEP = 0.08;
/** 文字が入れ替わる間隔（秒） */
const FRAME = 0.06;

export interface CharTiming {
  /** その文字が止まるまでの秒数 */
  end: number;
  /** 止まるまでに入れ替わる回数 */
  spins: number;
}

/** n 文字の値で、左から i 番目の文字が止まる時刻と、それまでに回す回数 */
export function decodeDelays(n: number): CharTiming[] {
  const step = n > 1 ? Math.min(MAX_LOCK_STEP, (LAST_LOCK - FIRST_LOCK) / (n - 1)) : 0;
  return Array.from({ length: n }, (_, i) => {
    const end = Number((FIRST_LOCK + i * step).toFixed(3));
    return { end, spins: Math.max(3, Math.round(end / FRAME)) };
  });
}

/** 値と位置から決まる、いつも同じ並びの漢字（描くたびに変わると、読み込み直しで見た目がずれる） */
export function spinChars(value: string, index: number, count = 8): string[] {
  let seed = [...value].reduce((sum, c) => (sum * 31 + c.codePointAt(0)!) >>> 0, 7) ^ (index * 2654435761);
  return Array.from({ length: count }, () => {
    seed = (seed * 1103515245 + 12345) >>> 0;
    return PLACE_KANJI[(seed >>> 8) % PLACE_KANJI.length];
  });
}

/**
 * ランダムな漢字が回ってから、左から 1 文字ずつ本当の値に止まる。
 * 文字ごとに「回す漢字 → 本当の文字」の帯を縦に並べ、steps() で 1 文字ずつ送る。止まった状態（style の transform）が
 * 本当の文字なので、動きを減らす設定の人には最初から値がそのまま見える。読み上げには値そのものを渡す。
 */
export function DecodeText({ value, delay }: { value: string; delay: number }) {
  const chars = [...value];
  const timings = decodeDelays(chars.length);
  return (
    <span className="decode">
      <span className="sr-only">{value}</span>
      <span aria-hidden="true">
        {chars.map((ch, i) => {
          if (/\s/.test(ch)) return <span key={i}>{ch}</span>;
          const { end, spins } = timings[i];
          const strip = [...spinChars(value, i, spins), ch];
          return (
            <span key={i} className="decode-cell">
              <span className="decode-sizer">{ch}</span>
              <span
                className="decode-strip"
                style={{
                  transform: `translate(-50%, ${(-(spins / strip.length) * 100).toFixed(4)}%)`,
                  animationDelay: paced(delay),
                  animationDuration: `${end}s`,
                  animationTimingFunction: `steps(${spins}, end)`,
                }}
              >
                {strip.map((c, n) => (
                  <span key={n}>{c}</span>
                ))}
              </span>
            </span>
          );
        })}
      </span>
    </span>
  );
}
