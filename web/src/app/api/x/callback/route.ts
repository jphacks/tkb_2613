import { connection, NextRequest, NextResponse } from "next/server";

// X OAuth のコールバックだけは rewrites を通さずにここで api へ中継する。
// rewrites は api に届かないとき「Failed to proxy <URL>」とクエリ（code・state）ごとログに出すため。
// ここでは URL もエラーの中身も記録しない。

const FORWARDED_RESPONSE_HEADERS = ["location", "content-type", "retry-after"] as const;

function apiOrigin(): string {
  const origin = process.env.API_INTERNAL_ORIGIN ?? process.env.API_ORIGIN ?? "http://127.0.0.1:8001";
  return origin.replace(/\/+$/, "");
}

function unavailable(): NextResponse {
  return NextResponse.json(
    { detail: "X の認証を完了できませんでした。時間をおいてもう一度お試しください。" },
    { status: 502, headers: { "Cache-Control": "no-store" } },
  );
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  await connection();
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  let upstream: Response;
  try {
    upstream = await fetch(`${apiOrigin()}/api/x/callback${request.nextUrl.search}`, {
      method: "GET",
      headers,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return unavailable();
  }
  const response = new NextResponse(await upstream.arrayBuffer(), { status: upstream.status });
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) response.headers.set(name, value);
  }
  for (const value of upstream.headers.getSetCookie()) response.headers.append("Set-Cookie", value);
  response.headers.set("Cache-Control", "no-store");
  return response;
}
