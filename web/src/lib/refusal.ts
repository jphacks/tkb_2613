import { messages } from "@/lib/messages";

/**
 * api が理由のコードつきで断ったときの応答 {"detail": {"code", "message", ...}}。
 * api/src/tkb_api/errors.py と docs/api-sse-contract.md と同時に変更すること。
 */
export type RefusalCode =
  | "daily_limit"
  | "busy"
  | "already_running"
  | "closed"
  | "model_unavailable"
  | "bluesky_busy"
  | "share_disabled"
  | "diagnosis_required";

export interface Refusal {
  readonly code: RefusalCode;
  /** closed：次の公開の開始時刻（時差つき ISO 8601）。null なら公開は終わった */
  readonly next_open?: string | null;
  /** daily_limit：1日の上限回数 */
  readonly limit?: number;
}

const CODES: readonly string[] = [
  "daily_limit",
  "busy",
  "already_running",
  "closed",
  "model_unavailable",
  "bluesky_busy",
  "share_disabled",
  "diagnosis_required",
] satisfies readonly RefusalCode[];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 応答の本文が理由のコードつきの断りなら、その中身を返す。違う形なら null */
export function toRefusal(body: unknown): Refusal | null {
  if (!isRecord(body) || !isRecord(body.detail)) return null;
  const { code, next_open: nextOpen, limit } = body.detail;
  if (typeof code !== "string" || !CODES.includes(code)) return null;
  return {
    code: code as RefusalCode,
    next_open: typeof nextOpen === "string" ? nextOpen : null,
    limit: typeof limit === "number" && Number.isInteger(limit) && limit > 0 ? limit : undefined,
  };
}

/** 応答を読み、理由のコードつきの断りなら返す（本文が JSON でなければ null） */
export async function readRefusal(res: Response): Promise<Refusal | null> {
  const body: unknown = await res.json().catch(() => undefined);
  return toRefusal(body);
}

/** 日本時間の「11月16日の20:00」。読めない時刻なら null */
export function formatOpening(iso: string): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("month")}月${part("day")}日の${part("hour")}:${part("minute")}`;
}

/** 断りの理由を画面の文言にする */
export function refusalMessage(refusal: Refusal): string {
  const e = messages.errors;
  switch (refusal.code) {
    case "daily_limit":
      return e.dailyLimit(refusal.limit);
    case "busy":
      return e.busy;
    case "already_running":
      return e.alreadyRunning;
    case "closed": {
      const opensAt = refusal.next_open ? formatOpening(refusal.next_open) : null;
      return opensAt ? e.closed(opensAt) : e.ended;
    }
    case "model_unavailable":
      return e.modelUnavailable;
    case "bluesky_busy":
      return e.blueskyBusy;
    case "share_disabled":
      return e.shareDisabled;
    case "diagnosis_required":
      return e.diagnoseFirst;
  }
}
