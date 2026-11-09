import { Agent } from "@atproto/api";
import { connection, NextRequest, NextResponse } from "next/server";

import { authMode, forgetOAuthSession, getOAuthClient, pendingStateMatches, publicUrl, resetOAuthExpiry, START_COOKIE } from "@/lib/server/oauth";

export async function GET(request: NextRequest) {
  await connection();
  const failed = NextResponse.redirect(new URL("/?auth_error=1", publicUrl()));
  failed.cookies.delete(START_COOKIE);
  failed.headers.set("Cache-Control", "no-store");
  if (authMode() !== "oauth") return failed;
  const expected = request.cookies.get(START_COOKIE)?.value;
  const actual = request.nextUrl.searchParams.get("state");
  if (!pendingStateMatches(actual, expected)) return failed;
  let sessionDid: string | null = null;
  try {
    const { session, state } = await getOAuthClient().callback(request.nextUrl.searchParams);
    sessionDid = session.did;
    if (state !== expected) {
      forgetOAuthSession(session.did);
      return failed;
    }
    resetOAuthExpiry(session.did);
    const agent = new Agent({ service: "https://public.api.bsky.app" });
    const profile = await agent.app.bsky.actor.getProfile({ actor: session.did });
    if (profile.data.did !== session.did) throw new Error("DID mismatch");
    const secret = process.env.INTERNAL_AUTH_SECRET;
    if (!secret) throw new Error("Internal auth is not configured");
    const completed = await fetch(`${process.env.API_INTERNAL_ORIGIN ?? "http://127.0.0.1:8001"}/__internal/oauth/complete`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Internal-Auth": secret },
      body: JSON.stringify({ did: session.did, handle: profile.data.handle }), cache: "no-store",
    });
    const cookie = completed.headers.get("set-cookie");
    if (!completed.ok || !cookie) throw new Error("Session completion failed");
    const response = NextResponse.redirect(new URL("/", publicUrl()));
    response.cookies.delete(START_COOKIE);
    response.headers.append("Set-Cookie", cookie);
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    if (sessionDid) forgetOAuthSession(sessionDid);
    return failed;
  }
}
