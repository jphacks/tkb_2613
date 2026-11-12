/** プロフィール項目と表示用カタログ。Python側の正は common/src/tkb_common/schemas.py。 */

export const PROFILE_CATEGORIES = [
  "identity_and_face",
  "home_and_location",
  "affiliation_and_work",
  "activity_and_family",
] as const;

export type ProfileCategory = (typeof PROFILE_CATEGORIES)[number];

export const PROFILE_CATEGORY_LABELS = {
  identity_and_face: "身元・顔",
  home_and_location: "自宅・位置",
  affiliation_and_work: "所属・職場",
  activity_and_family: "行動圏・家族",
} as const satisfies Record<ProfileCategory, string>;

export const PROFILE_ATTRIBUTE_CATALOG = {
  facial_appearance: {
    label: "顔貌（自撮り・他撮り・反射）",
    category: "identity_and_face",
    personalLevel: null, guessability: null,
  },
  full_name: {
    label: "本名（フルネーム）",
    category: "identity_and_face",
    personalLevel: null, guessability: null,
  },
  given_name: { label: "下の名前", category: "identity_and_face", personalLevel: null, guessability: null },
  nickname: { label: "呼ばれている名前", category: "identity_and_face", personalLevel: null, guessability: null },
  other_social_account: {
    label: "別SNSのアカウント / 本垢",
    category: "identity_and_face",
    personalLevel: null, guessability: null,
  },
  realtime_location: {
    label: "リアルタイムの現在地",
    category: "home_and_location",
    personalLevel: null, guessability: null,
  },
  home_building: { label: "自宅の建物候補", category: "home_and_location", personalLevel: null, guessability: null },
  home_room: { label: "自宅の部屋・階・位置", category: "home_and_location", personalLevel: null, guessability: null },
  home_nearest_station: { label: "自宅の最寄り駅", category: "home_and_location", personalLevel: null, guessability: null },
  regular_station: { label: "日常的に利用する駅", category: "home_and_location", personalLevel: null, guessability: null },
  regular_line: { label: "日常的に利用する路線", category: "home_and_location", personalLevel: null, guessability: null },
  residential_area: {
    label: "居住エリア（市区町村・町域）",
    category: "home_and_location",
    personalLevel: null, guessability: null,
  },
  announced_long_absence: { label: "予告された長期不在", category: "home_and_location", personalLevel: null, guessability: null },
  actual_home_absence: { label: "実際の自宅不在", category: "home_and_location", personalLevel: null, guessability: null },
  employer_name: { label: "雇用主名の推定", category: "affiliation_and_work", personalLevel: null, guessability: null },
  workplace_building_candidate: { label: "勤務先建物候補", category: "affiliation_and_work", personalLevel: null, guessability: null },
  workplace_area: {
    label: "勤務先エリア（オフィス街）",
    category: "affiliation_and_work",
    personalLevel: null, guessability: null,
  },
  school: {
    label: "通学先（大学・キャンパス・学校）",
    category: "affiliation_and_work",
    personalLevel: null, guessability: null,
  },
  frequent_shop: {
    label: "行きつけの店（ジム・美容院・カフェ）",
    category: "activity_and_family",
    personalLevel: null, guessability: null,
  },
  vehicle_model: { label: "自家用車の車種", category: "activity_and_family", personalLevel: null, guessability: null },
  partial_plate: { label: "ナンバーの一部", category: "activity_and_family", personalLevel: null, guessability: null },
  partner_status: { label: "配偶者・交際相手の有無", category: "activity_and_family", personalLevel: null, guessability: null },
  partner_attributes: { label: "配偶者・交際相手の属性", category: "activity_and_family", personalLevel: null, guessability: null },
  child_age: { label: "子どもの年齢", category: "activity_and_family", personalLevel: null, guessability: null },
  child_school: { label: "子どもの通園・通学先", category: "activity_and_family", personalLevel: null, guessability: null },
} as const;

export type ProfileAttribute = keyof typeof PROFILE_ATTRIBUTE_CATALOG;
export type ProfileAttributeMetadata = (typeof PROFILE_ATTRIBUTE_CATALOG)[ProfileAttribute];
export type Guessability = ProfileAttributeMetadata["guessability"];
export type ProfileStatus = "found" | "weak" | "unknown";

export interface WebFact {
  readonly id: string;
  readonly subject: string;
  readonly relation: string;
  readonly object: string;
  readonly source_url: string;
  readonly source_title: string;
  readonly source_kind: "official_organization" | "public_registry" | "other";
  readonly excerpt: string;
  readonly retrieved_at: string;
  readonly verification_status: "verified" | "unverified" | "conflict" | "stale";
}

export interface ExternalOwnerEvidence {
  readonly kind: "profile_text" | "post_text";
  readonly post_id: string | null;
  readonly excerpt: string;
}

/** Public search hit. owner_linked means only that the owner's own profile/post links this URL. */
export interface ExternalProfileResult {
  readonly id: string;
  readonly url: string;
  readonly domain: string;
  readonly title: string;
  readonly status: "candidate" | "owner_linked";
  readonly owner_evidence: ExternalOwnerEvidence | null;
}

export type ExternalLookupStatus = "not_requested" | "fixture" | "searched" | "no_results" | "unavailable";

export function isExternalProfileResult(value: unknown): value is ExternalProfileResult {
  if (!isRecord(value)) return false;
  const keys = ["id", "url", "domain", "title", "status", "owner_evidence"];
  if (!Object.keys(value).every((key) => keys.includes(key))) return false;
  if (!["id", "url", "domain", "title"].every((key) => typeof value[key] === "string" && (value[key] as string).length > 0)) return false;
  let url: URL;
  try { url = new URL(value.url as string); } catch { return false; }
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (
    url.protocol !== "https:" || url.username || url.password || url.port || host !== (value.domain as string).toLowerCase() ||
    host.length > 253 || host.split(".").length < 2 || /^\d{1,3}(?:\.\d{1,3}){3}$/.test(host) ||
    host === "localhost.localdomain" ||
    [".localhost", ".local", ".localdomain", ".internal", ".test", ".invalid", ".home", ".lan", ".home.arpa"].some((suffix) => host.endsWith(suffix)) ||
    host.split(".").some((label) => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))
  ) return false;
  if (value.status === "candidate") return value.owner_evidence === null;
  if (value.status !== "owner_linked" || !isRecord(value.owner_evidence)) return false;
  const evidence = value.owner_evidence;
  if (!Object.keys(evidence).every((key) => ["kind", "post_id", "excerpt"].includes(key)) || typeof evidence.excerpt !== "string" || !evidence.excerpt) return false;
  return (evidence.kind === "profile_text" && evidence.post_id === null) ||
    (evidence.kind === "post_text" && typeof evidence.post_id === "string" && evidence.post_id.length > 0);
}

export interface ProfileEvidence {
  readonly post_id: string | null;
  readonly clue_index: number | null;
  readonly required: boolean;
  /** open_data は事前に取得した公的な公開データ。excerpt に出典と注記が入り、投稿は指さない */
  readonly source?: "clue" | "post_text" | "profile_text" | "image_alt" | "public_web" | "open_data";
  readonly image_index?: number | null;
  readonly excerpt?: string | null;
  readonly web_fact_id?: string | null;
}

export interface ProfileEvidencePath {
  readonly evidence: readonly ProfileEvidence[];
  readonly confidence: number;
}

export interface ClaimAssessment {
  readonly minimal_scope: "bluesky" | "bluesky_plus_public_web" | "bluesky_plus_offline" | null;
  readonly offline_subtype: string | null;
  readonly psychological_resistance: number | null;
  readonly persona_context: string | null;
  readonly inference_ease: number | null;
  readonly inference_ease_basis: "provisional" | "measured" | null;
  readonly harm_severity: number | null;
  readonly harm_scenario: string | null;
  readonly harm_prerequisites: readonly string[];
  readonly harm_status: "applicable" | "prerequisites_unmet" | "unknown";
}

/** confidence は 0..1 の値。検出ロジック未実装のため、校正済み確率とは限らない。 */
interface ProfileItemBase {
  readonly attribute: ProfileAttribute;
  readonly confidence: number;
  readonly evidence: readonly ProfileEvidence[];
  readonly evidence_paths?: readonly ProfileEvidencePath[];
  readonly assessment?: ClaimAssessment;
}

export type ProfileItem =
  | (ProfileItemBase & { readonly value: string; readonly status: "found" | "weak" })
  | (ProfileItemBase & { readonly value: null; readonly status: "unknown" });

/** Recalculate a known claim from its existing OR-of-AND paths only. */
export function profileClaimAfterDeletion(item: ProfileItem, deletedPostIds: ReadonlySet<string>): ProfileItem | null | undefined {
  if (!item.evidence_paths?.length) return undefined;
  const survivingPaths = item.evidence_paths.filter((path) =>
    !path.evidence.some((reference) => reference.post_id !== null && deletedPostIds.has(reference.post_id)),
  );
  if (survivingPaths.length === 0) return null;
  const confidence = Math.max(...survivingPaths.map((path) => path.confidence));
  if (confidence < 0.5) return null;
  if (item.status === "unknown") return undefined;
  const hasBlueskyOnlyPath = survivingPaths.some((path) => path.evidence.every((reference) => reference.source !== "public_web"));
  return {
    ...item,
    evidence_paths: survivingPaths,
    evidence: survivingPaths.flatMap((path) => path.evidence),
    confidence,
    status: confidence >= 0.8 ? "found" : "weak",
    ...(item.assessment ? {
      assessment: {
        ...item.assessment,
        minimal_scope: hasBlueskyOnlyPath ? "bluesky" : "bluesky_plus_public_web",
      },
    } : {}),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isWebFact(value: unknown): value is WebFact {
  if (!isRecord(value)) return false;
  const stringFields = ["id", "subject", "relation", "object", "source_url", "source_title", "excerpt", "retrieved_at"];
  if (!Object.keys(value).every((key) => [...stringFields, "source_kind", "verification_status"].includes(key))) return false;
  if (!stringFields.every((key) => typeof value[key] === "string" && (value[key] as string).trim().length > 0)) return false;
  try {
    const url = new URL(value.source_url as string);
    if (url.protocol !== "https:" || url.username || url.password) return false;
  } catch { return false; }
  return !Number.isNaN(Date.parse(value.retrieved_at as string)) &&
    ["official_organization", "public_registry", "other"].includes(value.source_kind as string) &&
    ["verified", "unverified", "conflict", "stale"].includes(value.verification_status as string);
}

function isProfileEvidence(value: unknown): value is ProfileEvidence {
  if (!isRecord(value)) return false;
  const source = value.source ?? "clue";
  return (
    Object.keys(value).every((key) =>
      ["post_id", "clue_index", "required", "source", "image_index", "excerpt", "web_fact_id"].includes(key),
    ) &&
    typeof value.required === "boolean" &&
    ["clue", "post_text", "profile_text", "image_alt", "public_web", "open_data"].includes(source as string) &&
    (source === "public_web" || value.web_fact_id === null || value.web_fact_id === undefined) &&
    ((source === "clue" && typeof value.post_id === "string" && Number.isInteger(value.clue_index) && (value.clue_index as number) >= 0 && (value.image_index === null || value.image_index === undefined)) ||
      (source === "post_text" && typeof value.post_id === "string" && value.clue_index === null && (value.image_index === null || value.image_index === undefined) && typeof value.excerpt === "string") ||
      (source === "profile_text" && value.post_id === null && value.clue_index === null && typeof value.excerpt === "string") ||
      (source === "image_alt" && typeof value.post_id === "string" && value.clue_index === null && Number.isInteger(value.image_index) && typeof value.excerpt === "string") ||
      (source === "open_data" && value.post_id === null && value.clue_index === null && (value.image_index === null || value.image_index === undefined) && typeof value.excerpt === "string" && value.excerpt.length > 0) ||
      (source === "public_web" && value.post_id === null && value.clue_index === null && (value.image_index === null || value.image_index === undefined) && (value.excerpt === null || value.excerpt === undefined) && typeof value.web_fact_id === "string" && value.web_fact_id.length > 0))
  );
}

function isClaimAssessment(value: unknown): value is ClaimAssessment {
  if (!isRecord(value)) return false;
  const rating = (v: unknown) => v === null || (Number.isInteger(v) && (v as number) >= 1 && (v as number) <= 5);
  const baseValid = ["minimal_scope", "offline_subtype", "psychological_resistance", "persona_context", "inference_ease", "inference_ease_basis", "harm_severity", "harm_scenario", "harm_prerequisites", "harm_status"].every((k) => Object.hasOwn(value, k)) &&
    (value.minimal_scope === null || ["bluesky", "bluesky_plus_public_web", "bluesky_plus_offline"].includes(value.minimal_scope as string)) &&
    (value.offline_subtype === null || typeof value.offline_subtype === "string") && rating(value.psychological_resistance) &&
    (value.persona_context === null || typeof value.persona_context === "string") && rating(value.inference_ease) &&
    (value.inference_ease_basis === null || ["provisional", "measured"].includes(value.inference_ease_basis as string)) && rating(value.harm_severity) &&
    (value.harm_scenario === null || typeof value.harm_scenario === "string") && Array.isArray(value.harm_prerequisites) && value.harm_prerequisites.every((v) => typeof v === "string") &&
    ["applicable", "prerequisites_unmet", "unknown"].includes(value.harm_status as string);
  if (!baseValid) return false;
  const prerequisites = value.harm_prerequisites as string[];
  if (value.minimal_scope === "bluesky_plus_offline" ? typeof value.offline_subtype !== "string" || !value.offline_subtype : value.offline_subtype !== null) return false;
  if (value.psychological_resistance !== null && typeof value.persona_context !== "string") return false;
  if ((value.inference_ease === null) !== (value.inference_ease_basis === null)) return false;
  if (value.harm_status === "applicable") return value.harm_severity !== null && typeof value.harm_scenario === "string" && prerequisites.length > 0;
  if (value.harm_status === "prerequisites_unmet") return value.harm_severity === null && typeof value.harm_scenario === "string" && prerequisites.length > 0;
  return value.harm_severity === null;
}

export function isProfileItem(value: unknown): value is ProfileItem {
  if (!isRecord(value)) return false;
  if (
    !Object.keys(value).every((key) =>
      ["attribute", "value", "confidence", "status", "evidence", "evidence_paths", "assessment"].includes(key),
    ) ||
    typeof value.attribute !== "string" ||
    !Object.hasOwn(PROFILE_ATTRIBUTE_CATALOG, value.attribute)
  ) {
    return false;
  }
  if (
    typeof value.confidence !== "number" ||
    !Number.isFinite(value.confidence) ||
    value.confidence < 0 ||
    value.confidence > 1 ||
    !Array.isArray(value.evidence) ||
    !value.evidence.every(isProfileEvidence)
    || (value.evidence_paths !== undefined && (!Array.isArray(value.evidence_paths) || !value.evidence_paths.every((path) => isRecord(path) && typeof path.confidence === "number" && path.confidence >= 0 && path.confidence <= 1 && Array.isArray(path.evidence) && path.evidence.length >= 2 && path.evidence.every(isProfileEvidence))))
    || (value.assessment !== undefined && !isClaimAssessment(value.assessment))
  ) {
    return false;
  }
  if (value.status === "unknown") return value.value === null;
  return (
    (value.status === "found" || value.status === "weak") &&
    typeof value.value === "string" &&
    value.value.trim().length > 0
  );
}

/** 推定の根拠に使った公開データの出典（重複を除く）。画面で推定の下に出す */
export function openDataCitations(item: ProfileItem): string[] {
  return [...new Set(item.evidence.flatMap((reference) =>
    reference.source === "open_data" && reference.excerpt ? [reference.excerpt] : [],
  ))];
}
