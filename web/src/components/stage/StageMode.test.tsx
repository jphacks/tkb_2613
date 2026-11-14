import { render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { STAGE_KEY, StageMode } from "./StageMode";

function visit(search: string) {
  window.history.replaceState(null, "", `/${search}`);
  return render(<StageMode />);
}

afterEach(() => {
  window.sessionStorage.clear();
  document.documentElement.classList.remove("stage");
  window.history.replaceState(null, "", "/");
});

describe("StageMode", () => {
  it("leaves the normal display untouched without ?stage=1", () => {
    visit("");
    expect(document.documentElement).not.toHaveClass("stage");
    expect(window.sessionStorage.getItem(STAGE_KEY)).toBeNull();
  });

  it("turns on the presentation mode with ?stage=1 and keeps it in this tab", () => {
    visit("?stage=1").unmount();
    expect(document.documentElement).toHaveClass("stage");
    expect(window.sessionStorage.getItem(STAGE_KEY)).toBe("1");

    // 同じタブで別の画面へ移っても（クエリがなくても）発表モードのまま
    document.documentElement.classList.remove("stage");
    visit("");
    expect(document.documentElement).toHaveClass("stage");
  });

  it("turns it off with ?stage=0", () => {
    window.sessionStorage.setItem(STAGE_KEY, "1");
    visit("?stage=0");
    expect(document.documentElement).not.toHaveClass("stage");
    expect(window.sessionStorage.getItem(STAGE_KEY)).toBeNull();
  });

  it("works even when the browser refuses the tab storage", () => {
    const original = Object.getOwnPropertyDescriptor(window, "sessionStorage");
    Object.defineProperty(window, "sessionStorage", { configurable: true, get: () => { throw new Error("blocked"); } });
    try {
      visit("?stage=1");
      expect(document.documentElement).toHaveClass("stage");
    } finally {
      if (original) Object.defineProperty(window, "sessionStorage", original);
    }
  });
});
