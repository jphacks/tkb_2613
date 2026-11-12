// X の表示要件（https://docs.x.com/developer-terms/display-requirements）に使う型と、
// 本文をリンクの範囲で区切る処理。本文の文字は変えない（区切って並べ直すだけ）。

export type XEntityKind = "mention" | "hashtag" | "url";
export type XEntity = {
  readonly kind: XEntityKind;
  readonly start: number;
  readonly end: number;
  readonly href: string;
  readonly display: string | null;
};
export type XPostDisplay = {
  readonly permalink: string | null;
  readonly edited: boolean;
  readonly entities: readonly XEntity[];
};
export type XAuthor = {
  readonly username: string;
  readonly name: string;
  readonly profile_image_url: string | null;
  readonly profile_url: string | null;
};
export type XDisplay = {
  readonly synthetic: boolean;
  readonly author: XAuthor;
  readonly posts: Readonly<Record<string, XPostDisplay>>;
};

export type XTextSegment =
  | { readonly kind: "text"; readonly text: string }
  // text は本文の元の文字。label は画面に出す文字（URL だけ display_url、ほかは text と同じ）
  | { readonly kind: XEntityKind; readonly text: string; readonly label: string; readonly href: string };

const KINDS = new Set<string>(["mention", "hashtag", "url"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isOptionalString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

/** リンク先は X とその短縮 URL だけを許す。 */
export function isAllowedXHref(kind: XEntityKind, href: string): boolean {
  let url: URL;
  try { url = new URL(href); } catch { return false; }
  if (url.protocol !== "https:") return false;
  return kind === "url" ? url.hostname === "t.co" : url.hostname === "x.com";
}

function isEntity(value: unknown): value is XEntity {
  return isRecord(value) && typeof value.kind === "string" && KINDS.has(value.kind) &&
    Number.isInteger(value.start) && Number.isInteger(value.end) &&
    typeof value.href === "string" && isOptionalString(value.display);
}

function isPostDisplay(value: unknown): value is XPostDisplay {
  return isRecord(value) && isOptionalString(value.permalink) && typeof value.edited === "boolean" &&
    Array.isArray(value.entities) && value.entities.every(isEntity);
}

function isAuthor(value: unknown): value is XAuthor {
  return isRecord(value) && typeof value.username === "string" && typeof value.name === "string" &&
    isOptionalString(value.profile_image_url) && isOptionalString(value.profile_url);
}

export function isXDisplay(value: unknown): value is XDisplay {
  return isRecord(value) && typeof value.synthetic === "boolean" && isAuthor(value.author) &&
    isRecord(value.posts) && Object.values(value.posts).every(isPostDisplay);
}

/**
 * 本文をリンクの範囲で区切る。start・end は X の仕様どおり Unicode のコードポイント単位。
 * 範囲が本文に収まらない・重なる・許可していないリンク先のエンティティは、ただの文字として残す。
 * 区切った断片をつなげると、必ず元の本文と同じ文字列になる。
 */
export function segmentXText(text: string, entities: readonly XEntity[]): XTextSegment[] {
  const chars = Array.from(text);
  const segments: XTextSegment[] = [];
  let cursor = 0;
  const sorted = [...entities].sort((a, b) => a.start - b.start);
  for (const entity of sorted) {
    if (entity.start < cursor || entity.end <= entity.start || entity.end > chars.length) continue;
    if (!isAllowedXHref(entity.kind, entity.href)) continue;
    if (entity.start > cursor) segments.push({ kind: "text", text: chars.slice(cursor, entity.start).join("") });
    const original = chars.slice(entity.start, entity.end).join("");
    const label = entity.kind === "url" && entity.display ? entity.display : original;
    segments.push({ kind: entity.kind, text: original, label, href: entity.href });
    cursor = entity.end;
  }
  if (cursor < chars.length) segments.push({ kind: "text", text: chars.slice(cursor).join("") });
  return segments;
}
