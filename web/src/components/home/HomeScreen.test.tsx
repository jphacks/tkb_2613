import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/session/SessionProvider";
import { deleteSession, getSession } from "@/lib/api";
import { messages } from "@/lib/messages";

import { HomeScreen } from "./HomeScreen";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, deleteSession: vi.fn(), getSession: vi.fn() };
});

// 診断そのものは DiagnosePanel のテストで見るので、ここでは「結果が出た」を知らせるボタンにする
vi.mock("@/components/diagnose/DiagnosePanel", () => ({
  DiagnosePanel: ({ onRevealedChange }: { onRevealedChange: (revealed: boolean) => void }) => (
    <button type="button" onClick={() => onRevealedChange(true)}>
      reveal
    </button>
  ),
}));

afterEach(() => {
  vi.mocked(deleteSession).mockReset();
  vi.mocked(getSession).mockReset();
});

describe("HomeScreen", () => {
  it("hides the title and the login bar once the result is revealed, and brings them back after logout", async () => {
    vi.mocked(getSession).mockResolvedValue({ handle: "alice.bsky.social", did: "did:plc:abc" });
    vi.mocked(deleteSession).mockResolvedValue(undefined);
    render(
      <SessionProvider>
        <HomeScreen />
      </SessionProvider>,
    );
    expect(await screen.findByText("@alice.bsky.social")).toBeInTheDocument();
    expect(screen.getByText(messages.home.lead)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "reveal" }));

    expect(screen.queryByText(messages.home.lead)).not.toBeInTheDocument();
    expect(screen.queryByText("@alice.bsky.social")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: messages.login.logout }));

    expect(await screen.findByText(messages.home.lead)).toBeInTheDocument();
    expect(deleteSession).toHaveBeenCalled();
  });
});
