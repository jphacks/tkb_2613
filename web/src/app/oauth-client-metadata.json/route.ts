import { connection, NextResponse } from "next/server";

import { clientMetadata } from "@/lib/server/oauth";

export async function GET() {
  await connection();
  return NextResponse.json(clientMetadata(), { headers: { "Cache-Control": "no-store" } });
}
