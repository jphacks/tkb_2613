import { NextResponse } from "next/server";

import { forgetOAuthSession, validInternalSecret } from "@/lib/server/oauth";

export async function POST(request: Request) {
  if (!validInternalSecret(request)) return new NextResponse(null, { status: 403 });
  const body: unknown = await request.json().catch(() => null);
  if (typeof body !== "object" || body === null || !("did" in body) || typeof body.did !== "string") {
    return new NextResponse(null, { status: 400 });
  }
  forgetOAuthSession(body.did);
  return new NextResponse(null, { status: 204 });
}
