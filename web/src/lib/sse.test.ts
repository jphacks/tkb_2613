import { describe, expect, it } from "vitest";

import { readSse, type SseMessage } from "./sse";

/** 文字列を、指定した区切りで分けて届くストリームにする（ネットワークで途中から届く状態を再現する） */
function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<SseMessage[]> {
  const messages: SseMessage[] = [];
  for await (const message of readSse(stream)) messages.push(message);
  return messages;
}

describe("readSse", () => {
  it("splits messages by blank lines and reads event and data", async () => {
    const messages = await collect(streamOf('event: post\ndata: {"a":1}\n\nevent: done\ndata: {}\n\n'));

    expect(messages).toEqual([
      { event: "post", data: '{"a":1}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("joins a message that arrives split across chunks, even inside a multibyte character", async () => {
    const bytes = new TextEncoder().encode('event: post\ndata: {"text":"夜勤明け"}\n\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 25));
        controller.enqueue(bytes.slice(25));
        controller.close();
      },
    });

    expect(await collect(stream)).toEqual([{ event: "post", data: '{"text":"夜勤明け"}' }]);
  });

  it("accepts CRLF line endings", async () => {
    expect(await collect(streamOf("event: done\r\ndata: {}\r\n\r\n"))).toEqual([{ event: "done", data: "{}" }]);
  });

  it("joins multiple data lines with a newline", async () => {
    expect(await collect(streamOf("data: a\ndata: b\n\n"))).toEqual([{ event: "message", data: "a\nb" }]);
  });

  it("ignores comment lines and messages without data", async () => {
    expect(await collect(streamOf(": keep-alive\n\nevent: post\n\ndata: x\n\n"))).toEqual([
      { event: "message", data: "x" },
    ]);
  });

  it("drops an unfinished message at the end of the stream", async () => {
    expect(await collect(streamOf("data: x\n\ndata: half"))).toEqual([{ event: "message", data: "x" }]);
  });
});
