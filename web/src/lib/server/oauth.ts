import { randomBytes, timingSafeEqual } from "node:crypto";

import {
  NodeOAuthClient,
  buildAtprotoLoopbackClientMetadata,
  requestLocalLock,
  type NodeSavedSession,
  type NodeSavedState,
  type OAuthClientMetadataInput,
} from "@atproto/oauth-client-node";

export const OAUTH_SCOPE = "atproto repo:app.bsky.feed.post?action=delete";
export const OAUTH_TTL_SECONDS = 30 * 60;
export const START_COOKIE = "tkb_oauth_start";

const memory = globalThis as typeof globalThis & {
  tkbOAuthStates?: Map<string, { value: NodeSavedState; expires: number }>;
  tkbOAuthSessions?: Map<string, { value: NodeSavedSession; expires: number }>;
  tkbOAuthExpiries?: Map<string, number>;
  tkbOAuthClient?: NodeOAuthClient;
};
memory.tkbOAuthStates ??= new Map();
memory.tkbOAuthSessions ??= new Map();
memory.tkbOAuthExpiries ??= new Map();

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
          if (item && item.expires > Date.now()) return item.value;
          memory.tkbOAuthSessions?.delete(key);
          memory.tkbOAuthExpiries?.delete(key);
          return undefined;
        },
        async set(key, value) {
          let expires = memory.tkbOAuthExpiries?.get(key);
          if (!expires || expires <= Date.now()) {
            expires = Date.now() + OAUTH_TTL_SECONDS * 1000;
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

export function resetOAuthExpiry(did: string): void {
  const expires = Date.now() + OAUTH_TTL_SECONDS * 1000;
  memory.tkbOAuthExpiries?.set(did, expires);
  const item = memory.tkbOAuthSessions?.get(did);
  if (item) memory.tkbOAuthSessions?.set(did, { ...item, expires });
}

export function pendingStateMatches(oauthState: string | null, browserState: string | undefined): boolean {
  if (!oauthState || !browserState) return false;
  const item = memory.tkbOAuthStates?.get(oauthState);
  const value = item?.value.appState;
  if (!item || item.expires <= Date.now() || typeof value !== "string" || value.length !== browserState.length) return false;
  return timingSafeEqual(Buffer.from(value), Buffer.from(browserState));
}

export function validInternalSecret(request: Request): boolean {
  const expected = process.env.INTERNAL_AUTH_SECRET;
  const actual = request.headers.get("x-internal-auth");
  if (!expected || !actual || expected.length !== actual.length) return false;
  return timingSafeEqual(Buffer.from(expected), Buffer.from(actual));
}
