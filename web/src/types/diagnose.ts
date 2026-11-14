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

import { isNarrowing, type Narrowing } from "./narrowing";
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
  /**
   * 確からしさ（0〜1）。根拠の手がかりの confidence を 1 − ∏(1 − c) で合成した値（engine の infer）。
   * 以前に保存した閲覧リンクにはないので省略可
   */
  readonly confidence?: number;
}

/** これ以上の確からしさの推定を「強い」と見せる（写真の顔の FACE_MIN_CONFIDENCE と同じ境目） */
export const STRONG_CONFIDENCE = 0.8;

/** 確からしさの2段階。値がない（古い閲覧リンク）ときは null で、印を出さない */
export function confidenceLevel(conclusion: Conclusion): "strong" | "weak" | null {
  if (conclusion.confidence === undefined) return null;
  return conclusion.confidence >= STRONG_CONFIDENCE ? "strong" : "weak";
}

/**
 * 投稿を消したらどうなるか（実際には消さない）。plan イベントと POST /api/simulate の応答に共通。
 * api/src/tkb_api/pipeline.py の simulate_claims_json と同時に変更すること。
 * Threads 互換ルートでは after に旧 Conclusion[] が返る場合がある。
 */
export interface Simulation {
  /** 消す投稿の ID */
  readonly delete: readonly string[];
  /** 消すと候補が崩れる項目（ProfileAttribute または旧 Conclusion の attribute） */
  readonly broken: readonly string[];
  /** 消したあとに残る結果 */
  readonly after: readonly ProfileCandidateSet[] | readonly Conclusion[];
}

export function isProfileSimulationAfter(
  after: Simulation["after"],
): after is readonly ProfileCandidateSet[] {
  return isProfileCandidateSetList(after);
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

export interface PhotoPlaceSource {
  readonly source_id: string;
  readonly provider: string;
  readonly dataset: string;
  readonly license_id: string | null;
  readonly record_id: string | null;
  readonly version: string | null;
  readonly attribution: string | null;
  readonly source_url?: string | null;
}

export interface PhotoPlaceEvidence {
  readonly kind: "clue" | "reference";
  readonly clue_index: number | null;
  readonly reference_id: string | null;
}

export interface PhotoPlaceCandidate {
  readonly place_id: string;
  readonly label: string;
  readonly place_type: "station" | "facility" | "landmark" | "address" | "area" | "unknown";
  readonly photo_relation: "visible_in_frame" | "camera_nearby" | "camera_at";
  readonly area_label: string | null;
  readonly score: number | null;
  readonly evidence: readonly PhotoPlaceEvidence[];
  readonly source_ids: readonly string[];
  readonly sources: readonly PhotoPlaceSource[];
  /** Brave候補の名称・都道府県・市区町村が、同じ結果内の公的記録1件と一致したときのその place_id。表示用の裏付けだけで、状態や推論は変えない。古い応答では省略される。 */
  readonly corroborated_by?: readonly string[];
}

export interface PhotoPlaceResult {
  readonly post_id: string;
  readonly image_index: number;
  readonly status: "candidate" | "ambiguous" | "unknown" | "unavailable";
  readonly granularity: "station" | "facility" | "address" | "area" | "unknown";
  readonly candidates: readonly PhotoPlaceCandidate[];
  readonly reason_codes: readonly string[];
  readonly lookup_status: "local_only" | "web_searched" | "reference_checked" | "unavailable";
}

/** 同じログインセッションで開き直したときに取得する完了済みの診断。 */
export interface DiagnosisSnapshot {
  readonly posts: readonly Post[];
  readonly clues: readonly Clue[];
  /**
   * 診断のあとに Bluesky から消した投稿の ID（GET /api/diagnosis だけが返す）。posts と clues は診断時のまま
   * （番号を変えない）で、conclusions と plan はここの投稿を除いて計算してある
   */
  readonly deleted?: readonly string[];
  readonly conclusions: readonly Conclusion[];
  /** f1 絞り込みの演出のデータ。推定の段がなければ null（古い応答では省略） */
  readonly narrowing?: Narrowing | null;
  readonly photo_place_results?: readonly PhotoPlaceResult[];
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
      /** f1 絞り込みの演出のデータ。形が違うときは落とす（演出だけなので診断は止めない） */
      readonly narrowing?: Narrowing | null;
      readonly photo_place_results?: readonly PhotoPlaceResult[];
      readonly profile_claims?: readonly ProfileCandidateSet[];
      readonly profile_claims_error?: boolean;
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

function isPhotoPlaceResultList(value: unknown, clues: readonly Clue[]): value is readonly PhotoPlaceResult[] {
  if (!Array.isArray(value)) return false;
  const imageKeys = new Set<string>();
  return value.every((entry: unknown) => {
    if (!isRecord(entry) || typeof entry.post_id !== "string" || !Number.isInteger(entry.image_index) ||
      (entry.image_index as number) < 0 ||
      !["candidate", "ambiguous", "unknown", "unavailable"].includes(entry.status as string) ||
      !["station", "facility", "address", "area", "unknown"].includes(entry.granularity as string) ||
      !["local_only", "web_searched", "reference_checked", "unavailable"].includes(entry.lookup_status as string) ||
      !Array.isArray(entry.candidates) || !Array.isArray(entry.reason_codes) ||
      !entry.reason_codes.every((reason) => typeof reason === "string")) return false;
    const key = `${entry.post_id}:${entry.image_index}`;
    if (imageKeys.has(key)) return false;
    imageKeys.add(key);
    const candidates = entry.candidates;
    if (entry.status === "candidate" && candidates.length !== 1) return false;
    if (entry.status === "ambiguous" && candidates.length < 2) return false;
    if (["unknown", "unavailable"].includes(entry.status as string) && candidates.length !== 0) return false;
    const ids = new Set<string>();
    return candidates.every((candidate: unknown) => {
      if (!isRecord(candidate) || typeof candidate.place_id !== "string" || !candidate.place_id ||
        typeof candidate.label !== "string" || !candidate.label ||
        !["station", "facility", "landmark", "address", "area", "unknown"].includes(candidate.place_type as string) ||
        !["visible_in_frame", "camera_nearby", "camera_at"].includes(candidate.photo_relation as string) ||
        !(candidate.area_label === null || typeof candidate.area_label === "string") ||
        !(candidate.score === null || (typeof candidate.score === "number" && candidate.score >= 0 && candidate.score <= 1)) ||
        !Array.isArray(candidate.source_ids) || !candidate.source_ids.length ||
        !candidate.source_ids.every((id) => typeof id === "string" && id.length > 0) ||
        !Array.isArray(candidate.evidence) || !candidate.evidence.length || !Array.isArray(candidate.sources)) return false;
      if (ids.has(candidate.place_id)) return false;
      ids.add(candidate.place_id);
      const validEvidence = candidate.evidence.every((item: unknown) => {
        if (!isRecord(item)) return false;
        if (item.kind === "clue" && Number.isInteger(item.clue_index) && (item.clue_index as number) >= 0 && item.reference_id === null) {
          const clue = clues[item.clue_index as number];
          return clue?.post_id === entry.post_id && clue.image_index === entry.image_index;
        }
        return item.kind === "reference" && item.clue_index === null && typeof item.reference_id === "string" && item.reference_id.length > 0;
      });
      const validSources = candidate.sources.every((source: unknown) => isRecord(source) &&
        typeof source.source_id === "string" && typeof source.provider === "string" && typeof source.dataset === "string" &&
        (source.license_id === null || typeof source.license_id === "string") &&
        (source.record_id === null || typeof source.record_id === "string") &&
        (source.version === null || typeof source.version === "string") &&
        (source.attribution === null || typeof source.attribution === "string") &&
        (!Object.hasOwn(source, "source_url") || source.source_url === null ||
          (typeof source.source_url === "string" && source.source_url.startsWith("https://"))));
      return validEvidence && validSources;
    }) && candidates.every((candidate: unknown) => {
      if (!isRecord(candidate) || !Object.hasOwn(candidate, "corroborated_by")) return true;
      const refs = candidate.corroborated_by;
      return Array.isArray(refs) && refs.length <= 1 && refs.every((id) =>
        typeof id === "string" && id !== candidate.place_id && ids.has(id));
    });
  });
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
    (!Object.hasOwn(value, "confidence") ||
      (typeof value.confidence === "number" && value.confidence >= 0 && value.confidence <= 1)) &&
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
  if (!isRecord(value) || !isStringList(value.delete) || !isStringList(value.broken) || !Array.isArray(value.after)) {
    return false;
  }
  const after: readonly unknown[] = value.after;
  return isProfileCandidateSetList(after) || after.every((c) => isConclusion(c, clueCount));
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

/**
 * ログインなしの体験デモの結果（GET /api/demo/diagnosis）。架空アカウントの診断で、形は DiagnosisSnapshot と同じ。
 * api/src/tkb_api/routes/demo.py と同時に変更すること
 */
export type DemoDiagnosis = DiagnosisSnapshot & { readonly demo: true };

export function isDemoDiagnosis(value: unknown): value is DemoDiagnosis {
  return isRecord(value) && value.demo === true && isDiagnosisSnapshot(value);
}

export function isDiagnosisSnapshot(value: unknown): value is DiagnosisSnapshot {
  if (!isRecord(value) || !Array.isArray(value.posts) || !value.posts.every(isPost) || !isClueList(value.clues)) return false;
  const clueCount = value.clues.length;
  if (Object.hasOwn(value, "deleted")) {
    const postIds = new Set(value.posts.map((post) => post.post_id));
    if (!isStringList(value.deleted) || !value.deleted.every((id) => postIds.has(id))) return false;
  }
  if (!Array.isArray(value.conclusions) || !value.conclusions.every((c) => isConclusion(c, clueCount))) return false;
  const plan = value.plan;
  if (!isSimulation(plan, clueCount) || !isRecord(plan) || !Array.isArray(plan.posts) || !plan.posts.every(isRiskyPost)) return false;
  let conclusionsEvent: DiagnoseEvent | null;
  try {
    conclusionsEvent = toDiagnoseEvent("conclusions", JSON.stringify({
      clues: value.clues,
      conclusions: value.conclusions,
      ...(Object.hasOwn(value, "narrowing") ? { narrowing: value.narrowing } : {}),
      ...(Object.hasOwn(value, "photo_place_results") ? { photo_place_results: value.photo_place_results } : {}),
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
  return conclusionsEvent?.event === "conclusions" && !conclusionsEvent.profile_claims_error;
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
    const hasPhotoPlaceResults = Object.hasOwn(value, "photo_place_results");
    const photoPlaceResults = value.photo_place_results ?? [];
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
    const profileClaimsError = hasProfileClaims && (!profileClaimsValid || !claimsReferenceKnownWebFacts);
    const safeProfileClaims = profileClaimsError ? [] : typedProfileClaims;
    const suggestionsValid = Array.isArray(profileClaimSuggestions) && profileClaimSuggestions.length <= 3 &&
      profileClaimSuggestions.every((postId) => typeof postId === "string" && postId.length > 0) &&
      new Set(profileClaimSuggestions).size === profileClaimSuggestions.length &&
      (profileClaimsError || profileClaimSuggestions.every((postId) => safeProfileClaims.some((claimSet) =>
        claimSet.candidate_pool.some((claim) => claim.evidence_paths.some((path) =>
          path.evidence.some((evidence) => evidence.post_id === postId),
        )),
      )));
    if (
      Array.isArray(conclusions) && conclusions.every((c) => isConclusion(c, clueCount)) &&
      (!hasPhotoPlaceResults || isPhotoPlaceResultList(photoPlaceResults, value.clues)) &&
      typeof profileText === "string" &&
      (!hasProfileRelations || isProfileRelationList(profileRelations)) &&
      suggestionsValid &&
      isClueList(selfReportClues) && Array.isArray(webFacts) && webFacts.every(isWebFact) &&
      new Set(webFacts.map((fact) => fact.id)).size === webFacts.length &&
      (webLookupStatus === "not_run" || webLookupStatus === "fixture") &&
      isExternalLookupStatus(externalLookupStatus) &&
      Array.isArray(externalProfileResults) && externalProfileResults.length <= 5 && externalProfileResults.every(isExternalProfileResult) &&
      new Set(externalProfileResults.map((result) => result.id)).size === externalProfileResults.length
    ) {
      return {
        event,
        clues: value.clues,
        conclusions: conclusions as Conclusion[],
        ...(Object.hasOwn(value, "narrowing") ? { narrowing: isNarrowing(value.narrowing) ? value.narrowing : null } : {}),
        ...(hasPhotoPlaceResults ? { photo_place_results: photoPlaceResults as readonly PhotoPlaceResult[] } : {}),
        ...(hasProfileClaims ? { profile_claims: safeProfileClaims } : {}),
        ...(profileClaimsError ? { profile_claims_error: true } : {}),
        ...(hasProfileRelations ? { profile_relations: profileRelations as readonly ProfileRelation[] } : {}),
        ...(Object.hasOwn(value, "profile_claim_suggestions") ? { profile_claim_suggestions: profileClaimsError ? [] : profileClaimSuggestions } : {}),
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
