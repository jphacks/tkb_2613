"use client";

import { useState } from "react";

import { type Size, toPercentBox } from "@/lib/region";
import type { Clue } from "@/types/clue";
import type { Post, PostImage } from "@/types/post";

import { ClueList } from "./ClueList";

const TIME_FORMAT = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  month: "numeric",
  day: "numeric",
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

function PostPhoto({ image, clues }: { image: PostImage; clues: readonly Clue[] }) {
  const [failed, setFailed] = useState(false);
  // 手がかりの位置は、api が解析した元の写真のピクセル座標。読み込んだ写真の実寸で割って重ねる
  const [size, setSize] = useState<Size | null>(null);
  const name = image.alt || `写真 ${image.index + 1}`;
  const boxes =
    size && !failed ? clues.flatMap((c) => (c.region ? [toPercentBox(c.region, size)] : [])) : [];

  return (
    <div
      className="relative overflow-hidden rounded-sm border border-ink/15 bg-paper-deep"
      style={{ aspectRatio: `${image.width} / ${image.height}` }}
    >
      {failed ? (
        <p className="flex h-full items-center justify-center p-3 text-center text-sm text-ink/60">
          {name}（表示できません）
        </p>
      ) : (
        // Bluesky の CDN の画像をそのまま表示するので next/image は使わない
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={image.url}
          alt={name}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          onLoad={(e) =>
            setSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })
          }
          className="block h-full w-full object-cover"
        />
      )}
      {/* 上から下へ 1 回スキャンしてから、手がかりの位置に赤枠を出す */}
      {boxes.length > 0 && <span aria-hidden="true" className="photo-scan" />}
      {boxes.map((box, i) => (
        <span key={i} aria-hidden="true" className="photo-mark" style={box} />
      ))}
    </div>
  );
}

/** 投稿から取り出した手がかり。まだ取り出していなければ undefined */
export interface PostClues {
  clues: readonly Clue[];
  error: string | null;
}

/** 診断で読んだ投稿 1 件。本文・投稿時刻・写真と、取り出した手がかりを出す。 */
export function PostCard({ post, found }: { post: Post; found?: PostClues }) {
  // 手がかりが届いた瞬間にクラスが付き、そのとき 1 回だけ揺れる
  const clues = found?.clues ?? [];
  const hit = clues.length > 0;
  return (
    <article className={`space-y-3 border-b border-dashed border-ink/25 pb-5 ${hit ? "clue-hit" : ""}`}>
      <time dateTime={post.created_at} className="block text-xs tracking-widest text-ink/60">
        {TIME_FORMAT.format(new Date(post.created_at))}
      </time>
      {post.text && <p className="whitespace-pre-wrap">{post.text}</p>}
      {post.images.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {post.images.map((image) => (
            <PostPhoto
              key={image.index}
              image={image}
              clues={clues.filter((c) => c.image_index === image.index)}
            />
          ))}
        </div>
      )}
      {found && <ClueList clues={found.clues} error={found.error} label="この投稿の手がかり" />}
    </article>
  );
}
