// E2E テスト専用の偽の X API。本物の X には接続しない。127.0.0.1 だけで待ち受ける。
// 応答の形は X の公式ドキュメントの例に合わせる（値はすべて架空）。
// - GET /2/users/me：Authenticated User Quickstart の例（data.id / name / username）
//   https://docs.x.com/x-api/users/lookup/quickstart/authenticated-lookup
// - GET /2/users/:id/tweets：Pagination の例（data[] と meta.result_count / next_token / previous_token。
//   最後のページは next_token を省く）、max_results は 5〜100
//   https://docs.x.com/x-api/fundamentals/pagination / https://docs.x.com/x-api/users/get-posts
// - OAuth 2.0 PKCE：authorize は state と code を redirect_uri へ返す。認可コードは30秒で失効。
//   confidential client（Web App）は token で Basic 認証を使う。token の応答例は公式に無いので
//   RFC 6749 の形（token_type / expires_in=7200 / access_token / scope）にする
//   https://docs.x.com/resources/fundamentals/authentication/oauth-2-0/authorization-code
// このファイルは web/.dockerignore で本番イメージから除く。api 側は X_FAKE_API_BASE_URL が
// http の loopback で COOKIE_SECURE=0 のときだけ向き先を変えられる（api/src/tkb_api/config.py）。
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";

const PORT = Number(process.env.FAKE_X_PORT ?? 4010);
const CLIENT_ID = process.env.FAKE_X_CLIENT_ID ?? "fake-x-client";
const CLIENT_SECRET = process.env.FAKE_X_CLIENT_SECRET ?? "fake-x-secret";
const CODE_TTL_MS = 30_000;
const USER = { id: "1000000000000000001", name: "架空のテスター", username: "fictional_x_tester" };
const POSTS = [
  "新宿駅で待ち合わせ、土曜11時",
  "東京都新宿区の図書館へ行った",
  "土曜日は新宿駅から歩く",
  "みどり大学のオープンキャンパス",
  "今日は晴れ",
  "6件目以降は X_MAX_POSTS=5 では読まない",
  "7件目",
].map((text, index) => {
  // 新しい順に並べる（X の投稿一覧と同じ）
  const id = String(1900000000000000099n - BigInt(index));
  return {
    id,
    author_id: USER.id,
    text,
    created_at: new Date(Date.UTC(2026, 10, 10 - index, 3)).toISOString().replace(".000", ""),
    edit_history_tweet_ids: [id],
  };
});

const codes = new Map();
const tokens = new Set();
const calls = { authorize: 0, token: 0, me: 0, tweets: 0, resources: 0 };

function json(response, status, body, headers = {}) {
  response.writeHead(status, { "Content-Type": "application/json", ...headers });
  response.end(JSON.stringify(body));
}

function problem(response, status, title, detail) {
  json(response, status, { title, detail, type: "about:blank", status });
}

function sameText(a, b) {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

function bearer(request) {
  const header = request.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  return tokens.has(token);
}

function authorize(url, response) {
  const q = url.searchParams;
  const valid = q.get("response_type") === "code" && q.get("client_id") === CLIENT_ID &&
    q.get("code_challenge_method") === "S256" && q.get("code_challenge") && q.get("state") &&
    q.get("redirect_uri") && q.get("scope") === "tweet.read users.read";
  if (!valid) return problem(response, 400, "Invalid Request", "authorize のパラメーターが不正です");
  calls.authorize += 1;
  const code = randomBytes(24).toString("base64url");
  codes.set(code, {
    challenge: q.get("code_challenge"),
    redirectUri: q.get("redirect_uri"),
    expiresAt: Date.now() + CODE_TTL_MS,
  });
  const target = new URL(q.get("redirect_uri"));
  target.searchParams.set("state", q.get("state"));
  target.searchParams.set("code", code);
  response.writeHead(302, { Location: target.toString() });
  response.end();
}

async function readBody(request) {
  let body = "";
  for await (const chunk of request) body += chunk;
  return new URLSearchParams(body);
}

async function token(request, response) {
  calls.token += 1;
  const expected = `Basic ${Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString("base64")}`;
  if (!sameText(request.headers.authorization ?? "", expected)) {
    return json(response, 401, { error: "unauthorized_client", error_description: "client authentication failed" });
  }
  const form = await readBody(request);
  const pending = codes.get(form.get("code") ?? "");
  codes.delete(form.get("code") ?? "");
  const verifier = form.get("code_verifier") ?? "";
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  if (form.get("grant_type") !== "authorization_code" || !pending || pending.expiresAt < Date.now() ||
      pending.redirectUri !== form.get("redirect_uri") || !sameText(challenge, pending.challenge)) {
    return json(response, 400, { error: "invalid_request", error_description: "Value passed for the authorization code was invalid." });
  }
  const accessToken = randomBytes(32).toString("base64url");
  tokens.add(accessToken);
  json(response, 200, { token_type: "bearer", expires_in: 7200, access_token: accessToken, scope: "tweet.read users.read" });
}

function tweets(url, response) {
  const q = url.searchParams;
  const max = Number(q.get("max_results") ?? 10);
  if (!Number.isInteger(max) || max < 5 || max > 100) {
    return problem(response, 400, "Invalid Request", "The `max_results` query parameter value is not between 5 and 100");
  }
  const start = q.has("pagination_token") ? Number.parseInt(q.get("pagination_token"), 32) : 0;
  const page = POSTS.slice(start, start + max);
  const fields = new Set((q.get("post.fields") ?? "").split(",").filter(Boolean));
  const data = page.map((post) => ({
    id: post.id, text: post.text, edit_history_tweet_ids: post.edit_history_tweet_ids,
    ...(fields.has("author_id") ? { author_id: post.author_id } : {}),
    ...(fields.has("created_at") ? { created_at: post.created_at } : {}),
  }));
  calls.tweets += 1;
  calls.resources += data.length;
  const meta = { result_count: data.length };
  if (data.length > 0) Object.assign(meta, { newest_id: data[0].id, oldest_id: data.at(-1).id });
  if (start + max < POSTS.length) meta.next_token = (start + max).toString(32);
  if (start > 0) meta.previous_token = Math.max(0, start - max).toString(32);
  json(response, 200, { data, meta });
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${PORT}`);
  if (request.method === "GET" && url.pathname === "/__health") return json(response, 200, { ok: true });
  if (request.method === "GET" && url.pathname === "/__calls") return json(response, 200, calls);
  if (request.method === "GET" && url.pathname === "/i/oauth2/authorize") return authorize(url, response);
  if (request.method === "POST" && url.pathname === "/2/oauth2/token") return token(request, response);
  if (!bearer(request)) return problem(response, 401, "Unauthorized", "Unauthorized");
  if (request.method === "GET" && url.pathname === "/2/users/me") {
    calls.me += 1;
    calls.resources += 1;
    return json(response, 200, { data: USER });
  }
  if (request.method === "GET" && url.pathname === `/2/users/${USER.id}/tweets`) return tweets(url, response);
  return problem(response, 404, "Not Found Error", "Could not find the requested resource");
});

server.listen(PORT, "127.0.0.1");
