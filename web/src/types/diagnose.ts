/**
 * 診断（POST /api/diagnose）で SSE として届くイベント。TypeScript 側の正。
 * api/src/tkb_api/routes/diagnose.py と同時に変更すること。
 *
 *   event: post         data: {"post": 投稿}                             投稿を 1 件取得するたびに
 *   event: clues        data: {"post_id", "clues": [手がかり], "error"}  手がかりの取り出しが終わった順
 *   event: conclusions  data: {"clues": [全手がかり], "conclusions": [推理]}  最後に 1 回
 *   event: done         data: {"posts_seen": 件数}                       最後に 1 回
 *
 * 推理の clue_indices は、同じ conclusions イベントの clues の並びでの番号。
 */

import { type Clue, isClue } from "./clue";
import { isPost, type Post } from "./post";

/** 推理ルールが出した結論 1 つ（engine の Conclusion） */
export interface Conclusion {
  readonly rule: string;
  /** 項目の名前（station / home_area / active_time / routine など。まだ試作の名前） */
  readonly attribute: string;
  readonly value: string;
  readonly clue_indices: readonly number[];
  readonly note: string;
}

export type DiagnoseEvent =
  | { readonly event: "post"; readonly post: Post }
  | {
      readonly event: "clues";
      readonly post_id: string;
      readonly clues: readonly Clue[];
      /** 失敗したときの理由。成功なら null */
      readonly error: string | null;
    }
  | {
      readonly event: "conclusions";
      readonly clues: readonly Clue[];
      readonly conclusions: readonly Conclusion[];
    }
  | { readonly event: "done"; readonly posts_seen: number };

const KNOWN_EVENTS = ["post", "clues", "conclusions", "done"] as const;

export class InvalidDiagnoseEventError extends Error {
  constructor(readonly event: string) {
    // 中身（投稿の本文など）はエラーの文言に入れない
    super(`診断のイベント「${event}」を読み取れませんでした`);
    this.name = "InvalidDiagnoseEventError";
  }
}

function parseJson(data: string): unknown {
  try {
    return JSON.parse(data) as unknown;
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isClueList(value: unknown): value is readonly Clue[] {
  return Array.isArray(value) && value.every(isClue);
}

function isConclusion(value: unknown, clueCount: number): value is Conclusion {
  return (
    isRecord(value) &&
    typeof value.rule === "string" &&
    typeof value.attribute === "string" &&
    typeof value.value === "string" &&
    typeof value.note === "string" &&
    Array.isArray(value.clue_indices) &&
    value.clue_indices.every((i) => Number.isInteger(i) && i >= 0 && i < clueCount)
  );
}

/**
 * SSE のイベント名と data から、診断のイベントを作る。
 * まだ知らないイベント名は null（api が先にイベントを足しても画面が止まらないように）。
 * 知っているイベント名で形が違えば InvalidDiagnoseEventError を投げる。
 */
export function toDiagnoseEvent(event: string, data: string): DiagnoseEvent | null {
  if (!(KNOWN_EVENTS as readonly string[]).includes(event)) return null;
  const value = parseJson(data);
  if (event === "post" && isRecord(value) && isPost(value.post)) {
    return { event, post: value.post };
  }
  if (
    event === "clues" &&
    isRecord(value) &&
    typeof value.post_id === "string" &&
    isClueList(value.clues) &&
    (value.error === null || typeof value.error === "string")
  ) {
    return { event, post_id: value.post_id, clues: value.clues, error: value.error };
  }
  if (event === "conclusions" && isRecord(value) && isClueList(value.clues)) {
    const clueCount = value.clues.length;
    const { conclusions } = value;
    if (Array.isArray(conclusions) && conclusions.every((c) => isConclusion(c, clueCount))) {
      return { event, clues: value.clues, conclusions: conclusions as Conclusion[] };
    }
  }
  if (
    event === "done" &&
    isRecord(value) &&
    Number.isInteger(value.posts_seen) &&
    (value.posts_seen as number) >= 0
  ) {
    return { event, posts_seen: value.posts_seen as number };
  }
  throw new InvalidDiagnoseEventError(event);
}
