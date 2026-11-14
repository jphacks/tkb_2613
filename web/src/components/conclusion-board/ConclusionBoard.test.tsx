import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import { PROFILE_CATEGORIES, PROFILE_CATEGORY_LABELS, PROFILE_DIAGNOSED_ATTRIBUTES, type ProfileCandidateSet } from "@/types/profile";

import { ConclusionBoard } from "./ConclusionBoard";

const CLUE: Clue = {
  post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
  image_index: null,
  type: "place_text",
  value: "新宿",
  region: null,
  confidence: 0.8,
  source: "text",
};

const CONCLUSION: Conclusion = {
  rule: "station_from_place",
  attribute: "station",
  value: "新宿",
  clue_indices: [0],
  note: "",
};

/** jsdom には ResizeObserver がないので、observe した瞬間に 1 回知らせる代わりを置く */
class ImmediateResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe() {
    this.callback([], this as unknown as ResizeObserver);
  }
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ImmediateResizeObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ConclusionBoard", () => {
  it("shows per-image place candidates with clue/source and never turns them into location claims", () => {
    const photoClue: Clue = {
      ...CLUE, post_id: "post-photo", image_index: 0, type: "shop", value: "公園", source: "ocr", region: [1, 2, 30, 40],
    };
    render(<ConclusionBoard
      clues={[photoClue]}
      conclusions={[]}
      posts={[{ post_id: "post-photo", text: "", created_at: "2026-11-01T00:00:00Z", images: [{ index: 0, url: "https://cdn.bsky.app/img/feed_fullsize/demo", alt: "入口の看板", width: 20, height: 20 }] }]}
      photoPlaceResults={[{
        post_id: "post-photo", image_index: 0, status: "candidate", granularity: "facility", reason_codes: [], lookup_status: "local_only",
        candidates: [{
          place_id: "places:poi-1", label: "公園", place_type: "facility", photo_relation: "visible_in_frame",
          area_label: null, score: 0.92, source_ids: ["provider:poi-1"],
          evidence: [{ kind: "clue", clue_index: 0, reference_id: null }],
          sources: [{ source_id: "provider:poi-1", provider: "Provider", dataset: "places", license_id: "CC-BY-4.0", record_id: "poi-1", version: "v1", attribution: "Provider attribution" }],
        }],
      }, {
        post_id: "post-photo", image_index: 1, status: "unknown", granularity: "unknown", candidates: [], reason_codes: ["insufficient_local_evidence"], lookup_status: "local_only",
      }]}
    />);

    expect(screen.getByText(/写真ごとの場所候補/)).toBeInTheDocument();
    expect(screen.getAllByText(/写真内に見える/)).toHaveLength(2);
    expect(screen.getByText(/撮影地点・家の場所・居住地を示しません/)).toBeInTheDocument();
    expect(screen.getByText(/Provider \/ places · license CC-BY-4.0/)).toBeInTheDocument();
    expect(screen.getByText(/手がかり 0: 公園 \(ocr\)/)).toBeInTheDocument();
    expect(screen.getByText(/写真 2 枚目 · 不明/)).toBeInTheDocument();
    expect(screen.queryByText(/92%/)).not.toBeInTheDocument();
  });

  it("shows an official-record corroboration on a Brave candidate without upgrading its status", () => {
    const photoClue: Clue = {
      ...CLUE, post_id: "post-photo", image_index: 0, type: "shop", value: "市民会館", source: "ocr", region: [1, 2, 30, 40],
    };
    const candidate = (place_id: string, area_label: string, extra: object = {}) => ({
      place_id, label: "市民会館", place_type: "facility" as const, photo_relation: "visible_in_frame" as const,
      area_label, score: null, source_ids: [`source:${place_id}`],
      evidence: [{ kind: "clue" as const, clue_index: 0, reference_id: null }], sources: [], ...extra,
    });
    render(<ConclusionBoard
      clues={[photoClue]}
      conclusions={[]}
      photoPlaceResults={[{
        post_id: "post-photo", image_index: 0, status: "ambiguous", granularity: "facility", reason_codes: ["multiple_matches"], lookup_status: "web_searched",
        candidates: [
          candidate("p05:tokyo", "府中市"),
          candidate("p05:hiroshima", "府中市"),
          candidate("brave:1", "東京都 府中市", { corroborated_by: ["p05:tokyo"] }),
        ],
      }]}
    />);

    expect(screen.getAllByText(/名称・都道府県・市区町村が一致しました/)).toHaveLength(1);
    expect(screen.getByText(/同じ施設かどうかと、写真の撮影位置は確認していません/)).toBeInTheDocument();
    expect(screen.getByText(/複数候補（曖昧）/)).toBeInTheDocument();
  });

  it("pins each clue used as evidence once and ties a red string to every conclusion it supports", () => {
    const clues: Clue[] = [CLUE, { ...CLUE, type: "routine_text", value: "毎朝 8 時の電車" }];
    const conclusions: Conclusion[] = [
      { ...CONCLUSION, clue_indices: [0, 1] },
      { ...CONCLUSION, attribute: "active_time", value: "平日の朝", clue_indices: [1] },
    ];
    const { container } = render(<ConclusionBoard clues={clues} conclusions={conclusions} />);

    const evidence = within(screen.getByRole("list", { name: messages.board.evidence })).getAllByRole(
      "listitem",
    );
    expect(evidence.map((e) => e.textContent)).toEqual([
      `${messages.clues.typeLabels.place_text}新宿`,
      `${messages.clues.typeLabels.routine_text}毎朝 8 時の電車`,
    ]);
    const strings = container.querySelector("svg.red-strings");
    expect(strings).toHaveAttribute("aria-hidden", "true");
    expect(strings?.querySelectorAll("path")).toHaveLength(3);
  });

  it("announces みーつけた and flashes once when something is inferred", () => {
    const { container } = render(<ConclusionBoard clues={[CLUE]} conclusions={[CONCLUSION]} />);

    expect(screen.getByText(messages.board.found)).toBeInTheDocument();
    expect(container.querySelector(".found-flash")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText(messages.board.attributeLabels.station)).toBeInTheDocument();
  });

  it("stays calm when nothing is inferred", () => {
    const { container } = render(<ConclusionBoard clues={[]} conclusions={[]} />);

    expect(screen.queryByText(messages.board.found)).not.toBeInTheDocument();
    expect(container.querySelector(".found-flash")).not.toBeInTheDocument();
    expect(screen.getByText(messages.board.empty)).toBeInTheDocument();
  });

  it("shows broken items as unknown after a simulated deletion, without the evidence", () => {
    render(<ConclusionBoard clues={[CLUE]} conclusions={[]} unknown={["station"]} />);

    const cards = within(screen.getByRole("list", { name: messages.board.conclusionsLabel })).getAllByRole("listitem");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveTextContent(messages.board.attributeLabels.station);
    expect(cards[0]).toHaveTextContent(messages.board.unknown);
    expect(screen.queryByText(CLUE.value)).not.toBeInTheDocument();
    expect(screen.queryByText(messages.board.empty)).not.toBeInTheDocument();
  });

  it("does not show legacy R8 name breakage among simulated unknown items", () => {
    render(<ConclusionBoard clues={[]} conclusions={[]} unknown={["full_name", "station"]} />);

    expect(screen.getByText(messages.board.attributeLabels.station)).toBeInTheDocument();
    expect(screen.queryByText(messages.board.attributeLabels.full_name)).not.toBeInTheDocument();
  });

  it("labels stale location as post-time information and exposes candidate counter-evidence", async () => {
    const oldEvidence = { post_id: CLUE.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: "投稿時点の駅前" };
    const counterEvidence = { ...oldEvidence, excerpt: "これは別の日の投稿だと書いてある" };
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const candidate = {
      rank: 1, value: "架空駅前", confidence: 0.65, status: "weak" as const,
      evidence: [oldEvidence], evidence_paths: [{ evidence: [oldEvidence, { ...oldEvidence, post_id: "at://did:plc:test/app.bsky.feed.post/other" }], confidence: 0.65, provenance: "combined_inference" as const }],
      assessment, observed_at: new Date(Date.now() - 16 * 60_000).toISOString(), counter_evidence: [counterEvidence],
    };
    const locationSet: ProfileCandidateSet = {
      attribute: "realtime_location", status: "candidate", candidates: [candidate], candidate_pool: [candidate],
      reason: null, conflicting_evidence: [],
    };
    render(<ConclusionBoard clues={[]} conclusions={[]} profileClaims={[locationSet]} />);

    expect(screen.getByText("投稿時点の位置候補 ・候補（正解とは限りません）")).toBeInTheDocument();
    expect(screen.getByText(/投稿時点：/)).toBeInTheDocument();
    expect(await screen.findByText(/15分経過。最新情報ではありません/)).toBeInTheDocument();
    expect(screen.queryByText("リアルタイムの現在地")).not.toBeInTheDocument();
    expect(screen.getByText("架空駅前")).toBeInTheDocument();

    fireEvent.click(screen.getByText("根拠と反対の根拠を確認"));
    expect(screen.getByText(/これは別の日の投稿だと書いてある/)).toBeInTheDocument();
  });

  it("renders all catalog attributes in unified mode, keeping direct and combined provenance", () => {
    const firstPost = { post_id: CLUE.post_id, clue_index: 0, required: true, source: "post_text" as const, excerpt: "私の勤務先は青空社です" };
    const secondPost = { ...firstPost, clue_index: null, post_id: "at://did:plc:test/app.bsky.feed.post/second", excerpt: "青空社の正式社名は株式会社青空" };
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const candidate = {
      rank: 1, value: "株式会社青空", confidence: 0.7, status: "weak" as const,
      evidence: [firstPost, secondPost],
      evidence_paths: [
        { evidence: [firstPost, secondPost], confidence: 0.7, provenance: "direct_disclosure" as const },
        { evidence: [firstPost, secondPost], confidence: 0.68, provenance: "combined_inference" as const },
      ], assessment, observed_at: null, counter_evidence: [],
    };
    const allSets: ProfileCandidateSet[] = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => (
      attribute === "employer_name"
        ? { attribute, status: "candidate", candidates: [candidate], candidate_pool: [candidate], reason: null, conflicting_evidence: [] }
        : { attribute, status: "unknown", candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [] }
    ));
    const { container } = render(<ConclusionBoard clues={[CLUE]} conclusions={[]} profileClaims={allSets} />);

    for (const category of PROFILE_CATEGORIES) {
      expect(screen.getByRole("heading", { name: PROFILE_CATEGORY_LABELS[category] })).toBeInTheDocument();
    }
    expect(screen.getAllByText("自分で直接公開")).toHaveLength(2);
    expect(screen.getAllByText("投稿の組み合わせから推定")).toHaveLength(2);
    expect(screen.getAllByText("株式会社青空")).toHaveLength(1);
    expect(screen.getByText("通学先（大学・キャンパス・学校）")).toBeInTheDocument();
    expect(screen.getAllByText(messages.board.unknown)).toHaveLength(28);
    expect(screen.queryByRole("heading", { name: "プロフィール候補" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: messages.board.evidence })).getAllByRole("listitem")).toHaveLength(1);
    expect(container.querySelectorAll("svg.red-strings path")).toHaveLength(1);
  });

  it("marks broken attributes as unknown in unified mode", () => {
    const allSets: ProfileCandidateSet[] = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => (
      { attribute, status: "unknown", candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [] }
    ));
    render(<ConclusionBoard clues={[CLUE]} conclusions={[]} profileClaims={allSets} unknown={["employer_name"]} />);

    expect(screen.getByText(messages.board.found)).toBeInTheDocument();
    expect(screen.getByText(messages.board.unknownNote)).toBeInTheDocument();
    expect(screen.getAllByText(messages.board.unknown)).toHaveLength(PROFILE_DIAGNOSED_ATTRIBUTES.length);
  });

  it("shows profileClaimsError banner when profile_claims could not be read", () => {
    render(<ConclusionBoard clues={[]} conclusions={[]} profileClaims={[]} profileClaimsError />);

    expect(screen.getByRole("alert")).toHaveTextContent(messages.board.profileClaimsError);
    expect(screen.queryByText(messages.board.empty)).not.toBeInTheDocument();
  });

  it("shows names only in provenance-labelled profile candidate cards, not legacy R8 conclusions", () => {
    const evidence = {
      post_id: CLUE.post_id, clue_index: 0, required: true, source: "post_text" as const, excerpt: "内藤大貴",
    };
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const candidate = {
      rank: 1, value: "内藤大貴", confidence: 0.86, status: "found" as const,
      evidence: [evidence],
      evidence_paths: [{ evidence: [evidence], confidence: 0.86, provenance: "direct_disclosure" as const }],
      assessment, observed_at: null, counter_evidence: [],
    };
    const nameSet: ProfileCandidateSet = {
      attribute: "full_name", status: "candidate", candidates: [candidate], candidate_pool: [candidate],
      reason: null, conflicting_evidence: [],
    };
    render(<ConclusionBoard
      clues={[{ ...CLUE, type: "name_text", value: "内藤大貴" }]}
      conclusions={[{ rule: "R8", attribute: "full_name", value: "内藤大貴", clue_indices: [0], note: "宛名・名札などの姓と名" }]}
      profileClaims={[nameSet]}
    />);

    expect(screen.getAllByText("内藤大貴")).toHaveLength(1);
    expect(screen.getAllByText("自分で直接公開")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "プロフィール候補" })).toBeInTheDocument();
    expect(screen.queryByText("宛名・名札などの姓と名")).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: messages.board.conclusionsLabel })).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("draws red strings inside a candidate when its evidence paths start from different posts", () => {
    const busPost = { post_id: CLUE.post_id, text: "家の前のバス停から毎朝バスに乗る。", created_at: "2026-10-20T08:31:00+09:00", images: [] };
    const shelterPost = { post_id: "at://did:plc:test/app.bsky.feed.post/shelter", text: "近所の小学校が避難所になっている。", created_at: "2026-10-21T08:31:00+09:00", images: [] };
    const fromPost = (post_id: string) => ({ post_id, clue_index: null, required: true, source: "post_text" as const });
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const candidate = {
      rank: 1, value: "文京区", confidence: 0.65, status: "weak" as const,
      evidence: [fromPost(busPost.post_id), fromPost(shelterPost.post_id)],
      evidence_paths: [
        { evidence: [fromPost(busPost.post_id)], confidence: 0.6, provenance: "combined_inference" as const },
        { evidence: [fromPost(shelterPost.post_id)], confidence: 0.6, provenance: "combined_inference" as const },
      ], assessment, observed_at: null, counter_evidence: [],
    };
    const areaSet: ProfileCandidateSet = {
      attribute: "residential_area", status: "candidate", candidates: [candidate], candidate_pool: [candidate], reason: null, conflicting_evidence: [],
    };
    render(<ConclusionBoard clues={[]} conclusions={[]} profileClaims={[areaSet]} posts={[busPost, shelterPost]} />);

    const candidates = screen.getByRole("list", { name: /の候補$/ });
    expect(within(candidates).getByRole("figure", { name: "別々の 2 つの道筋が、同じ答え「文京区」を指す" })).toBeInTheDocument();
  });
});
