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
    personalLevel: 5,
    guessability: "A",
  },
  full_name: {
    label: "本名（フルネーム）",
    category: "identity_and_face",
    personalLevel: 5,
    guessability: "B",
  },
  given_name_or_nickname: {
    label: "下の名前 / 呼ばれている名前",
    category: "identity_and_face",
    personalLevel: 4,
    guessability: "A〜B",
  },
  other_social_account: {
    label: "別SNSのアカウント / 本垢",
    category: "identity_and_face",
    personalLevel: 4,
    guessability: "A",
  },
  realtime_location: {
    label: "リアルタイムの現在地",
    category: "home_and_location",
    personalLevel: 5,
    guessability: "A",
  },
  home_building_or_room: {
    label: "自宅の建物外観・部屋の位置",
    category: "home_and_location",
    personalLevel: 5,
    guessability: "B",
  },
  commute_station_or_line: {
    label: "最寄り駅 / 日常の利用路線",
    category: "home_and_location",
    personalLevel: 4,
    guessability: "A〜B",
  },
  residential_area: {
    label: "居住エリア（市区町村・町域）",
    category: "home_and_location",
    personalLevel: 4,
    guessability: "B",
  },
  long_term_home_absence: {
    label: "自宅の長期不在（旅行・帰省中）",
    category: "home_and_location",
    personalLevel: 4,
    guessability: "A〜B",
  },
  workplace: {
    label: "勤務先（企業名・店舗・ビル）",
    category: "affiliation_and_work",
    personalLevel: 4,
    guessability: "B",
  },
  workplace_area: {
    label: "勤務先エリア（オフィス街）",
    category: "affiliation_and_work",
    personalLevel: 4,
    guessability: "A〜B",
  },
  school: {
    label: "通学先（大学・キャンパス・学校）",
    category: "affiliation_and_work",
    personalLevel: 4,
    guessability: "B",
  },
  frequent_shop: {
    label: "行きつけの店（ジム・美容院・カフェ）",
    category: "activity_and_family",
    personalLevel: 4,
    guessability: "B",
  },
  vehicle_model_or_partial_plate: {
    label: "自家用車の車種・ナンバー（一部）",
    category: "activity_and_family",
    personalLevel: 4,
    guessability: "A〜B",
  },
  partner_status_and_attributes: {
    label: "配偶者・交際相手の有無と属性",
    category: "activity_and_family",
    personalLevel: 4,
    guessability: "B",
  },
  children_age_and_school: {
    label: "子どもの有無・年齢・通園通学先",
    category: "activity_and_family",
    personalLevel: 4,
    guessability: "B",
  },
} as const;

export type ProfileAttribute = keyof typeof PROFILE_ATTRIBUTE_CATALOG;
export type ProfileAttributeMetadata = (typeof PROFILE_ATTRIBUTE_CATALOG)[ProfileAttribute];
export type Guessability = ProfileAttributeMetadata["guessability"];
export type ProfileStatus = "found" | "weak" | "unknown";

export interface ProfileEvidence {
  readonly post_id: string;
  readonly clue_index: number;
  readonly required: boolean;
}

/** confidence は 0..1 の値。検出ロジック未実装のため、校正済み確率とは限らない。 */
interface ProfileItemBase {
  readonly attribute: ProfileAttribute;
  readonly confidence: number;
  readonly evidence: readonly ProfileEvidence[];
}

export type ProfileItem =
  | (ProfileItemBase & { readonly value: string; readonly status: "found" | "weak" })
  | (ProfileItemBase & { readonly value: null; readonly status: "unknown" });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isProfileEvidence(value: unknown): value is ProfileEvidence {
  return (
    isRecord(value) &&
    Object.keys(value).every((key) =>
      ["post_id", "clue_index", "required"].includes(key),
    ) &&
    typeof value.post_id === "string" &&
    value.post_id.length > 0 &&
    Number.isInteger(value.clue_index) &&
    (value.clue_index as number) >= 0 &&
    typeof value.required === "boolean"
  );
}

export function isProfileItem(value: unknown): value is ProfileItem {
  if (!isRecord(value)) return false;
  if (
    !Object.keys(value).every((key) =>
      ["attribute", "value", "confidence", "status", "evidence"].includes(key),
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
