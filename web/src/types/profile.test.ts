import { describe, expect, it } from "vitest";

import { PROFILE_ATTRIBUTE_CATALOG, PROFILE_CATEGORIES, PROFILE_DIAGNOSED_ATTRIBUTES, isExternalProfileResult, isProfileCandidateSet, isProfileCandidateSetList, isProfileItem, isWebFact, profileCandidateAfterDeletion, profileClaimAfterDeletion, type ClaimAssessment, type ProfileAttribute, type ProfileCandidate, type ProfileCandidateSet, type ProfileEvidence, type ProfileItem } from "./profile";

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
      { evidence: [ref(a, "A"), ref(b, "B")], confidence: 0.8, provenance: "combined_inference" },
      { evidence: [ref(c, "C"), ref(d, "D")], confidence: 0.6, provenance: "combined_inference" },
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

  it("keeps a found grade when a direct-disclosure path survives below the old score threshold", () => {
    const withProvenance: ProfileItem = {
      ...item,
      confidence: 0.86,
      evidence_paths: [
        { evidence: [ref(a, "直接公開 A"), ref(b, "直接公開 B")], confidence: 0.72, provenance: "direct_disclosure" },
        { evidence: [ref(c, "複合 C"), ref(d, "複合 D")], confidence: 0.86, provenance: "combined_inference" },
      ],
    };

    const after = profileClaimAfterDeletion(withProvenance, new Set([c]));

    expect(after?.confidence).toBe(0.72);
    expect(after?.status).toBe("found");
    expect(after?.evidence_paths?.map((path) => path.provenance)).toEqual(["direct_disclosure"]);
  });

  it("downgrades a found claim when deletion leaves only combined-inference paths", () => {
    const withProvenance: ProfileItem = {
      ...item,
      confidence: 0.86,
      evidence_paths: [
        { evidence: [ref(a, "直接公開 A"), ref(b, "直接公開 B")], confidence: 0.72, provenance: "direct_disclosure" },
        { evidence: [ref(c, "複合 C"), ref(d, "複合 D")], confidence: 0.86, provenance: "combined_inference" },
      ],
    };

    const after = profileClaimAfterDeletion(withProvenance, new Set([a]));

    expect(after?.confidence).toBe(0.86);
    expect(after?.status).toBe("weak");
    expect(after?.evidence_paths?.map((path) => path.provenance)).toEqual(["combined_inference"]);
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
    expect(isProfileItem({ ...base, value: "会社名", status: "weak", evidence_paths: [{ provenance: "combined_inference", confidence: 0.65, evidence: [
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
    ["path without provenance", { ...base, value: "会社名", status: "found", evidence_paths: [{ evidence: base.evidence, confidence: 0.65 }] }],
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

describe("profile candidate sets", () => {
  const evidence: ProfileEvidence[] = [
    { post_id: "at://did:plc:test/app.bsky.feed.post/a", clue_index: null, required: true, source: "post_text", image_index: null, excerpt: "投稿 A" },
    { post_id: "at://did:plc:test/app.bsky.feed.post/b", clue_index: null, required: true, source: "post_text", image_index: null, excerpt: "投稿 B" },
  ];
  const assessment: ClaimAssessment = {
    minimal_scope: "bluesky", offline_subtype: null, psychological_resistance: null, persona_context: null,
    inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
    harm_prerequisites: [], harm_status: "unknown",
  };
  const candidate = (value: string, confidence = 0.65, status: "found" | "weak" = "weak", observed_at?: string | null, rank = 1): ProfileCandidate => ({
    rank, value, confidence, status, evidence, evidence_paths: [{ evidence, confidence, provenance: "combined_inference" }], assessment,
    observed_at: observed_at ?? null, counter_evidence: [],
  });
  const set = (attribute: ProfileAttribute, pool: readonly ProfileCandidate[], status?: "candidate" | "ambiguous"): ProfileCandidateSet => {
    const strongest = pool[0];
    const visible = strongest?.status === "weak"
      ? pool.filter((entry) => entry.status === "weak").slice(0, 3)
      : pool.filter((entry) => entry.status === "found" && strongest.confidence - entry.confidence <= 0.15).slice(0, 3);
    return {
      attribute,
      status: status ?? (visible.length > 1 ? "ambiguous" : "candidate"),
      candidates: visible,
      candidate_pool: pool,
      reason: null,
      conflicting_evidence: [],
    };
  };
  const rawSet = (pool: readonly ProfileCandidate[], candidates: readonly ProfileCandidate[] = pool): ProfileCandidateSet => ({
    attribute: "residential_area", status: "ambiguous", candidates, candidate_pool: pool,
    reason: null, conflicting_evidence: [],
  });

  it("accepts one candidate and multiple weak candidates despite a wider score gap", () => {
    expect(isProfileCandidateSet(set("residential_area", [candidate("架空の区")]))).toBe(true);
    expect(isProfileCandidateSet(set("residential_area", [candidate("架空の区A", 0.90, "weak", null, 1), candidate("架空の区B", 0.60, "weak", null, 2)]))).toBe(true);
  });

  it("rejects a strong displayed set outside the 0.15 margin or mixed grades", () => {
    expect(isProfileCandidateSet(rawSet([
      candidate("A", 0.80, "found", null, 1), candidate("B", 0.64, "found", null, 2),
    ]))).toBe(false);
    expect(isProfileCandidateSet(rawSet([
      candidate("A", 0.65, "found", null, 1), candidate("B", 0.65, "weak", null, 2),
    ]))).toBe(false);
  });

  it("rejects duplicate normalized pool values and more than three displayed candidates", () => {
    expect(isProfileCandidateSet(rawSet([
      candidate("Ａ", 0.65, "weak", null, 1), candidate("a", 0.65, "weak", null, 2),
    ]))).toBe(false);
    const four = [
      candidate("A", 0.65, "weak", null, 1), candidate("B", 0.65, "weak", null, 2),
      candidate("C", 0.65, "weak", null, 3), candidate("D", 0.65, "weak", null, 4),
    ];
    expect(isProfileCandidateSet(rawSet(four))).toBe(false);
  });

  it("uses the shared NFKC, trim, lowercase candidate normalization", () => {
    const candidates = [candidate("STRASSE", 0.65, "weak", null, 1), candidate("Straße", 0.65, "weak", null, 2)];
    expect(isProfileCandidateSet(set("residential_area", candidates))).toBe(true);
  });

  it("requires an explanation for an empty candidate set", () => {
    expect(isProfileCandidateSet({ attribute: "residential_area", status: "unknown", candidates: [], candidate_pool: [], reason: null, conflicting_evidence: [] })).toBe(false);
  });

  it("requires a timezone-aware observation timestamp only for real-time location candidates", () => {
    expect(isProfileCandidateSet(set("realtime_location", [candidate("駅前", 0.65, "weak", "2026-11-12T10:00:00+09:00")]))).toBe(true);
    expect(isProfileCandidateSet(set("realtime_location", [candidate("駅前")]))).toBe(false);
    expect(isProfileCandidateSet(set("realtime_location", [candidate("駅前", 0.65, "weak", "2026-11-12T10:00:00")]))).toBe(false);
    expect(isProfileCandidateSet(set("school", [candidate("架空大学", 0.65, "weak", "2026-11-12T10:00:00+09:00")]))).toBe(false);
  });

  it("requires a complete 24-attribute diagnosis set, excluding home_room", () => {
    const sets: ProfileCandidateSet[] = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => ({
      attribute, status: "unknown", candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [],
    }));
    expect(sets).toHaveLength(24);
    expect(isProfileCandidateSetList(sets)).toBe(true);
    expect(isProfileCandidateSetList([...sets, { attribute: "home_room", status: "unknown", candidates: [], candidate_pool: [], reason: "excluded", conflicting_evidence: [] }])).toBe(false);
  });

  it("reduces an ambiguous set to the one surviving grounded candidate after hypothetical deletion", () => {
    const evidenceC: ProfileEvidence[] = [
      { post_id: "at://did:plc:test/app.bsky.feed.post/c", clue_index: null, required: true, source: "post_text", image_index: null, excerpt: "投稿 C" },
      { post_id: "at://did:plc:test/app.bsky.feed.post/d", clue_index: null, required: true, source: "post_text", image_index: null, excerpt: "投稿 D" },
    ];
    const candidates = [
      candidate("区A", 0.65, "weak", null, 1),
      { ...candidate("区B", 0.60, "weak", null, 2), evidence: evidenceC, evidence_paths: [{ evidence: evidenceC, confidence: 0.60, provenance: "combined_inference" as const }] },
    ];
    const candidateSet = set("residential_area", candidates);
    const after = profileCandidateAfterDeletion(candidateSet, new Set(["at://did:plc:test/app.bsky.feed.post/a"]));
    expect(after.status).toBe("candidate");
    expect(after.candidates).toHaveLength(1);
    expect(after.candidates[0].value).toBe("区B");
  });

  it("removes a denial from an unknown set when its post is hypothetically excluded", () => {
    const denial: ProfileEvidence = {
      post_id: "at://did:plc:test/app.bsky.feed.post/a", clue_index: null, required: true,
      source: "post_text", excerpt: "ここは自宅ではありません",
    };
    const set: ProfileCandidateSet = {
      attribute: "residential_area", status: "unknown", candidates: [], candidate_pool: [],
      reason: "explicit_negation", conflicting_evidence: [denial],
    };
    const after = profileCandidateAfterDeletion(set, new Set([denial.post_id!]));
    expect(after.status).toBe("unknown");
    expect(after.reason).toBe("no_grounded_rule");
    expect(after.conflicting_evidence).toEqual([]);
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
