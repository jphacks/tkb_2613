import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getSession } from "@/lib/api";

import { SessionProvider, useSession } from "./SessionProvider";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getSession: vi.fn() };
});

function Status() {
  const { state } = useSession();
  return <p>{state.status}</p>;
}

afterEach(() => {
  vi.mocked(getSession).mockReset();
});

describe("SessionProvider", () => {
  it("treats a failed check as logged out", async () => {
    vi.mocked(getSession).mockRejectedValue(new ApiError("network", "x"));
    render(
      <SessionProvider>
        <Status />
      </SessionProvider>,
    );

    expect(await screen.findByText("anonymous")).toBeInTheDocument();
  });

  it("requires the provider", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Status />)).toThrow("SessionProvider");
  });
});
