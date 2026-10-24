import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/session/SessionProvider";
import { ApiError, createSession, deleteSession, getSession } from "@/lib/api";
import { messages } from "@/lib/messages";

import { LoginPanel } from "./LoginPanel";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, createSession: vi.fn(), deleteSession: vi.fn(), getSession: vi.fn() };
});

const t = messages.login;
const PASSWORD = "correct horse battery staple";
const ALICE = { handle: "alice.bsky.social", did: "did:plc:abc" };

async function renderLoggedOut() {
  render(
    <SessionProvider>
      <LoginPanel />
    </SessionProvider>,
  );
  await screen.findByLabelText(t.handle);
}

function fill(handle: string, password: string) {
  fireEvent.change(screen.getByLabelText(t.handle), { target: { value: handle } });
  fireEvent.change(screen.getByLabelText(t.password), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: t.submit }));
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

    expect(screen.getByRole("status")).toHaveTextContent(t.checking);
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

    expect(await screen.findByRole("status")).toHaveTextContent(t.pending);
    expect(screen.getByLabelText(t.handle)).toBeDisabled();
    expect(screen.getByRole("button", { name: t.submit })).toBeDisabled();

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
    expect(screen.getByLabelText(t.handle)).toHaveValue("alice.bsky.social");
    expect(screen.getByLabelText(t.password)).toHaveValue("");
  });

  it("shows a generic message for unexpected errors", async () => {
    vi.mocked(createSession).mockRejectedValue(new Error("boom"));
    await renderLoggedOut();

    fill("alice.bsky.social", PASSWORD);

    expect(await screen.findByRole("alert")).toHaveTextContent(t.failed);
  });

  it("returns to the form after logging out, even if the api fails", async () => {
    vi.mocked(createSession).mockResolvedValue(ALICE);
    vi.mocked(deleteSession).mockRejectedValue(new ApiError("network", "x"));
    await renderLoggedOut();
    fill("alice.bsky.social", PASSWORD);

    fireEvent.click(await screen.findByRole("button", { name: t.logout }));

    expect(await screen.findByLabelText(t.handle)).toBeInTheDocument();
    expect(deleteSession).toHaveBeenCalled();
  });
});
