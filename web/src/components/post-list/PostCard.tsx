"use client";

import { useState } from "react";

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

function PostPhoto({ image }: { image: PostImage }) {
  const [failed, setFailed] = useState(false);
  const name = image.alt || `写真 ${image.index + 1}`;

  return (
    <div
      className="overflow-hidden rounded-sm border border-ink/15 bg-paper-deep"
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
          className="block h-full w-full object-cover"
        />
      )}
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
  return (
    <article className="space-y-3 border-b border-dashed border-ink/25 pb-5">
      <time dateTime={post.created_at} className="block text-xs tracking-widest text-ink/60">
        {TIME_FORMAT.format(new Date(post.created_at))}
      </time>
      {post.text && <p className="whitespace-pre-wrap">{post.text}</p>}
      {post.images.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {post.images.map((image) => (
            <PostPhoto key={image.index} image={image} />
          ))}
        </div>
      )}
      {found && <ClueList clues={found.clues} error={found.error} label="この投稿の手がかり" />}
    </article>
  );
}
