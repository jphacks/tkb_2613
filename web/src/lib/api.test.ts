import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, detectClues, MAX_IMAGE_BYTES } from "./api";

const RESPONSE = {
  clues: [
    { type: "phone", value: "03-0000-0000", region: [1, 2, 3, 4], confidence: 0.8, source: "ocr" },
  ],
};

function jpeg(size = 8): File {
  return new File([new Uint8Array(size)], "photo.jpg", { type: "image/jpeg" });
}

function mockFetch(response: Response | Error) {
  const fn = vi.fn<typeof fetch>(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("detectClues", () => {
  it("posts the image as the raw body and returns clues", async () => {
    const fetchFn = mockFetch(Response.json(RESPONSE));
    const file = jpeg();

    const result = await detectClues(file, { baseUrl: "http://api.test" });

    expect(result).toEqual(RESPONSE);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://api.test/api/detect");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(file);
    expect(new Headers(init?.headers).get("Content-Type")).toBe("image/jpeg");
  });

  it("rejects unsupported file types before sending", async () => {
    const fetchFn = mockFetch(Response.json(RESPONSE));
    const gif = new File(["x"], "a.gif", { type: "image/gif" });

    await expect(detectClues(gif)).rejects.toMatchObject({ kind: "unsupported_type" });
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("rejects oversized files before sending", async () => {
    const fetchFn = mockFetch(Response.json(RESPONSE));

    await expect(detectClues(jpeg(MAX_IMAGE_BYTES + 1))).rejects.toMatchObject({
      kind: "too_large",
    });
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("reports a network failure", async () => {
    mockFetch(new TypeError("Failed to fetch"));

    await expect(detectClues(jpeg())).rejects.toMatchObject({ kind: "network" });
  });

  it("reports a server error status", async () => {
    mockFetch(new Response("", { status: 501 }));

    const error = await detectClues(jpeg()).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: "server", status: 501 });
  });

  it("rejects a response that does not match the clue format", async () => {
    mockFetch(Response.json({ clues: [{ type: "nope" }] }));

    await expect(detectClues(jpeg())).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("rejects a response that is not JSON", async () => {
    mockFetch(new Response("not json", { status: 200 }));

    await expect(detectClues(jpeg())).rejects.toMatchObject({ kind: "invalid_response" });
  });
});
