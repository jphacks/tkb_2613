import { Agent } from "@atproto/api";
import { NextResponse } from "next/server";

import { authMode, getOAuthClient, validInternalSecret } from "@/lib/server/oauth";

export async function POST(request: Request) {
  if (authMode() !== "oauth" || !validInternalSecret(request)) return new NextResponse(null, { status: 403 });
  let input: unknown;
  try { input = await request.json(); } catch { return new NextResponse(null, { status: 400 }); }
  if (typeof input !== "object" || input === null || !("did" in input) || !("post_id" in input) ||
    typeof input.did !== "string" || typeof input.post_id !== "string") return new NextResponse(null, { status: 400 });
  const match = /^at:\/\/(did:(?:plc|web):[A-Za-z0-9._:%-]+)\/app\.bsky\.feed\.post\/([A-Za-z0-9._~-]+)$/.exec(input.post_id);
  if (!match || match[1] !== input.did || match[2] === "." || match[2] === "..") return new NextResponse(null, { status: 403 });
  try {
    const session = await getOAuthClient().restore(input.did);
    const agent = new Agent(session);
    if (agent.did !== input.did) return new NextResponse(null, { status: 403 });
    await agent.com.atproto.repo.deleteRecord({ repo: input.did, collection: "app.bsky.feed.post", rkey: match[2] });
    return NextResponse.json({ deleted: true }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const limited = typeof error === "object" && error !== null && "status" in error && error.status === 429;
    return NextResponse.json({ deleted: false }, { status: limited ? 429 : 502, headers: { "Cache-Control": "no-store" } });
  }
}
