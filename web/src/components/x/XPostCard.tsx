"use client";

import { useState } from "react";

import {
  segmentXText, splitByHighlights, type XAuthor, type XHighlight, type XHighlightCategory, type XPostDisplay,
} from "@/lib/xDisplay";
import type { Post } from "@/types/post";

// X の表示要件（https://docs.x.com/developer-terms/display-requirements）に合わせた投稿の表示。
// - 投稿者：アイコン・表示名・@ユーザー名を出し、X のプロフィールへリンクする（アイコンは左）
// - 本文：投稿者の下の独立した行に、改変せずに出す。@メンション・ハッシュタグ・URL をリンクにする
// - 日時：permalink へリンクする。操作アイコン（返信・リポスト・いいね）の代わりに「Xで見る」を出す
// - X のロゴ：各投稿の右上に出す。編集された投稿は「編集済み」と出す
// 合成デモの架空投稿は X に存在しないので、X のロゴと x.com へのリンクを出さず、架空と明示する
// （表示要件は「存在しない投稿のモックアップ」を禁じている）。

const TIME_FORMAT = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const LINK_ATTRS = { target: "_blank", rel: "noopener noreferrer" } as const;

export const HIGHLIGHT_LABEL: Record<XHighlightCategory, string> = { station: "駅名", place: "地名" };

// 本文の文字は変えずに、地名・駅名の部分に背景色を付けるだけ（値ごとに数えない）
function Marked({ text, offset, highlights }: { text: string; offset: number; highlights: readonly XHighlight[] }) {
  if (highlights.length === 0) return <>{text}</>;
  return <>{splitByHighlights(text, offset, highlights).map((part, index) => part.highlight
    ? <mark key={index} data-category={part.highlight} title={HIGHLIGHT_LABEL[part.highlight]}
      className={part.highlight === "station" ? "rounded-sm bg-seeker/20 text-inherit" : "rounded-sm bg-ink/15 text-inherit"}>
      {part.text}
    </mark>
    : <span key={index}>{part.text}</span>)}</>;
}

function XLogo() {
  return (
    <svg role="img" aria-label="X" viewBox="0 0 24 24" className="h-5 w-5 shrink-0 fill-current">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

function Avatar({ author }: { author: XAuthor }) {
  const [failed, setFailed] = useState(false);
  if (!author.profile_image_url || failed) {
    return (
      <span aria-hidden="true"
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-ink/10 font-bold text-ink/60">
        {Array.from(author.name)[0] ?? "?"}
      </span>
    );
  }
  return (
    // X のプロフィール画像をそのまま表示するので next/image は使わない
    // eslint-disable-next-line @next/next/no-img-element
    <img src={author.profile_image_url} alt="" width={48} height={48} referrerPolicy="no-referrer"
      onError={() => setFailed(true)} className="h-12 w-12 shrink-0 rounded-full object-cover" />
  );
}

function MaybeLink({ href, className, children }: { href: string | null; className?: string; children: React.ReactNode }) {
  return href ? <a href={href} className={className} {...LINK_ATTRS}>{children}</a> : <span className={className}>{children}</span>;
}

export type XPostCardProps = {
  readonly post: Post;
  readonly author: XAuthor;
  readonly display: XPostDisplay;
  readonly synthetic: boolean;
  /** 集計しない表示（X_INFO_VIEW=highlight）で色を付ける範囲。コードポイント単位 */
  readonly highlights?: readonly XHighlight[];
};

export function XPostCard({ post, author, display, synthetic, highlights = [] }: XPostCardProps) {
  const profileUrl = synthetic ? null : author.profile_url;
  const permalink = synthetic ? null : display.permalink;
  const segments = segmentXText(post.text, synthetic ? [] : display.entities);
  // 各断片が本文の何文字目（コードポイント）から始まるか
  const offsets = segments.reduce<number[]>((acc, segment, index) =>
    [...acc, index === 0 ? 0 : acc[index - 1] + Array.from(segments[index - 1].text).length], []);
  const when = TIME_FORMAT.format(new Date(post.created_at));
  return (
    <article aria-label={`${author.name}の投稿`} className="rounded-sm border border-ink/20 bg-paper p-4">
      <header className="flex items-start gap-3">
        <MaybeLink href={profileUrl} className="shrink-0"><Avatar author={author} /></MaybeLink>
        <div className="min-w-0 flex-1 leading-tight">
          <MaybeLink href={profileUrl} className="block truncate font-bold hover:underline">{author.name}</MaybeLink>
          <MaybeLink href={profileUrl} className="block truncate text-sm text-ink/60 hover:underline">@{author.username}</MaybeLink>
        </div>
        {synthetic
          ? <span className="shrink-0 rounded-sm border border-ink/40 px-2 py-0.5 text-xs">架空</span>
          : <XLogo />}
      </header>
      <p className="mt-3 whitespace-pre-wrap break-words">
        {segments.map((segment, index) => segment.kind === "text"
          ? <Marked key={index} text={segment.text} offset={offsets[index]} highlights={highlights} />
          : <a key={index} href={segment.href} className="text-seeker underline-offset-2 hover:underline" {...LINK_ATTRS}>
            {/* URL は display_url を出すので色は付けない */}
            {segment.kind === "url"
              ? segment.label
              : <Marked text={segment.text} offset={offsets[index]} highlights={highlights} />}
          </a>)}
      </p>
      <footer className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink/60">
        <MaybeLink href={permalink} className="hover:underline"><time dateTime={post.created_at}>{when}</time></MaybeLink>
        {display.edited && <span>編集済み</span>}
        {permalink && <a href={permalink} className="font-bold text-ink hover:underline" {...LINK_ATTRS}>Xで見る</a>}
        {synthetic && <span>架空の投稿（Xの投稿ではありません）</span>}
      </footer>
    </article>
  );
}
