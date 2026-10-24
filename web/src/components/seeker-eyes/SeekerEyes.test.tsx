import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SeekerEyes } from "./SeekerEyes";

describe("SeekerEyes", () => {
  it("is decoration only and is hidden from screen readers", () => {
    const { container } = render(<SeekerEyes />);

    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });
});
