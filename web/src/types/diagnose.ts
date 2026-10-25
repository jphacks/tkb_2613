/**
 * 診断（POST /api/diagnose）で SSE として届くイベント。TypeScript 側の正。
 * api/src/tkb_api/routes/diagnose.py と同時に変更すること。
 *
 *   event: post         data: {"post": 投稿}                             投稿を 1 件取得するたびに
 *   event: clues        data: {"post_id", "clues": [手がかり], "error"}  手がかりの取り出しが終わった順
 *   event: conclusions  data: {"clues": [全手がかり], "conclusions": [推理]}  最後に 1 回
 *   event: plan         data: {"delete", "broken", "after", "posts"}      危ない投稿。最後に 1 回
 *   event: done         data: {"posts_seen": 件数}                       最後に 1 回
 *
 * 推理の clue_indices は、同じ conclusions イベントの clues の並びでの番号。
 * plan の after（消したあとの結論）の clue_indices も、conclusions イベントの clues での番号。
 */

import { type Clue, isClue } from "./clue";
import { isPost, type Post } from "./post";

/** 推理ルールが出した結論 1 つ（engine の Conclusion） */
export interface Conclusion {
  readonly rule: string;
  /** 項目の名前（station / home_area / active_time / routine / line / full_name / age / school / birthday など。まだ試作の名前） */
  readonly attribute: string;
  readonly value: string;
  readonly clue_indices: readonly number[];
  readonly note: string;
}

/**
 * 投稿を消したらどうなるか（実際には消さない）。plan イベントと POST /api/simulate の応答に共通。
 * api/src/tkb_api/pipeline.py の simulation_json と同時に変更すること。
 */
export interface Simulation {
  /** 消す投稿の ID */
  readonly delete: readonly string[];
  /** 消すと「不明」になる項目（Conclusion の attribute） */
  readonly broken: readonly string[];
  /** 消したあとに残る結論 */
  readonly after: readonly Conclusion[];
}

/**
 * 投稿を実際に消した結果（POST /api/delete の応答）。delete は消せた投稿だけで、broken・after は
 * それを除いて推理し直した結果。api/src/tkb_api/routes/delete.py と同時に変更すること。
 */
export interface Deletion extends Simulation {
  /** 消せなかった投稿の ID */
  readonly failed: readonly string[];
}

/** 危ない投稿 1 件と、それだけを消したときに崩れる項目 */
export interface RiskyPost {
  readonly post_id: string;
  readonly broken: readonly string[];
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
  | ({
      readonly event: "plan";
      readonly posts: readonly RiskyPost[];
    } & Simulation)
  | { readonly event: "done"; readonly posts_seen: number };

const KNOWN_EVENTS = ["post", "clues", "conclusions", "plan", "done"] as const;

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
    value.clue_indices.every(
      (i) => Number.isInteger(i) && i >= 0 && i < clueCount,
    )
  );
}

function isStringList(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

/**
 * 消したらどうなるかの形を確かめる。clueCount は根拠の番号の上限
 * （conclusions イベントの clues の数。わからなければ上限なし）。
 */
export function isSimulation(
  value: unknown,
  clueCount = Number.POSITIVE_INFINITY,
): value is Simulation {
  return (
    isRecord(value) &&
    isStringList(value.delete) &&
    isStringList(value.broken) &&
    Array.isArray(value.after) &&
    value.after.every((c) => isConclusion(c, clueCount))
  );
}

/** 実際に消した結果の形を確かめる。clueCount は isSimulation と同じ */
export function isDeletion(value: unknown, clueCount = Number.POSITIVE_INFINITY): value is Deletion {
  return isRecord(value) && isStringList(value.failed) && isSimulation(value, clueCount);
}

function isRiskyPost(value: unknown): value is RiskyPost {
  return (
    isRecord(value) &&
    typeof value.post_id === "string" &&
    isStringList(value.broken)
  );
}

/**
 * SSE のイベント名と data から、診断のイベントを作る。
 * まだ知らないイベント名は null（api が先にイベントを足しても画面が止まらないように）。
 * 知っているイベント名で形が違えば InvalidDiagnoseEventError を投げる。
 */
export function toDiagnoseEvent(
  event: string,
  data: string,
): DiagnoseEvent | null {
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
    return {
      event,
      post_id: value.post_id,
      clues: value.clues,
      error: value.error,
    };
  }
  if (event === "conclusions" && isRecord(value) && isClueList(value.clues)) {
    const clueCount = value.clues.length;
    const { conclusions } = value;
    if (
      Array.isArray(conclusions) &&
      conclusions.every((c) => isConclusion(c, clueCount))
    ) {
      return {
        event,
        clues: value.clues,
        conclusions: conclusions as Conclusion[],
      };
    }
  }
  if (event === "plan" && isRecord(value) && isSimulation(value)) {
    const { posts } = value as { posts?: unknown };
    if (Array.isArray(posts) && posts.every(isRiskyPost)) {
      return {
        event,
        delete: value.delete,
        broken: value.broken,
        after: value.after,
        posts: posts as RiskyPost[],
      };
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
