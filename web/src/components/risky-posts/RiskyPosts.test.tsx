import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, deletePosts, simulate } from "@/lib/api";
import { ESCAPED_MESSAGE } from "@/components/escape-stamps/EscapeStamps";
import { attributeLabel, messages } from "@/lib/messages";
import type { Clue } from "@/types/clue";
import type { RiskyPost, Simulation } from "@/types/diagnose";
import type { Post } from "@/types/post";
import { PROFILE_DIAGNOSED_ATTRIBUTES, type ProfileAttribute, type ProfileCandidateSet } from "@/types/profile";

import { RiskyPosts, inviteComposeUrl } from "./RiskyPosts";

const t = messages.risky;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, simulate: vi.fn(), deletePosts: vi.fn() };
});

function post(n: number, text: string): Post {
  return {
    post_id: `at://did:plc:abc/app.bsky.feed.post/3k${n}`,
    text,
    created_at: "2026-10-20T08:31:00+09:00",
    images: [],
  };
}

const ADDRESS = post(9, "荷物届いた");
const GYM = post(2, "ジムおわり 毎週火曜はここ");
const RISKY: RiskyPost[] = [
  { post_id: ADDRESS.post_id, broken: ["regular_station", "employer_name"] },
  { post_id: GYM.post_id, broken: ["routine"] },
];
const ALL_BROKEN: Simulation = {
  delete: [ADDRESS.post_id, GYM.post_id],
  broken: ["regular_station", "employer_name", "routine"],
  after: [],
};

function onlyCandidateSet(candidate: ProfileCandidateSet): ProfileCandidateSet[] {
  return PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => attribute === candidate.attribute
    ? candidate
    : { attribute, status: "unknown", candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [] });
}

function renderRisky(onSimulated = vi.fn()) {
  render(<RiskyPosts posts={[GYM, ADDRESS]} risky={RISKY} clueCount={20} onSimulated={onSimulated} />);
  return onSimulated;
}

afterEach(() => {
  vi.mocked(simulate).mockReset();
  vi.mocked(deletePosts).mockReset();
});

describe("RiskyPosts", () => {
  it("lists the risky posts in plan order with what each one breaks, all selected", () => {
    renderRisky();

    const items = within(screen.getByRole("list", { name: t.listLabel })).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent(ADDRESS.text);
    expect(items[0]).toHaveTextContent(t.breaks(`${attributeLabel("regular_station")}・${attributeLabel("employer_name")}`));
    expect(items[1]).toHaveTextContent(t.breaks(attributeLabel("routine")));
    expect(screen.getAllByRole("checkbox").map((c) => (c as HTMLInputElement).checked)).toEqual([true, true]);
  });

  it("explains why a face photo is recommended even when it breaks no conclusion by itself", () => {
    const face: Clue = {
      post_id: ADDRESS.post_id, image_index: 0, type: "face", value: "1人",
      region: [0, 0, 10, 10], confidence: 0.9, source: "vlm",
    };
    render(<RiskyPosts posts={[ADDRESS]} risky={[{ post_id: ADDRESS.post_id, broken: [] }]} clues={[face]} clueCount={1} onSimulated={vi.fn()} />);

    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent(t.breaksNothing);
    expect(item).toHaveTextContent(t.directClues(messages.clues.typeLabels.face));
  });

  it("shows provenance-backed catalog-driven breakage labels including full_name", async () => {
    const name: Clue = {
      post_id: ADDRESS.post_id, image_index: null, type: "name_text", value: "内藤大貴",
      region: null, confidence: 0.9, source: "text",
    };
    const namePost = { post_id: ADDRESS.post_id, broken: ["full_name"] };
    const sim: Simulation = {
      delete: [ADDRESS.post_id], broken: ["full_name"], after: [],
    };
    vi.mocked(simulate).mockResolvedValue(sim);
    render(<RiskyPosts posts={[ADDRESS]} risky={[namePost]} clues={[name]} clueCount={1} onSimulated={vi.fn()} />);

    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent(t.breaks(attributeLabel("full_name")));
    expect(item).toHaveTextContent(t.directClues(messages.clues.typeLabels.name_text));

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByText(t.result(1, 1))).toBeInTheDocument();
    expect(screen.getByText(t.safe)).toBeInTheDocument();
    expect(within(screen.getByRole("status")).getByText(attributeLabel("full_name"))).toBeInTheDocument();
  });

  it("does not report escape while a profile candidate still has a surviving evidence path", async () => {
    const name: Clue = {
      post_id: ADDRESS.post_id, image_index: null, type: "name_text", value: "内藤大貴",
      region: null, confidence: 0.9, source: "text",
    };
    const ownerEvidence = { post_id: null, clue_index: null, required: true, source: "profile_text" as const, excerpt: "本名は内藤大貴" };
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const candidate = {
      rank: 1, value: "内藤大貴", confidence: 0.9, status: "found" as const,
      evidence: [ownerEvidence],
      evidence_paths: [{ evidence: [ownerEvidence], confidence: 0.9, provenance: "direct_disclosure" as const }],
      assessment, observed_at: null, counter_evidence: [],
    };
    const claim: ProfileCandidateSet = {
      attribute: "full_name", status: "candidate", candidates: [candidate], candidate_pool: [candidate],
      reason: null, conflicting_evidence: [],
    };
    vi.mocked(simulate).mockResolvedValue({ delete: [ADDRESS.post_id], broken: ["full_name"], after: onlyCandidateSet(claim) });
    render(<RiskyPosts posts={[ADDRESS]} risky={[{ post_id: ADDRESS.post_id, broken: ["full_name"] }]} clues={[name]} clueCount={1} profileClaims={[claim]} onSimulated={vi.fn()} />);

    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent(t.directClues(messages.clues.typeLabels.name_text));
    expect(item).toHaveTextContent(t.breaks(attributeLabel("full_name")));
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByText(t.result(1, 1))).toBeInTheDocument();
    expect(screen.queryByText(t.safe)).not.toBeInTheDocument();
  });

  it("simulates the selected posts and reports that the user got away", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    const onSimulated = renderRisky();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByText(t.result(2, 3))).toBeInTheDocument();
    expect(screen.getByText(t.safe)).toBeInTheDocument();
    expect(vi.mocked(simulate).mock.calls[0][0]).toEqual([ADDRESS.post_id, GYM.post_id]);
    expect(vi.mocked(simulate).mock.calls[0][1]).toBe(20);
    expect(onSimulated).toHaveBeenLastCalledWith(ALL_BROKEN);
  });

  it("sends only the posts that stay selected", async () => {
    // 宛名の投稿が残るので、最寄り駅は推定されたまま（逃げ切りにはならない）
    vi.mocked(simulate).mockResolvedValue({
      delete: [GYM.post_id],
      broken: ["routine"],
      after: [],
    });
    renderRisky();

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByText(t.safe)).toBeInTheDocument();
    expect(screen.getByText(t.safe)).toBeInTheDocument();
    expect(vi.mocked(simulate).mock.calls[0][0]).toEqual([GYM.post_id]);
  });

  it("drops the old result when the selection changes or on reset", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    const onSimulated = renderRisky();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    await screen.findByText(t.result(2, 3));
    fireEvent.click(screen.getAllByRole("checkbox")[1]);

    expect(screen.queryByText(t.result(2, 3))).not.toBeInTheDocument();
    expect(onSimulated).toHaveBeenLastCalledWith(null);

    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.reset }));

    expect(screen.queryByText(t.result(2, 3))).not.toBeInTheDocument();
    expect(onSimulated).toHaveBeenLastCalledWith(null);
  });

  it("cannot simulate with nothing selected", () => {
    renderRisky();

    for (const box of screen.getAllByRole("checkbox")) fireEvent.click(box);

    expect(screen.getByRole("button", { name: t.simulate })).toBeDisabled();
  });

  it("shows the api error", async () => {
    vi.mocked(simulate).mockRejectedValue(new ApiError("server", messages.errors.diagnoseFirst, 409));
    renderRisky();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.errors.diagnoseFirst);
  });

  it("hands an expired session to the caller instead of showing an error", async () => {
    vi.mocked(simulate).mockRejectedValue(new ApiError("unauthorized", messages.errors.sessionExpired, 401));
    const onSessionExpired = vi.fn();
    render(
      <RiskyPosts posts={[GYM, ADDRESS]} risky={RISKY} clueCount={20} onSimulated={vi.fn()} onSessionExpired={onSessionExpired} />,
    );

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    await vi.waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("hands an expired session to the caller when deleting", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockRejectedValue(new ApiError("unauthorized", messages.errors.sessionExpired, 401));
    const onSessionExpired = vi.fn();
    render(
      <RiskyPosts posts={[GYM, ADDRESS]} risky={RISKY} clueCount={20} onSimulated={vi.fn()} onSessionExpired={onSessionExpired} />,
    );
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));
    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    await vi.waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
  });

  it("shows how many catalog-driven items could be inferred before and after the simulated deletion", async () => {
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const ev = [
      { post_id: GYM.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: "根拠1" },
      { post_id: ADDRESS.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: "根拠2" },
    ];
    const makeSet = (attribute: ProfileAttribute, values: string[]): ProfileCandidateSet => {
      const sortedValues = [...values].sort((a, b) => a.localeCompare(b));
      const candidates = sortedValues.map((value, rankIndex) => ({
        rank: rankIndex + 1, value, confidence: 0.7, status: "weak" as const,
        evidence: ev, evidence_paths: [{ evidence: ev, confidence: 0.7, provenance: "direct_disclosure" as const }],
        assessment, observed_at: null, counter_evidence: [],
      }));
      return {
        attribute,
        status: candidates.length > 1 ? "ambiguous" : candidates.length === 1 ? "candidate" : "unknown",
        candidates,
        candidate_pool: candidates,
        reason: candidates.length > 0 ? null : "no_grounded_rule",
        conflicting_evidence: [],
      };
    };
    const before = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) =>
      attribute === "regular_station" ? makeSet(attribute, ["根津", "湯島"])
        : attribute === "routine" ? makeSet(attribute, ["毎週火曜"])
          : attribute === "employer_name" ? makeSet(attribute, ["青空株式会社"])
            : makeSet(attribute, []),
    );
    const after = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) =>
      attribute === "routine" ? makeSet(attribute, ["毎週火曜"]) : makeSet(attribute, []),
    );
    vi.mocked(simulate).mockResolvedValue({ ...ALL_BROKEN, broken: ["regular_station", "employer_name"], after });
    render(<RiskyPosts posts={[GYM, ADDRESS]} risky={RISKY} clueCount={20} onSimulated={vi.fn()} profileClaims={before} />);
    expect(screen.queryByRole("figure")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    // 同じ項目（よく使う駅）の候補が2つあっても1項目と数える：3 → 1
    const figure = await screen.findByRole("figure", { name: t.countLabel(3, 1) });
    expect(figure).toHaveTextContent(t.countHeading);
    // 減ったので、崩れた推定に「不明」の判子を押し、数を 1 つずつ減らし、最後に「もう、見つからない」
    const rows = within(figure).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("根津"),
      expect.stringContaining("青空株式会社"),
    ]);
    for (const row of rows) expect(within(row).getByText("不明")).toBeInTheDocument();
    expect(within(figure).getByText(ESCAPED_MESSAGE)).toBeInTheDocument();
  });

  it("keeps the plain counts without stamps when nothing was lost", async () => {
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const ev = [
      { post_id: GYM.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: "根拠1" },
      { post_id: ADDRESS.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: "根拠2" },
    ];
    const candidate = {
      rank: 1, value: "毎週火曜", confidence: 0.7, status: "weak" as const,
      evidence: ev, evidence_paths: [{ evidence: ev, confidence: 0.7, provenance: "direct_disclosure" as const }],
      assessment, observed_at: null, counter_evidence: [],
    };
    const before = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) =>
      attribute === "routine"
        ? { attribute, status: "candidate" as const, candidates: [candidate], candidate_pool: [candidate], reason: null, conflicting_evidence: [] }
        : { attribute, status: "unknown" as const, candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [] },
    );
    vi.mocked(simulate).mockResolvedValue({ ...ALL_BROKEN, broken: [], after: before });
    render(<RiskyPosts posts={[GYM, ADDRESS]} risky={RISKY} clueCount={20} onSimulated={vi.fn()} profileClaims={before} />);

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    const figure = await screen.findByRole("figure", { name: t.countLabel(1, 1) });
    expect(figure).toHaveTextContent("1→1");
    expect(within(figure).queryByText("不明")).not.toBeInTheDocument();
    expect(screen.queryByText(ESCAPED_MESSAGE)).not.toBeInTheDocument();
  });

  it("keeps showing the counts after deleting for real", async () => {
    const assessment = {
      minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
      inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
      harm_prerequisites: [], harm_status: "unknown" as const,
    };
    const ev = [
      { post_id: GYM.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: "根拠1" },
      { post_id: ADDRESS.post_id, clue_index: null, required: true, source: "post_text" as const, excerpt: "根拠2" },
    ];
    const candidate = {
      rank: 1, value: "毎週火曜", confidence: 0.7, status: "weak" as const,
      evidence: ev, evidence_paths: [{ evidence: ev, confidence: 0.7, provenance: "direct_disclosure" as const }],
      assessment, observed_at: null, counter_evidence: [],
    };
    const before: ProfileCandidateSet[] = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) =>
      attribute === "routine"
        ? { attribute, status: "candidate", candidates: [candidate], candidate_pool: [candidate], reason: null, conflicting_evidence: [] }
        : { attribute, status: "unknown", candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [] },
    );
    const emptyAfter: ProfileCandidateSet[] = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) => (
      { attribute, status: "unknown", candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [] }
    ));
    vi.mocked(simulate).mockResolvedValue({ ...ALL_BROKEN, after: emptyAfter });
    vi.mocked(deletePosts).mockResolvedValue({ ...ALL_BROKEN, after: emptyAfter, failed: [] });
    render(<RiskyPosts posts={[GYM, ADDRESS]} risky={RISKY} clueCount={20} onSimulated={vi.fn()} profileClaims={before} />);
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByText(messages.escaped.heading)).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: t.countLabel(1, 0) })).toBeInTheDocument();
  });

  it("does not show the counts without the conclusions before deletion", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByText(t.result(2, 3))).toBeInTheDocument();
    expect(screen.queryByRole("figure")).not.toBeInTheDocument();
  });

  it("offers to delete for real only after simulating", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();
    expect(screen.queryByRole("button", { name: t.deleteForReal })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t.simulate }));

    expect(await screen.findByRole("button", { name: t.deleteForReal })).toBeInTheDocument();
  });

  it("does not delete until the user confirms, and cancelling deletes nothing", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    const dialog = screen.getByRole("alertdialog", { name: t.confirmHeading });
    expect(dialog).toHaveTextContent(t.confirmLead(2));
    expect(within(dialog).getByRole("list", { name: t.confirmListLabel })).toHaveTextContent(ADDRESS.text);
    expect(within(dialog).getByRole("button", { name: t.cancel })).toHaveFocus();

    fireEvent.click(within(dialog).getByRole("button", { name: t.cancel }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deletePosts).not.toHaveBeenCalled();
  });

  it("closes the confirmation with Escape", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deletePosts).not.toHaveBeenCalled();
  });

  it("deletes the simulated posts once confirmed and shows that the user got away", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockResolvedValue({ ...ALL_BROKEN, failed: [] });
    const onSimulated = renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByText(messages.escaped.heading)).toBeInTheDocument();
    expect(screen.getByText(messages.escaped.deleted(2))).toBeInTheDocument();
    expect(screen.getByText(t.safe)).toBeInTheDocument();
    expect(vi.mocked(deletePosts).mock.calls[0][0]).toEqual([ADDRESS.post_id, GYM.post_id]);
    expect(vi.mocked(deletePosts).mock.calls[0][1]).toBe(20);
    expect(onSimulated).toHaveBeenLastCalledWith({ ...ALL_BROKEN, failed: [] });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    // 消したあとは選び直せない
    expect(screen.queryByRole("button", { name: t.simulate })).not.toBeInTheDocument();
    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeDisabled();
  });

  it("says which posts could not be deleted", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockResolvedValue({
      delete: [GYM.post_id],
      failed: [ADDRESS.post_id],
      broken: ["routine"],
      after: [],
    });
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByText(messages.escaped.deleted(1))).toBeInTheDocument();
    expect(screen.getByText(messages.escaped.failed(1))).toBeInTheDocument();
    expect(screen.queryByText(t.safe)).not.toBeInTheDocument();
  });

  it("says Bluesky was busy when it stopped the deletion midway", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockResolvedValue({
      delete: [GYM.post_id],
      failed: [ADDRESS.post_id],
      broken: ["routine"],
      after: [],
      bluesky_busy: true,
    });
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByText(messages.escaped.blueskyBusy(1))).toBeInTheDocument();
    expect(screen.queryByText(messages.escaped.failed(1))).not.toBeInTheDocument();
  });

  it("shows the error when deleting fails and keeps the simulation", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    vi.mocked(deletePosts).mockRejectedValue(new Error("boom"));
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    fireEvent.click(await screen.findByRole("button", { name: t.deleteForReal }));

    fireEvent.click(screen.getByRole("button", { name: t.confirm }));

    expect(await screen.findByRole("alert")).toHaveTextContent(t.deleteFailed);
    expect(screen.getByRole("alert")).not.toHaveTextContent("boom");
    expect(screen.getByRole("button", { name: t.deleteForReal })).toBeInTheDocument();
  });

  it("says so when no post can break the profile", () => {
    render(<RiskyPosts posts={[]} risky={[]} clueCount={0} onSimulated={vi.fn()} />);

    expect(screen.getByText(t.none)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t.simulate })).not.toBeInTheDocument();
  });
});


it("does not report escape while a catalog-driven residential_area claim survives", async () => {
  const assessment = {
    minimal_scope: "bluesky" as const, offline_subtype: null, psychological_resistance: null, persona_context: null,
    inference_ease: null, inference_ease_basis: null, harm_severity: null, harm_scenario: null,
    harm_prerequisites: [], harm_status: "unknown" as const,
  };
  const ev = [
    { post_id: "at://did:plc:abc/app.bsky.feed.post/other", clue_index: null, required: true, source: "post_text" as const, excerpt: "架空町1" },
    { post_id: "at://did:plc:abc/app.bsky.feed.post/other2", clue_index: null, required: true, source: "post_text" as const, excerpt: "架空町2" },
  ];
  const survivingCandidate = {
    rank: 1, value: "架空町付近", confidence: 0.65, status: "weak" as const,
    evidence: ev, evidence_paths: [{ evidence: ev, confidence: 0.65, provenance: "combined_inference" as const }],
    assessment, observed_at: null, counter_evidence: [],
  };
  const survivingAfter: ProfileCandidateSet[] = PROFILE_DIAGNOSED_ATTRIBUTES.map((attribute) =>
    attribute === "residential_area"
      ? {
        attribute, status: "candidate",
        candidates: [survivingCandidate],
        candidate_pool: [survivingCandidate], reason: null, conflicting_evidence: [],
      }
      : { attribute, status: "unknown", candidates: [], candidate_pool: [], reason: "no_grounded_rule", conflicting_evidence: [] },
  );
  vi.mocked(simulate).mockResolvedValue({
    ...ALL_BROKEN,
    after: survivingAfter,
  });
  renderRisky();
  fireEvent.click(screen.getByRole("button", { name: t.simulate }));
  expect(await screen.findByText(t.result(2, 3))).toBeInTheDocument();
  expect(screen.queryByText(t.safe)).not.toBeInTheDocument();
});

describe("InviteLink", () => {
  it("invites friends with only the fixed text and the site URL, never the diagnosis", async () => {
    vi.mocked(simulate).mockResolvedValue(ALL_BROKEN);
    renderRisky();
    fireEvent.click(screen.getByRole("button", { name: t.simulate }));
    await screen.findByText(t.result(2, 3));

    const link = screen.getByRole("link", { name: messages.invite.link });
    const href = link.getAttribute("href") ?? "";
    expect(href.startsWith("https://bsky.app/intent/compose?text=")).toBe(true);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    const text = new URL(href).searchParams.get("text");
    expect(text).toBe(`${messages.invite.text}\n${window.location.origin}/`);
    // 投稿の本文・ハンドル・項目名・件数は入らない
    for (const leak of [GYM.text, ADDRESS.text, "did:plc", "最寄り駅", "決まった外出", "2 件", "3 つ"]) {
      expect(text).not.toContain(leak);
    }
  });

  it("offers the invite even when there is nothing to delete", () => {
    render(<RiskyPosts posts={[]} risky={[]} clueCount={0} onSimulated={vi.fn()} />);

    expect(screen.getByRole("link", { name: messages.invite.link })).toBeInTheDocument();
  });

  it("builds the compose URL from the origin alone", () => {
    const text = new URL(inviteComposeUrl("https://d111.cloudfront.net")).searchParams.get("text");
    expect(text).toBe(`${messages.invite.text}\nhttps://d111.cloudfront.net/`);
  });
});
