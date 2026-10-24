import { describe, expect, it } from "vitest";

import {
  PROFILE_ATTRIBUTE_CATALOG,
  PROFILE_CATEGORIES,
  PROFILE_CATEGORY_LABELS,
  isProfileItem,
  type ProfileAttribute,
} from "./profile";

describe("profile metadata catalog", () => {
  it("contains the 16 stable IDs and their Japanese display labels", () => {
    const expected: Record<ProfileAttribute, string> = {
      facial_appearance: "顔貌（自撮り・他撮り・反射）",
      full_name: "本名（フルネーム）",
      given_name_or_nickname: "下の名前 / 呼ばれている名前",
      other_social_account: "別SNSのアカウント / 本垢",
      realtime_location: "リアルタイムの現在地",
      home_building_or_room: "自宅の建物外観・部屋の位置",
      commute_station_or_line: "最寄り駅 / 日常の利用路線",
      residential_area: "居住エリア（市区町村・町域）",
      long_term_home_absence: "自宅の長期不在（旅行・帰省中）",
      workplace: "勤務先（企業名・店舗・ビル）",
      workplace_area: "勤務先エリア（オフィス街）",
      school: "通学先（大学・キャンパス・学校）",
      frequent_shop: "行きつけの店（ジム・美容院・カフェ）",
      vehicle_model_or_partial_plate: "自家用車の車種・ナンバー（一部）",
      partner_status_and_attributes: "配偶者・交際相手の有無と属性",
      children_age_and_school: "子どもの有無・年齢・通園通学先",
    };

    expect(Object.keys(PROFILE_ATTRIBUTE_CATALOG).sort()).toEqual(Object.keys(expected).sort());
    expect(
      Object.fromEntries(
        Object.entries(PROFILE_ATTRIBUTE_CATALOG).map(([id, metadata]) => [id, metadata.label]),
      ),
    ).toEqual(expected);
  });

  it("provides category, personal level, and guessability for every ID", () => {
    expect(PROFILE_CATEGORIES).toEqual([
      "identity_and_face",
      "home_and_location",
      "affiliation_and_work",
      "activity_and_family",
    ]);
    expect(PROFILE_CATEGORY_LABELS).toEqual({
      identity_and_face: "身元・顔",
      home_and_location: "自宅・位置",
      affiliation_and_work: "所属・職場",
      activity_and_family: "行動圏・家族",
    });
    for (const metadata of Object.values(PROFILE_ATTRIBUTE_CATALOG)) {
      expect(PROFILE_CATEGORIES).toContain(metadata.category);
      expect([4, 5]).toContain(metadata.personalLevel);
      expect(["A", "A〜B", "B"]).toContain(metadata.guessability);
    }
    expect(
      Object.fromEntries(
        Object.entries(PROFILE_ATTRIBUTE_CATALOG).map(([id, metadata]) => [
          id,
          [metadata.category, metadata.personalLevel, metadata.guessability],
        ]),
      ),
    ).toEqual({
      facial_appearance: ["identity_and_face", 5, "A"],
      full_name: ["identity_and_face", 5, "B"],
      given_name_or_nickname: ["identity_and_face", 4, "A〜B"],
      other_social_account: ["identity_and_face", 4, "A"],
      realtime_location: ["home_and_location", 5, "A"],
      home_building_or_room: ["home_and_location", 5, "B"],
      commute_station_or_line: ["home_and_location", 4, "A〜B"],
      residential_area: ["home_and_location", 4, "B"],
      long_term_home_absence: ["home_and_location", 4, "A〜B"],
      workplace: ["affiliation_and_work", 4, "B"],
      workplace_area: ["affiliation_and_work", 4, "A〜B"],
      school: ["affiliation_and_work", 4, "B"],
      frequent_shop: ["activity_and_family", 4, "B"],
      vehicle_model_or_partial_plate: ["activity_and_family", 4, "A〜B"],
      partner_status_and_attributes: ["activity_and_family", 4, "B"],
      children_age_and_school: ["activity_and_family", 4, "B"],
    });
  });
});

describe("isProfileItem", () => {
  const base = {
    attribute: "workplace",
    confidence: 0.6,
    evidence: [{ post_id: "at://did:plc:test/app.bsky.feed.post/abc", clue_index: 1, required: true }],
  };

  it("accepts found and weak values plus an unknown null value", () => {
    expect(isProfileItem({ ...base, value: "会社名", status: "found" })).toBe(true);
    expect(isProfileItem({ ...base, value: "会社らしい", status: "weak" })).toBe(true);
    expect(isProfileItem({ ...base, value: null, status: "unknown" })).toBe(true);
  });

  it.each([
    ["found with null", { ...base, value: null, status: "found" }],
    ["unknown with a value", { ...base, value: "会社名", status: "unknown" }],
    ["empty found value", { ...base, value: "  ", status: "found" }],
    ["not-a-number confidence", { ...base, value: "会社名", status: "found", confidence: NaN }],
    ["invalid ID", { ...base, attribute: "unknown", value: "x", status: "found" }],
    ["negative clue index", {
      ...base,
      value: "会社名",
      status: "found",
      evidence: [{ ...base.evidence[0], clue_index: -1 }],
    }],
  ])("rejects %s", (_label, item) => {
    expect(isProfileItem(item)).toBe(false);
  });
});
