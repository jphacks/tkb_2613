/**
 * ログインの形式。TypeScript 側の正。
 * api/src/tkb_api/schemas.py と同時に変更すること。
 */

export interface SessionResponse {
  readonly handle: string;
  readonly did: string;
}

/** 先頭の @ と前後の空白を取り除く */
export function normalizeHandle(value: string): string {
  return value.trim().replace(/^@/, "");
}

export function isSessionResponse(value: unknown): value is SessionResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.handle === "string" &&
    v.handle.length > 0 &&
    typeof v.did === "string" &&
    v.did.startsWith("did:")
  );
}
