import { readSse } from "@/lib/sse";
import { type DetectResponse, isDetectResponse } from "@/types/clue";
import { type DiagnoseEvent, toDiagnoseEvent } from "@/types/diagnose";
import { isSessionResponse, type SessionResponse } from "@/types/session";

/** api/src/tkb_api/routes/detect.py の上限とそろえる */
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
export const ACCEPTED_IMAGE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
] as const;

const DEFAULT_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001";

export type ApiErrorKind =
  | "unsupported_type"
  | "too_large"
  | "unauthorized"
  | "network"
  | "server"
  | "invalid_response";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface DetectOptions {
  baseUrl?: string;
  signal?: AbortSignal;
}

/** 写真を api に送り、手がかりを受け取る。写真は本文そのものとして送る。 */
export async function detectClues(
  file: File,
  { baseUrl = DEFAULT_BASE_URL, signal }: DetectOptions = {},
): Promise<DetectResponse> {
  if (!(ACCEPTED_IMAGE_TYPES as readonly string[]).includes(file.type)) {
    throw new ApiError("unsupported_type", "JPEG・PNG・WebP・HEIC の写真を選んでください");
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new ApiError("too_large", "写真が大きすぎます（20MB まで）");
  }

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/detect`, {
      method: "POST",
      headers: { "Content-Type": file.type },
      body: file,
      signal,
    });
  } catch {
    throw new ApiError("network", "サーバーに接続できませんでした");
  }

  if (!res.ok) {
    throw new ApiError("server", `サーバーでエラーが起きました（${res.status}）`, res.status);
  }

  const data: unknown = await res.json().catch(() => undefined);
  if (!isDetectResponse(data)) {
    throw new ApiError("invalid_response", "サーバーの応答を読み取れませんでした");
  }
  return data;
}

interface RequestOptions {
  baseUrl?: string;
  signal?: AbortSignal;
}

/**
 * Bluesky にログインする。パスワードは api に送るだけで、ブラウザには残さない。
 * セッションは api が Cookie（セッション番号だけ）で持つ。
 */
export async function createSession(
  handle: string,
  password: string,
  { baseUrl = DEFAULT_BASE_URL, signal }: RequestOptions = {},
): Promise<SessionResponse> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ handle, password }),
      credentials: "include",
      signal,
    });
  } catch {
    throw new ApiError("network", "サーバーに接続できませんでした");
  }

  if (res.status === 401) {
    throw new ApiError("unauthorized", "ハンドル名かパスワードが違います", 401);
  }
  if (!res.ok) {
    throw new ApiError("server", `サーバーでエラーが起きました（${res.status}）`, res.status);
  }

  const data: unknown = await res.json().catch(() => undefined);
  if (!isSessionResponse(data)) {
    throw new ApiError("invalid_response", "サーバーの応答を読み取れませんでした");
  }
  return data;
}

/** 今ログインしているアカウントを返す。ログインしていなければ null。 */
export async function getSession({
  baseUrl = DEFAULT_BASE_URL,
  signal,
}: RequestOptions = {}): Promise<SessionResponse | null> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/session`, { credentials: "include", signal });
  } catch {
    throw new ApiError("network", "サーバーに接続できませんでした");
  }

  if (res.status === 401) return null;
  if (!res.ok) {
    throw new ApiError("server", `サーバーでエラーが起きました（${res.status}）`, res.status);
  }

  const data: unknown = await res.json().catch(() => undefined);
  if (!isSessionResponse(data)) {
    throw new ApiError("invalid_response", "サーバーの応答を読み取れませんでした");
  }
  return data;
}

/** ログアウトする。api 側のセッションを捨てる。 */
export async function deleteSession({ baseUrl = DEFAULT_BASE_URL, signal }: RequestOptions = {}) {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/session`, { method: "DELETE", credentials: "include", signal });
  } catch {
    throw new ApiError("network", "サーバーに接続できませんでした");
  }
  if (!res.ok) {
    throw new ApiError("server", `サーバーでエラーが起きました（${res.status}）`, res.status);
  }
}

/**
 * 診断を始め、届いたイベントを順に返す。対象はセッション（Cookie）の本人のアカウントだけで、
 * どのアカウントを調べるかは送らない。done が届く前に切れたら ApiError（network）を投げる。
 */
export async function* diagnose({
  baseUrl = DEFAULT_BASE_URL,
  signal,
}: RequestOptions = {}): AsyncGenerator<DiagnoseEvent> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/diagnose`, { method: "POST", credentials: "include", signal });
  } catch {
    throw new ApiError("network", "サーバーに接続できませんでした");
  }

  if (res.status === 401) {
    throw new ApiError("unauthorized", "ログインし直してください", 401);
  }
  if (!res.ok || !res.body) {
    throw new ApiError("server", `サーバーでエラーが起きました（${res.status}）`, res.status);
  }

  try {
    for await (const message of readSse(res.body)) {
      let event: DiagnoseEvent | null;
      try {
        event = toDiagnoseEvent(message.event, message.data);
      } catch {
        throw new ApiError("invalid_response", "サーバーの応答を読み取れませんでした");
      }
      if (!event) continue;
      yield event;
      if (event.event === "done") return;
    }
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError("network", "診断の途中で接続が切れました");
  }
  throw new ApiError("network", "診断の途中で接続が切れました");
}
