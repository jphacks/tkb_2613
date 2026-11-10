import { describe, expect, it } from "vitest";

import { PROFILE_ATTRIBUTE_CATALOG, PROFILE_CATEGORIES, isProfileItem, isWebFact, type ProfileAttribute } from "./profile";

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
