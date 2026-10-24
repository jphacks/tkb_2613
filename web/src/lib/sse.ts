/**
 * Server-Sent Events を読む。EventSource は GET しか使えないので、POST の応答本文（fetch の body）を
 * 自分で区切る。形式は https://html.spec.whatwg.org/multipage/server-sent-events.html の一部だけ
 * （event と data）を扱う。
 */

export interface SseMessage {
  /** event: の値。書かれていなければ "message" */
  readonly event: string;
  /** data: の値。複数行なら改行でつなぐ */
  readonly data: string;
}

function parseBlock(block: string): SseMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  // stream: true で、途中で切れたマルチバイト文字を次のかたまりまで持ち越す
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const message = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (message) yield message;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
