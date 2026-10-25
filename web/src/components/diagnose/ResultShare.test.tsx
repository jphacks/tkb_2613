import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createResultLink, revokeResultLink } from "@/lib/api";

import { ResultShare } from "./ResultShare";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, createResultLink: vi.fn(), revokeResultLink: vi.fn() };
});

afterEach(() => {
  vi.mocked(createResultLink).mockReset();
  vi.mocked(revokeResultLink).mockReset();
});

describe("ResultShare", () => {
  it("creates a read-only link only after the owner clicks, and keeps the token after #", async () => {
    vi.mocked(createResultLink).mockResolvedValue("a".repeat(43));
    render(<ResultShare />);
    expect(createResultLink).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "閲覧リンクを作る" }));

    const input = await screen.findByRole("textbox", { name: "閲覧リンク" });
    expect(input).toHaveValue(`${window.location.origin}/share#${"a".repeat(43)}`);
    expect(screen.getByRole("link", { name: "別の画面で開く" })).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("lets the owner revoke the link", async () => {
    vi.mocked(createResultLink).mockResolvedValue("a".repeat(43));
    vi.mocked(revokeResultLink).mockResolvedValue();
    render(<ResultShare />);
    fireEvent.click(screen.getByRole("button", { name: "閲覧リンクを作る" }));
    fireEvent.click(await screen.findByRole("button", { name: "リンクを無効にする" }));
    expect(await screen.findByRole("button", { name: "閲覧リンクを作る" })).toBeInTheDocument();
    expect(revokeResultLink).toHaveBeenCalledWith("a".repeat(43));
  });
});
