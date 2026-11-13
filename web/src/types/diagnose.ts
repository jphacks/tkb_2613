/**
 * 診断（POST /api/diagnose）で SSE として届くイベント。TypeScript 側の正。
 * api/src/tkb_api/routes/diagnose.py と同時に変更すること。
 *
 *   event: post         data: {"post": 投稿}                             投稿を 1 件取得するたびに
 *   event: clues        data: {"post_id", "clues": [手がかり], "error"}  手がかりの取り出しが終わった順
 *   event: conclusions  data: {"clues": [全手がかり], "conclusions": [推理],
 *                             "profile_claim_suggestions": [最大3件の投稿ID]} 最後に 1 回
 *   event: plan         data: {"delete", "broken", "after", "posts"}      危ない投稿。最後に 1 回
 *   event: done         data: {"posts_seen": 件数}                       最後に 1 回
 *
 * 推理の clue_indices は、同じ conclusions イベントの clues の並びでの番号。
 * plan の after（消したあとの結論）の clue_indices も、conclusions イベントの clues での番号。
 */

import { type Clue, isClue } from "./clue";
import { isPost, type Post } from "./post";
import { isExternalProfileResult, isProfileCandidateSetList, isProfileRelationList, isWebFact, type ExternalLookupStatus, type ExternalProfileResult, type ProfileCandidateSet, type ProfileRelation, type WebFact } from "./profile";

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
  /** 途中で Bluesky に回数の制限で断られたか（そのときは残りを試さず failed に入る） */
  readonly bluesky_busy?: boolean;
}

/** 危ない投稿 1 件と、それだけを消したときに崩れる項目 */
export interface RiskyPost {
  readonly post_id: string;
  readonly broken: readonly string[];
}

/** 同じログインセッションで開き直したときに取得する完了済みの診断。 */
export interface DiagnosisSnapshot {
  readonly posts: readonly Post[];
  readonly clues: readonly Clue[];
  readonly conclusions: readonly Conclusion[];
  readonly plan: Simulation & { readonly posts: readonly RiskyPost[] };
  readonly profile_claims?: readonly ProfileCandidateSet[];
  readonly profile_relations?: readonly ProfileRelation[];
  readonly profile_claim_suggestions?: readonly string[];
  readonly web_facts?: readonly WebFact[];
  readonly web_lookup_status?: "not_run" | "fixture";
  readonly external_lookup_status?: ExternalLookupStatus;
  readonly external_profile_results?: readonly ExternalProfileResult[];
  readonly owner_profile_text?: string;
  readonly self_report_clues?: readonly Clue[];
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
      readonly profile_claims?: readonly ProfileCandidateSet[];
      readonly profile_relations?: readonly ProfileRelation[];
      /** Up to three diagnosis-order-stable post IDs selected by exact claim-path removal. */
      readonly profile_claim_suggestions?: readonly string[];
      readonly web_facts?: readonly WebFact[];
      readonly web_lookup_status?: "not_run" | "fixture";
      readonly external_lookup_status?: ExternalLookupStatus;
      readonly external_profile_results?: readonly ExternalProfileResult[];
      readonly owner_profile_text?: string;
      readonly self_report_clues?: readonly Clue[];
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

function isExternalLookupStatus(value: unknown): value is ExternalLookupStatus {
  return ["not_requested", "fixture", "searched", "no_results", "unavailable"].includes(value as string);
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
  return (
    isRecord(value) &&
    isStringList(value.failed) &&
    (value.bluesky_busy === undefined || typeof value.bluesky_busy === "boolean") &&
    isSimulation(value, clueCount)
  );
}

function isRiskyPost(value: unknown): value is RiskyPost {
  return (
    isRecord(value) &&
    typeof value.post_id === "string" &&
    isStringList(value.broken)
  );
}

export function isDiagnosisSnapshot(value: unknown): value is DiagnosisSnapshot {
  if (!isRecord(value) || !Array.isArray(value.posts) || !value.posts.every(isPost) || !isClueList(value.clues)) return false;
  const clueCount = value.clues.length;
  if (!Array.isArray(value.conclusions) || !value.conclusions.every((c) => isConclusion(c, clueCount))) return false;
  const plan = value.plan;
  if (!isSimulation(plan, clueCount) || !isRecord(plan) || !Array.isArray(plan.posts) || !plan.posts.every(isRiskyPost)) return false;
  let conclusionsEvent: DiagnoseEvent | null;
  try {
    conclusionsEvent = toDiagnoseEvent("conclusions", JSON.stringify({
      clues: value.clues,
      conclusions: value.conclusions,
      ...(Object.hasOwn(value, "profile_claims") ? { profile_claims: value.profile_claims } : {}),
      ...(Object.hasOwn(value, "profile_relations") ? { profile_relations: value.profile_relations } : {}),
      ...(Object.hasOwn(value, "profile_claim_suggestions") ? { profile_claim_suggestions: value.profile_claim_suggestions } : {}),
      ...(Object.hasOwn(value, "web_facts") ? { web_facts: value.web_facts } : {}),
      ...(Object.hasOwn(value, "web_lookup_status") ? { web_lookup_status: value.web_lookup_status } : {}),
      ...(Object.hasOwn(value, "external_lookup_status") ? { external_lookup_status: value.external_lookup_status } : {}),
      ...(Object.hasOwn(value, "external_profile_results") ? { external_profile_results: value.external_profile_results } : {}),
      ...(Object.hasOwn(value, "owner_profile_text") ? { owner_profile_text: value.owner_profile_text } : {}),
      ...(Object.hasOwn(value, "self_report_clues") ? { self_report_clues: value.self_report_clues } : {}),
    }));
  } catch {
    return false;
  }
  return conclusionsEvent?.event === "conclusions";
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
    const profileClaims = value.profile_claims ?? [];
    const profileRelations = value.profile_relations ?? [];
    const hasProfileRelations = Object.hasOwn(value, "profile_relations");
    const profileClaimSuggestions = Object.hasOwn(value, "profile_claim_suggestions")
      ? value.profile_claim_suggestions
      : [];
    const profileText = value.owner_profile_text ?? "";
    const selfReportClues = value.self_report_clues ?? [];
    const webFacts = value.web_facts ?? [];
    const webLookupStatus = value.web_lookup_status ?? "not_run";
    const externalLookupStatus = value.external_lookup_status ?? "not_requested";
    const externalProfileResults = value.external_profile_results ?? [];
    const webFactIds = Array.isArray(webFacts) && webFacts.every(isWebFact)
      ? new Set(webFacts.map((fact) => fact.id))
      : new Set<string>();
    const hasProfileClaims = Object.hasOwn(value, "profile_claims");
    const typedProfileClaims = isProfileCandidateSetList(profileClaims) ? profileClaims : [];
    const profileClaimsValid = !hasProfileClaims || typedProfileClaims.length > 0;
    const referencesKnownWebFact = (evidence: { readonly source?: string; readonly web_fact_id?: string | null }) =>
      evidence.source !== "public_web" ||
      (typeof evidence.web_fact_id === "string" && webFactIds.has(evidence.web_fact_id));
    const claimsReferenceKnownWebFacts = profileClaimsValid && typedProfileClaims.every((claimSet) =>
      claimSet.conflicting_evidence.every(referencesKnownWebFact) && claimSet.candidate_pool.every((claim) =>
        claim.counter_evidence.every(referencesKnownWebFact) &&
        claim.evidence.every(referencesKnownWebFact) &&
        claim.evidence_paths.every((path) => path.evidence.every(referencesKnownWebFact)),
      ),
    );
    if (
      Array.isArray(conclusions) && conclusions.every((c) => isConclusion(c, clueCount)) &&
      profileClaimsValid && typeof profileText === "string" &&
      (!hasProfileRelations || isProfileRelationList(profileRelations)) &&
      Array.isArray(profileClaimSuggestions) && profileClaimSuggestions.length <= 3 &&
      profileClaimSuggestions.every((postId) => typeof postId === "string" && postId.length > 0) &&
      new Set(profileClaimSuggestions).size === profileClaimSuggestions.length &&
      profileClaimSuggestions.every((postId) => typedProfileClaims.some((claimSet) =>
        claimSet.candidate_pool.some((claim) => claim.evidence_paths.some((path) =>
          path.evidence.some((evidence) => evidence.post_id === postId),
        )),
      )) &&
      isClueList(selfReportClues) && Array.isArray(webFacts) && webFacts.every(isWebFact) &&
      new Set(webFacts.map((fact) => fact.id)).size === webFacts.length && claimsReferenceKnownWebFacts &&
      (webLookupStatus === "not_run" || webLookupStatus === "fixture") &&
      isExternalLookupStatus(externalLookupStatus) &&
      Array.isArray(externalProfileResults) && externalProfileResults.length <= 5 && externalProfileResults.every(isExternalProfileResult) &&
      new Set(externalProfileResults.map((result) => result.id)).size === externalProfileResults.length
    ) {
      return {
        event,
        clues: value.clues,
        conclusions: conclusions as Conclusion[],
        ...(Object.hasOwn(value, "profile_claims") ? { profile_claims: typedProfileClaims } : {}),
        ...(hasProfileRelations ? { profile_relations: profileRelations as readonly ProfileRelation[] } : {}),
        ...(Object.hasOwn(value, "profile_claim_suggestions") ? { profile_claim_suggestions: profileClaimSuggestions } : {}),
        ...(Object.hasOwn(value, "web_facts") ? { web_facts: webFacts } : {}),
        ...(Object.hasOwn(value, "web_lookup_status") ? { web_lookup_status: webLookupStatus } : {}),
        ...(Object.hasOwn(value, "external_lookup_status") ? { external_lookup_status: externalLookupStatus } : {}),
        ...(Object.hasOwn(value, "external_profile_results") ? { external_profile_results: externalProfileResults } : {}),
        ...(Object.hasOwn(value, "owner_profile_text") ? { owner_profile_text: profileText } : {}),
        ...(Object.hasOwn(value, "self_report_clues") ? { self_report_clues: selfReportClues } : {}),
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
