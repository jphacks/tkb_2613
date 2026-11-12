// X OAuth のコールバック（code・state）が Next.js のサーバーログに残らないことを、
// 本番ビルド（standalone）と偽の api で確かめる。X には接続しない。
// 使い方: pnpm build のあと node scripts/check-x-callback-log-redaction.mjs
// API_ORIGIN はビルド時に埋め込まれるので、既定の http://localhost:8001 で偽の api を立てる。
import { spawn } from "node:child_process";
import { cpSync, existsSync } from "node:fs";
import { createServer } from "node:http";

const WEB_PORT = 3997;
const API_PORT = 8001;
const SECRETS = ["SyntheticCode4f2a", "SyntheticState9c1d"];
const TIMEOUT_MS = 45_000;

const standalone = new URL("../.next/standalone/", import.meta.url);
if (!existsSync(new URL("server.js", standalone))) {
  throw new Error("先に pnpm build を実行してください（.next/standalone がありません）");
}
cpSync(new URL("../.next/static", import.meta.url), new URL(".next/static", standalone), { recursive: true });

function startFakeApi() {
  const server = createServer((request, response) => {
    // 偽の api は受け取った URL を記録しない
    const status = request.url?.includes("upstream-error") ? 500 : 303;
    response.writeHead(status, { Location: "/x", "Content-Length": "0" });
    response.end();
  });
  return new Promise((resolve) => server.listen(API_PORT, "::", () => resolve(server)));
}

function startWeb(output) {
  const child = spawn(process.execPath, ["server.js"], {
    cwd: standalone,
    env: { ...process.env, PORT: String(WEB_PORT), HOSTNAME: "127.0.0.1", NODE_ENV: "production" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => output.push(String(chunk)));
  child.stderr.on("data", (chunk) => output.push(String(chunk)));
  return child;
}

async function waitForWeb() {
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      await fetch(`http://127.0.0.1:${WEB_PORT}/x`, { signal: AbortSignal.timeout(5_000) });
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
  }
  throw new Error("Next.js サーバーが起動しませんでした");
}

async function hitCallback(state) {
  const url = `http://127.0.0.1:${WEB_PORT}/api/x/callback?code=${SECRETS[0]}&state=${state}`;
  try {
    const response = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(TIMEOUT_MS) });
    return response.status;
  } catch {
    return "no-response";
  }
}

const output = [];
const web = startWeb(output);
let api = null;
try {
  await waitForWeb();
  api = await startFakeApi();
  const results = {
    upstreamOk: await hitCallback(SECRETS[1]),
    upstreamError: await hitCallback(`${SECRETS[1]}-upstream-error`),
  };
  await new Promise((resolve) => api.close(resolve));
  api = null;
  results.upstreamDown = await hitCallback(SECRETS[1]);
  await new Promise((resolve) => setTimeout(resolve, 500));
  const log = output.join("");
  const leaked = SECRETS.filter((secret) => log.includes(secret));
  process.stdout.write(`callback statuses: ${JSON.stringify(results)}\n`);
  if (leaked.length > 0) {
    process.stdout.write(log.replaceAll(SECRETS[0], "<code>").replaceAll(SECRETS[1], "<state>"));
    throw new Error("Next.js のログに X のコールバックのクエリが残りました");
  }
  process.stdout.write("Next.js のログに code・state は残りませんでした\n");
} finally {
  api?.close();
  web.kill();
}
