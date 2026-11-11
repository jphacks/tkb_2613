import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { messages } from "@/lib/messages";
import type { RiskyPost } from "@/types/diagnose";

import { PlanSummary } from "./PlanSummary";

const t = messages.plan;
const label = (a: string) => messages.board.attributeLabels[a] ?? a;

const RISKY: RiskyPost[] = [
  { post_id: "at://did:plc:abc/app.bsky.feed.post/3k1", broken: ["age", "given_name_or_nickname"] },
  { post_id: "at://did:plc:abc/app.bsky.feed.post/3k2", broken: [] },
  { post_id: "at://did:plc:abc/app.bsky.feed.post/3k3", broken: ["routine", "age"] },
];

describe("PlanSummary", () => {
  it("says how many posts to delete and which items break, without duplicates", () => {
    render(<PlanSummary risky={RISKY} targetId="risky-heading" />);

    const summary = screen.getByRole("region", { name: t.label });
    expect(summary).toHaveTextContent(
      t.breaks(3, [label("age"), label("given_name_or_nickname"), label("routine")].join("・")),
    );
  });

  it("links to the list of posts to delete", () => {
    render(<PlanSummary risky={RISKY} targetId="risky-heading" />);

    expect(screen.getByRole("link", { name: t.show })).toHaveAttribute("href", "#risky-heading");
  });

  it("shows the four steps and marks choosing posts as the current one", () => {
    render(<PlanSummary risky={RISKY} targetId="risky-heading" />);

    const steps = within(screen.getByRole("list", { name: t.stepsLabel })).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(steps[2]).toHaveTextContent(t.steps[2]);
  });

  it("falls back to direct clues when no single post breaks an item", () => {
    render(<PlanSummary risky={[RISKY[1]]} targetId="risky-heading" />);

    expect(screen.getByRole("region", { name: t.label })).toHaveTextContent(t.direct(1));
  });

  it("has no link when there is nothing to delete", () => {
    render(<PlanSummary risky={[]} targetId="risky-heading" />);

    expect(screen.getByRole("region", { name: t.label })).toHaveTextContent(t.none);
    expect(screen.queryByRole("link", { name: t.show })).not.toBeInTheDocument();
  });
});
