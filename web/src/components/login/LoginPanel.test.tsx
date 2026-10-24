import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/session/SessionProvider";
import { ApiError, createSession, deleteSession, getSession } from "@/lib/api";

import { LoginPanel } from "./LoginPanel";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, createSession: vi.fn(), deleteSession: vi.fn(), getSession: vi.fn() };
});

const PASSWORD = "correct horse battery staple";
const ALICE = { handle: "alice.bsky.social", did: "did:plc:abc" };

async function renderLoggedOut() {
  render(
    <SessionProvider>
      <LoginPanel />
    </SessionProvider>,
  );
  await screen.findByLabelText("ハンドル名");
}

function fill(handle: string, password: string) {
  fireEvent.change(screen.getByLabelText("ハンドル名"), { target: { value: handle } });
  fireEvent.change(screen.getByLabelText("パスワード"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "もういいかい？" }));
}

beforeEach(() => {
  vi.mocked(getSession).mockResolvedValue(null);
});

afterEach(() => {
  vi.mocked(createSession).mockReset();
  vi.mocked(deleteSession).mockReset();
  vi.mocked(getSession).mockReset();
});

describe("LoginPanel", () => {
  it("shows a status while checking the existing session", () => {
    vi.mocked(getSession).mockReturnValue(new Promise(() => {}));
    render(
      <SessionProvider>
        <LoginPanel />
      </SessionProvider>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("ログイン状態を確認しています");
  });

  it("restores the logged-in account when the cookie is still valid", async () => {
    vi.mocked(getSession).mockResolvedValue(ALICE);
    render(
      <SessionProvider>
        <LoginPanel />
      </SessionProvider>,
    );

    expect(await screen.findByText("@alice.bsky.social")).toBeInTheDocument();
  });

  it("shows loading UI and disables the form while logging in", async () => {
    // React は実行中のアクションが終わるまで他のアクションの結果を反映しないので、最後に必ず終わらせる
    const { promise, resolve } = Promise.withResolvers<typeof ALICE>();
    vi.mocked(createSession).mockReturnValue(promise);
    await renderLoggedOut();

    fill("alice.bsky.social", PASSWORD);

    expect(await screen.findByRole("status")).toHaveTextContent("Bluesky にログインしています");
    expect(screen.getByLabelText("ハンドル名")).toBeDisabled();
    expect(screen.getByRole("button", { name: "もういいかい？" })).toBeDisabled();

    resolve(ALICE);
    expect(await screen.findByText("@alice.bsky.social")).toBeInTheDocument();
  });

  it("logs in with a normalized handle and the password as typed", async () => {
    vi.mocked(createSession).mockResolvedValue(ALICE);
    await renderLoggedOut();

    fill(" @alice.bsky.social ", PASSWORD);

    expect(await screen.findByText("@alice.bsky.social")).toBeInTheDocument();
    expect(createSession).toHaveBeenCalledWith("alice.bsky.social", PASSWORD);
  });

  it("keeps the handle but clears the password when login fails", async () => {
    vi.mocked(createSession).mockRejectedValue(
      new ApiError("unauthorized", "ハンドル名かパスワードが違います", 401),
    );
    await renderLoggedOut();

    fill("alice.bsky.social", PASSWORD);

    expect(await screen.findByRole("alert")).toHaveTextContent("ハンドル名かパスワードが違います");
    expect(screen.getByLabelText("ハンドル名")).toHaveValue("alice.bsky.social");
    expect(screen.getByLabelText("パスワード")).toHaveValue("");
  });

  it("shows a generic message for unexpected errors", async () => {
    vi.mocked(createSession).mockRejectedValue(new Error("boom"));
    await renderLoggedOut();

    fill("alice.bsky.social", PASSWORD);

    expect(await screen.findByRole("alert")).toHaveTextContent("ログインできませんでした");
  });

  it("returns to the form after logging out, even if the api fails", async () => {
    vi.mocked(createSession).mockResolvedValue(ALICE);
    vi.mocked(deleteSession).mockRejectedValue(new ApiError("network", "x"));
    await renderLoggedOut();
    fill("alice.bsky.social", PASSWORD);

    fireEvent.click(await screen.findByRole("button", { name: "ログアウト" }));

    expect(await screen.findByLabelText("ハンドル名")).toBeInTheDocument();
    expect(deleteSession).toHaveBeenCalled();
  });
});
