import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createSession,
  deleteSession,
  detectClues,
  diagnose,
  getSession,
  MAX_IMAGE_BYTES,
  simulate,
} from "./api";
import { messages } from "@/lib/messages";

const RESPONSE = {
  clues: [
    {
      post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
      image_index: 0,
      type: "phone",
      value: "03-0000-0000",
      region: [1, 2, 3, 4],
      confidence: 0.8,
      source: "ocr",
    },
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

describe("createSession", () => {
  const SESSION = { handle: "alice.bsky.social", did: "did:plc:abc" };

  it("posts the handle and password as JSON with cookies", async () => {
    const fetchFn = mockFetch(Response.json(SESSION));

    const result = await createSession("alice.bsky.social", "pw", { baseUrl: "http://api.test" });

    expect(result).toEqual(SESSION);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://api.test/api/session");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(JSON.parse(init?.body as string)).toEqual({
      handle: "alice.bsky.social",
      password: "pw",
    });
  });

  it("maps 401 to unauthorized", async () => {
    mockFetch(new Response(null, { status: 401 }));
    await expect(createSession("a", "b")).rejects.toMatchObject({ kind: "unauthorized", status: 401 });
  });

  it("maps other errors to server", async () => {
    mockFetch(new Response(null, { status: 502 }));
    await expect(createSession("a", "b")).rejects.toMatchObject({ kind: "server", status: 502 });
  });

  it("maps fetch failures to network", async () => {
    mockFetch(new TypeError("offline"));
    await expect(createSession("a", "b")).rejects.toMatchObject({ kind: "network" });
  });

  it("rejects responses of the wrong shape", async () => {
    mockFetch(Response.json({ handle: "a" }));
    await expect(createSession("a", "b")).rejects.toMatchObject({ kind: "invalid_response" });
  });
});

describe("deleteSession", () => {
  it("sends DELETE with cookies", async () => {
    const fetchFn = mockFetch(new Response(null, { status: 204 }));

    await deleteSession({ baseUrl: "http://api.test" });

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://api.test/api/session");
    expect(init?.method).toBe("DELETE");
    expect(init?.credentials).toBe("include");
  });

  it("maps errors", async () => {
    mockFetch(new Response(null, { status: 500 }));
    await expect(deleteSession()).rejects.toBeInstanceOf(ApiError);
    mockFetch(new TypeError("offline"));
    await expect(deleteSession()).rejects.toMatchObject({ kind: "network" });
  });
});

describe("default base URL", () => {
  it("calls the api through the same origin, so the session cookie works behind the /api rewrite", async () => {
    const fetchFn = mockFetch(new Response(null, { status: 401 }));

    await getSession();

    expect(fetchFn.mock.calls[0][0]).toBe("/api/session");
  });
});

describe("getSession", () => {
  const SESSION = { handle: "alice.bsky.social", did: "did:plc:abc" };

  it("returns the logged-in account with cookies", async () => {
    const fetchFn = mockFetch(Response.json(SESSION));

    expect(await getSession({ baseUrl: "http://api.test" })).toEqual(SESSION);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://api.test/api/session");
    expect(init?.credentials).toBe("include");
  });

  it("returns null when not logged in", async () => {
    mockFetch(new Response(null, { status: 401 }));
    expect(await getSession()).toBeNull();
  });

  it("maps errors", async () => {
    mockFetch(new Response(null, { status: 500 }));
    await expect(getSession()).rejects.toMatchObject({ kind: "server" });
    mockFetch(Response.json({ handle: "a" }));
    await expect(getSession()).rejects.toMatchObject({ kind: "invalid_response" });
    mockFetch(new TypeError("offline"));
    await expect(getSession()).rejects.toMatchObject({ kind: "network" });
  });
});

describe("diagnose", () => {
  const POST = {
    post_id: "at://did:plc:xxxx/app.bsky.feed.post/3kxxxx",
    text: "夜勤明けのラーメン",
    created_at: "2026-10-20T08:31:00+09:00",
    images: [],
  };

  function sse(body: string, status = 200): Response {
    return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
  }

  async function collect(): Promise<unknown[]> {
    const events: unknown[] = [];
    for await (const event of diagnose({ baseUrl: "http://api.test" })) events.push(event);
    return events;
  }

  it("posts with cookies and yields events in the order they arrive", async () => {
    const fetchFn = mockFetch(
      sse(`event: post\ndata: ${JSON.stringify({ post: POST })}\n\nevent: done\ndata: {"posts_seen":1}\n\n`),
    );

    expect(await collect()).toEqual([
      { event: "post", post: POST },
      { event: "done", posts_seen: 1 },
    ]);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://api.test/api/diagnose");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
  });

  it("skips events the screen does not know yet", async () => {
    mockFetch(sse('event: profile\ndata: {"items":[]}\n\nevent: done\ndata: {"posts_seen":0}\n\n'));
    expect(await collect()).toEqual([{ event: "done", posts_seen: 0 }]);
  });

  it("asks to log in again when the session has expired", async () => {
    mockFetch(sse("", 401));
    await expect(collect()).rejects.toMatchObject({ kind: "unauthorized" });
  });

  it("maps errors", async () => {
    mockFetch(sse("", 500));
    await expect(collect()).rejects.toMatchObject({ kind: "server" });
    mockFetch(new TypeError("offline"));
    await expect(collect()).rejects.toMatchObject({ kind: "network" });
    mockFetch(sse('event: post\ndata: {"post":{}}\n\n'));
    await expect(collect()).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("fails when the stream ends before done", async () => {
    mockFetch(sse(`event: post\ndata: ${JSON.stringify({ post: POST })}\n\n`));
    const error = await collect().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: "network" });
  });
});

describe("simulate", () => {
  const POST_ID = "at://did:plc:abc/app.bsky.feed.post/3k9";
  const RESULT = {
    delete: [POST_ID],
    broken: ["station"],
    after: [{ rule: "R3", attribute: "routine", value: "毎週火曜", clue_indices: [2], note: "" }],
  };

  function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }

  it("posts only the selected ids with cookies and returns what breaks", async () => {
    const fetchFn = mockFetch(json(RESULT));

    expect(await simulate([POST_ID], 3, { baseUrl: "http://api.test" })).toEqual(RESULT);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("http://api.test/api/simulate");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(JSON.parse(init?.body as string)).toEqual({ delete: [POST_ID] });
  });

  it("rejects evidence numbers beyond the diagnosed clues", async () => {
    mockFetch(json(RESULT));
    await expect(simulate([POST_ID], 2)).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("asks to diagnose first when the api has no diagnosis", async () => {
    mockFetch(json({ detail: "先に診断してください" }, 409));
    await expect(simulate([POST_ID], 3)).rejects.toMatchObject({ kind: "server", message: messages.errors.diagnoseFirst });
  });

  it("asks to log in again when the session has expired", async () => {
    mockFetch(json({ detail: "ログインしてください" }, 401));
    await expect(simulate([POST_ID], 3)).rejects.toMatchObject({ kind: "unauthorized" });
  });
});
