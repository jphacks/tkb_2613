import { createHash, randomBytes, timingSafeEqual } from "node:crypto";

import {
  NodeOAuthClient,
  buildAtprotoLoopbackClientMetadata,
  requestLocalLock,
  type NodeSavedSession,
  type NodeSavedState,
  type OAuthClientMetadataInput,
} from "@atproto/oauth-client-node";

export const OAUTH_SCOPE = "atproto repo:app.bsky.feed.post?action=delete";
const DEFAULT_SESSION_TTL_MINUTES = 30;

/** api と同じ SESSION_TTL_MINUTES（未設定・不正な値は30分）で OAuth のセッションを持つ秒数 */
export function oauthTtlSeconds(): number {
  const minutes = Number(process.env.SESSION_TTL_MINUTES);
  const valid = Number.isInteger(minutes) && minutes > 0;
  return (valid ? minutes : DEFAULT_SESSION_TTL_MINUTES) * 60;
}
export const START_COOKIE = "tkb_oauth_start";

const memory = globalThis as typeof globalThis & {
  tkbOAuthStates?: Map<string, { value: NodeSavedState; expires: number }>;
  tkbOAuthSessions?: Map<string, { value: NodeSavedSession; expires: number }>;
  tkbOAuthExpiries?: Map<string, number>;
  /** 失効の処理中の DID。この間だけ、期限切れのトークンを SDK の revoke に渡せる */
  tkbOAuthRevoking?: Set<string>;
  tkbOAuthClient?: NodeOAuthClient;
};
memory.tkbOAuthStates ??= new Map();
memory.tkbOAuthSessions ??= new Map();
memory.tkbOAuthExpiries ??= new Map();
memory.tkbOAuthRevoking ??= new Set();

export function authMode(): "oauth" | "app_password" {
  return process.env.AUTH_MODE === "oauth" ? "oauth" : "app_password";
}

export function publicUrl(): string {
  const value = process.env.PUBLIC_URL ?? "http://127.0.0.1:3000";
  const url = new URL(value);
  if (url.protocol !== "https:" && url.hostname !== "127.0.0.1") {
    throw new Error("PUBLIC_URL must be HTTPS or local loopback");
  }
  return url.origin;
}

export function newState(): string {
  return randomBytes(32).toString("base64url");
}

export function clientMetadata(): OAuthClientMetadataInput {
  const origin = publicUrl();
  if (origin === "http://127.0.0.1:3000") {
    return buildAtprotoLoopbackClientMetadata({
      scope: OAUTH_SCOPE,
      redirect_uris: [`${origin}/auth/callback`],
    });
  }
  return {
    client_id: `${origin}/oauth-client-metadata.json`,
    client_name: "みーつけた",
    client_uri: origin,
    redirect_uris: [`${origin}/auth/callback`],
    grant_types: ["authorization_code", "refresh_token"],
    response_types: ["code"],
    scope: OAUTH_SCOPE,
    token_endpoint_auth_method: "none",
    dpop_bound_access_tokens: true,
  };
}

export function getOAuthClient(): NodeOAuthClient {
  if (!memory.tkbOAuthClient) {
    memory.tkbOAuthClient = new NodeOAuthClient({
      clientMetadata: clientMetadata(),
      requestLock: requestLocalLock,
      stateStore: {
        async get(key) {
          const item = memory.tkbOAuthStates?.get(key);
          if (item && item.expires > Date.now()) return item.value;
          memory.tkbOAuthStates?.delete(key);
          return undefined;
        },
        async set(key, value) {
          memory.tkbOAuthStates?.set(key, { value, expires: Date.now() + 5 * 60_000 });
        },
        async del(key) {
          memory.tkbOAuthStates?.delete(key);
        },
      },
      sessionStore: {
        async get(key) {
          const item = memory.tkbOAuthSessions?.get(key);
          if (item && (item.expires > Date.now() || memory.tkbOAuthRevoking?.has(key))) return item.value;
          memory.tkbOAuthSessions?.delete(key);
          memory.tkbOAuthExpiries?.delete(key);
          return undefined;
        },
        async set(key, value) {
          let expires = memory.tkbOAuthExpiries?.get(key);
          if (!expires || expires <= Date.now()) {
            expires = Date.now() + oauthTtlSeconds() * 1000;
            memory.tkbOAuthExpiries?.set(key, expires);
          }
          memory.tkbOAuthSessions?.set(key, { value, expires });
        },
        async del(key) {
          memory.tkbOAuthSessions?.delete(key);
          memory.tkbOAuthExpiries?.delete(key);
        },
      },
    });
  }
  return memory.tkbOAuthClient;
}

export function forgetOAuthSession(did: string): void {
  memory.tkbOAuthSessions?.delete(did);
  memory.tkbOAuthExpiries?.delete(did);
}

/**
 * Bluesky 側でトークンを失効させてから、メモリから消す。失効に失敗しても（認可サーバーに届かないなど）
 * メモリからは必ず消し、例外は出さない（ログアウトを止めないため。トークンには Bluesky 側の期限もある）。
 * DID もトークンも外に出さない。
 */
export async function revokeOAuthSession(did: string): Promise<void> {
  memory.tkbOAuthRevoking?.add(did);
  try {
    await getOAuthClient().revoke(did);
  } catch {
    // 失効できなくても、下でメモリからは消す
  } finally {
    memory.tkbOAuthRevoking?.delete(did);
    forgetOAuthSession(did);
  }
}

/** 期限が来たら、ログアウトと同じく失効させる。その前に再ログインして期限が変わっていれば何もしない */
function scheduleExpiry(did: string, expires: number): void {
  const timer = setTimeout(() => {
    if (memory.tkbOAuthExpiries?.get(did) !== expires) return;
    void revokeOAuthSession(did);
  }, Math.max(0, expires - Date.now()));
  timer.unref?.();
}

export function resetOAuthExpiry(did: string): void {
  const expires = Date.now() + oauthTtlSeconds() * 1000;
  memory.tkbOAuthExpiries?.set(did, expires);
  const item = memory.tkbOAuthSessions?.get(did);
  if (item) memory.tkbOAuthSessions?.set(did, { ...item, expires });
  scheduleExpiry(did, expires);
}

/**
 * 秘密の値を一定時間で比べる。両方を SHA-256（常に32バイト）にしてから比べるので、
 * バイト長の違う値（文字数が同じでもマルチバイト文字を含むなど）でも timingSafeEqual が例外を出さない
 */
function sameSecret(a: string, b: string): boolean {
  const digest = (value: string) => createHash("sha256").update(value, "utf8").digest();
  return timingSafeEqual(digest(a), digest(b));
}

export function pendingStateMatches(oauthState: string | null, browserState: string | undefined): boolean {
  if (!oauthState || !browserState) return false;
  const item = memory.tkbOAuthStates?.get(oauthState);
  const value = item?.value.appState;
  if (!item || item.expires <= Date.now() || typeof value !== "string") return false;
  return sameSecret(value, browserState);
}

export function validInternalSecret(request: Request): boolean {
  const expected = process.env.INTERNAL_AUTH_SECRET;
  const actual = request.headers.get("x-internal-auth");
  if (!expected || !actual) return false;
  return sameSecret(expected, actual);
}
