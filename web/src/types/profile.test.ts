import { describe, expect, it } from "vitest";

import { PROFILE_ATTRIBUTE_CATALOG, PROFILE_CATEGORIES, isExternalProfileResult, isProfileItem, isWebFact, profileClaimAfterDeletion, type ProfileAttribute, type ProfileItem } from "./profile";

describe("profile metadata catalog", () => {
  it("contains the 25 candidate IDs and labels with unrated legacy fields", () => {
    const expected: Record<ProfileAttribute, string> = {
      facial_appearance: "顔貌（自撮り・他撮り・反射）", full_name: "本名（フルネーム）",
      given_name: "下の名前", nickname: "呼ばれている名前", other_social_account: "別SNSのアカウント / 本垢",
      realtime_location: "リアルタイムの現在地", home_building: "自宅の建物候補", home_room: "自宅の部屋・階・位置",
      home_nearest_station: "自宅の最寄り駅", regular_station: "日常的に利用する駅", regular_line: "日常的に利用する路線",
      residential_area: "居住エリア（市区町村・町域）", announced_long_absence: "予告された長期不在",
      actual_home_absence: "実際の自宅不在", employer_name: "雇用主名の推定",
      workplace_building_candidate: "勤務先建物候補", workplace_area: "勤務先エリア（オフィス街）",
      school: "通学先（大学・キャンパス・学校）", frequent_shop: "行きつけの店（ジム・美容院・カフェ）",
      vehicle_model: "自家用車の車種", partial_plate: "ナンバーの一部", partner_status: "配偶者・交際相手の有無",
      partner_attributes: "配偶者・交際相手の属性", child_age: "子どもの年齢", child_school: "子どもの通園・通学先",
    };
    expect(Object.keys(PROFILE_ATTRIBUTE_CATALOG).sort()).toEqual(Object.keys(expected).sort());
    expect(Object.fromEntries(Object.entries(PROFILE_ATTRIBUTE_CATALOG).map(([id, item]) => [id, item.label]))).toEqual(expected);
    expect(PROFILE_CATEGORIES).toHaveLength(4);
    for (const item of Object.values(PROFILE_ATTRIBUTE_CATALOG)) {
      expect(item.personalLevel).toBeNull();
      expect(item.guessability).toBeNull();
    }
  });
});

describe("profileClaimAfterDeletion", () => {
  const a = "at://did:plc:test/app.bsky.feed.post/a";
  const b = "at://did:plc:test/app.bsky.feed.post/b";
  const c = "at://did:plc:test/app.bsky.feed.post/c";
  const d = "at://did:plc:test/app.bsky.feed.post/d";
  const ref = (post_id: string, excerpt: string) => ({ post_id, clue_index: null, required: true, source: "post_text" as const, excerpt });
  const item: ProfileItem = {
    attribute: "residential_area", value: "架空の区", confidence: 0.8, status: "found",
    evidence: [ref(a, "A"), ref(b, "B"), ref(c, "C"), ref(d, "D")],
    evidence_paths: [
      { evidence: [ref(a, "A"), ref(b, "B")], confidence: 0.8 },
      { evidence: [ref(c, "C"), ref(d, "D")], confidence: 0.6 },
    ],
  };

  it("keeps only complete alternative paths that survive and uses their confidence", () => {
    const after = profileClaimAfterDeletion(item, new Set([a]));
    expect(after).not.toBeNull();
    expect(after?.evidence_paths).toEqual([item.evidence_paths?.[1]]);
    expect(after?.evidence).toEqual([ref(c, "C"), ref(d, "D")]);
    expect(after?.confidence).toBe(0.6);
    expect(after?.status).toBe("weak");
  });

  it("returns null when every known path is removed and undefined when paths are unavailable", () => {
    expect(profileClaimAfterDeletion(item, new Set([a, c]))).toBeNull();
    const legacy: ProfileItem = { ...item, evidence_paths: undefined };
    expect(profileClaimAfterDeletion(legacy, new Set([a]))).toBeUndefined();
  });
});

describe("isProfileItem", () => {
  const base = {
    attribute: "employer_name", confidence: 0.6,
    evidence: [{ post_id: "at://did:plc:test/app.bsky.feed.post/abc", clue_index: 1, required: true }],
  };
  it("accepts values and null unknowns", () => {
    expect(isProfileItem({ ...base, value: "会社名", status: "found" })).toBe(true);
    expect(isProfileItem({ ...base, value: null, status: "unknown" })).toBe(true);
  });
  it("accepts source-aware text evidence paths", () => {
    expect(isProfileItem({ ...base, value: "会社名", status: "weak", evidence_paths: [{ confidence: 0.65, evidence: [
      { post_id: "p1", clue_index: null, required: true, source: "post_text", image_index: null, excerpt: "うちの会社の研修" },
      { post_id: "p2", clue_index: null, required: true, source: "post_text", image_index: null, excerpt: "会社名の研修" },
    ] }] })).toBe(true);
  });
  it("accepts Web evidence only with a fact ID and no post reference", () => {
    const webEvidence = { post_id: null, clue_index: null, required: true, source: "public_web", web_fact_id: "official-1" };
    expect(isProfileItem({ ...base, value: "青空社", status: "weak", evidence: [webEvidence] })).toBe(true);
    expect(isProfileItem({ ...base, value: "青空社", status: "weak", evidence: [{ ...webEvidence, post_id: "post" }] })).toBe(false);
  });
  it.each([
    ["unknown with a value", { ...base, value: "会社名", status: "unknown" }],
    ["negative clue index", { ...base, value: "会社名", status: "found", evidence: [{ ...base.evidence[0], clue_index: -1 }] }],
    ["single-item evidence path", { ...base, value: "会社名", status: "found", evidence_paths: [{ evidence: [base.evidence[0]] }] }],
  ])("rejects %s", (_label, item) => expect(isProfileItem(item)).toBe(false));

  it("validates the optional four-axis assessment fields and conditional requirements", () => {
    const assessment = {
      minimal_scope: "bluesky",
      offline_subtype: null,
      psychological_resistance: 2,
      persona_context: "架空の利用者",
      inference_ease: 3,
      inference_ease_basis: "provisional",
      harm_severity: 2,
      harm_scenario: "架空の被害例",
      harm_prerequisites: ["追加条件"],
      harm_status: "applicable",
    };
    const withAssessment = (value: unknown) => ({
      ...base,
      value: "会社名",
      status: "found",
      assessment: value,
    });

    expect(isProfileItem(withAssessment(assessment))).toBe(true);
    expect(isProfileItem(withAssessment({
      ...assessment,
      harm_severity: null,
      harm_scenario: null,
      harm_prerequisites: [],
      harm_status: "unknown",
      psychological_resistance: null,
      persona_context: null,
      inference_ease: null,
      inference_ease_basis: null,
    }))).toBe(true);
    expect(isProfileItem(withAssessment({
      ...assessment,
      minimal_scope: "bluesky_plus_offline",
      offline_subtype: "public_registry",
      harm_severity: null,
      harm_status: "prerequisites_unmet",
    }))).toBe(true);

    const invalidAssessments = [
      { ...assessment, minimal_scope: "other" },
      { ...assessment, psychological_resistance: 6 },
      { ...assessment, persona_context: null },
      { ...assessment, inference_ease_basis: "estimated" },
      { ...assessment, inference_ease: null },
      { ...assessment, harm_prerequisites: [1] },
      { ...assessment, harm_status: "unknown", harm_severity: 1 },
      { ...assessment, harm_status: "prerequisites_unmet", harm_severity: 2 },
      { ...assessment, harm_status: "prerequisites_unmet", harm_prerequisites: [] },
      { ...assessment, minimal_scope: "bluesky_plus_offline", offline_subtype: null },
      { ...assessment, minimal_scope: "bluesky_plus_public_web", offline_subtype: "registry" },
    ];
    for (const invalid of invalidAssessments) {
      expect(isProfileItem(withAssessment(invalid))).toBe(false);
    }
  });
});

describe("isWebFact", () => {
  const fact = {
    id: "official-1", subject: "青空社", relation: "legal_name_of", object: "株式会社青空",
    source_url: "https://example.org/company/training", source_title: "架空の公式会社案内",
    source_kind: "official_organization", excerpt: "青空社の正式名称は株式会社青空です",
    retrieved_at: "2026-11-10T10:00:00+09:00", verification_status: "verified",
  };
  it("accepts a sourced verified fact", () => expect(isWebFact(fact)).toBe(true));
  it("rejects URL credentials and invalid status", () => {
    expect(isWebFact({ ...fact, source_url: "https://user:pass@example.org/a" })).toBe(false);
    expect(isWebFact({ ...fact, verification_status: "guessed" })).toBe(false);
  });
});

describe("isExternalProfileResult", () => {
  const candidate = {
    id: "candidate-1",
    url: "https://example.net/blog",
    domain: "example.net",
    title: "架空のブログ",
    status: "candidate",
    owner_evidence: null,
  };

  it("accepts public HTTPS candidates and owner-linked profile or post URLs", () => {
    expect(isExternalProfileResult(candidate)).toBe(true);
    expect(isExternalProfileResult({
      ...candidate,
      status: "owner_linked",
      owner_evidence: { kind: "profile_text", post_id: null, excerpt: "ブログ https://example.net/blog" },
    })).toBe(true);
    expect(isExternalProfileResult({
      ...candidate,
      status: "owner_linked",
      owner_evidence: { kind: "post_text", post_id: "at://did:plc:test/app.bsky.feed.post/a", excerpt: "私の記事 https://example.net/blog" },
    })).toBe(true);
  });

  it.each([
    ["unknown fields", { extra: true }],
    ["empty title", { title: "" }],
    ["non-HTTPS URL", { url: "http://example.net/blog" }],
    ["URL credentials", { url: "https://user:pass@example.net/blog" }],
    ["explicit port", { url: "https://example.net:8443/blog" }],
    ["domain mismatch", { domain: "elsewhere.net" }],
    ["single-label host", { url: "https://intranet/blog", domain: "intranet" }],
    ["IPv4 address", { url: "https://192.0.2.1/blog", domain: "192.0.2.1" }],
    ["localhost host", { url: "https://localhost/blog", domain: "localhost" }],
    ["internal suffix", { url: "https://service.internal/blog", domain: "service.internal" }],
    ["malformed host label", { url: "https://-invalid.example/blog", domain: "-invalid.example" }],
    ["bad status", { status: "verified" }],
    ["candidate with owner evidence", { owner_evidence: { kind: "profile_text", post_id: null, excerpt: "link" } }],
    ["owner-linked without evidence", { status: "owner_linked" }],
    ["empty excerpt", { status: "owner_linked", owner_evidence: { kind: "profile_text", post_id: null, excerpt: "" } }],
    ["profile evidence with a post ID", { status: "owner_linked", owner_evidence: { kind: "profile_text", post_id: "post", excerpt: "link" } }],
    ["post evidence without a post ID", { status: "owner_linked", owner_evidence: { kind: "post_text", post_id: null, excerpt: "link" } }],
    ["unknown evidence kind", { status: "owner_linked", owner_evidence: { kind: "search_result", post_id: null, excerpt: "link" } }],
  ])("rejects %s", (_name, change) => {
    expect(isExternalProfileResult({ ...candidate, ...change })).toBe(false);
  });
});
