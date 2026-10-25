import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/session/SessionProvider";
import { createSession, deleteSession, getSession } from "@/lib/api";
import { messages } from "@/lib/messages";

import { HomeScreen } from "./HomeScreen";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, createSession: vi.fn(), deleteSession: vi.fn(), getSession: vi.fn() };
});

// 診断そのものは DiagnosePanel のテストで見るので、ここでは結果を中に持ち、「結果が出た」を知らせるボタンにする。
// 本物と同じく、ログインしていなければ何も出さない（隠れるだけで、中の状態は残る）
vi.mock("@/components/diagnose/DiagnosePanel", async () => {
  const { useSession } = await import("@/components/session/SessionProvider");
  return {
    DiagnosePanel: ({ onRevealedChange }: { onRevealedChange: (revealed: boolean) => void }) => {
      const { state } = useSession();
      const [result, setResult] = useState<string | null>(null);
      if (state.status !== "authenticated") return null;
      return (
        <>
          <button
            type="button"
            onClick={() => {
              setResult(`result of ${state.session.handle}`);
              onRevealedChange(true);
            }}
          >
            reveal
          </button>
          {result && <p>{result}</p>}
        </>
      );
    },
  };
});

afterEach(() => {
  vi.mocked(createSession).mockReset();
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

  it("does not keep the previous account's result after logging out and in as someone else", async () => {
    vi.mocked(getSession).mockResolvedValue({ handle: "alice.bsky.social", did: "did:plc:alice" });
    vi.mocked(deleteSession).mockResolvedValue(undefined);
    vi.mocked(createSession).mockResolvedValue({ handle: "bob.bsky.social", did: "did:plc:bob" });
    render(
      <SessionProvider>
        <HomeScreen />
      </SessionProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "reveal" }));
    expect(screen.getByText("result of alice.bsky.social")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: messages.login.logout }));
    fireEvent.change(await screen.findByLabelText(messages.login.handle), { target: { value: "bob.bsky.social" } });
    fireEvent.change(screen.getByLabelText(messages.login.password), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: messages.login.submit }));

    expect(await screen.findByText("@bob.bsky.social")).toBeInTheDocument();
    expect(screen.queryByText("result of alice.bsky.social")).not.toBeInTheDocument();
    // 前の結果を見せていた印も消え、タイトルが出ている
    expect(screen.getByText(messages.home.lead)).toBeInTheDocument();
  });
});
