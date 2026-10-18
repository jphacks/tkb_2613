import { type DetectResponse, isDetectResponse } from "@/types/clue";

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
