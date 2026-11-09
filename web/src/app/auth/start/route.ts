import { NextRequest, NextResponse } from "next/server";

import { authMode, getOAuthClient, newState, OAUTH_SCOPE, START_COOKIE } from "@/lib/server/oauth";

export async function POST(request: NextRequest) {
  if (authMode() !== "oauth") return new NextResponse(null, { status: 404 });
  let handle: unknown;
  try {
    ({ handle } = await request.json());
  } catch {
    return NextResponse.json({ error: "ハンドル名を入力してください" }, { status: 400 });
  }
  if (typeof handle !== "string" || !/^[a-zA-Z0-9.-]{1,253}$/.test(handle)) {
    return NextResponse.json({ error: "ハンドル名を確認してください" }, { status: 400 });
  }
  try {
    const state = newState();
    const url = await getOAuthClient().authorize(handle, { scope: OAUTH_SCOPE, state });
    const response = NextResponse.json({ redirectUrl: url.toString() }, { headers: { "Cache-Control": "no-store" } });
    response.cookies.set(START_COOKIE, state, {
      httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/auth", maxAge: 300,
    });
    return response;
  } catch {
    return NextResponse.json({ error: "Bluesky への接続を開始できませんでした" }, { status: 502 });
  }
}
