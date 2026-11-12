// 偽の X API の E2E の出力（api と画面のサーバーのログを含む）に、
// X OAuth のコールバックのクエリ（code・state）が残っていないことを確かめる。
// 使い方: node scripts/check-x-e2e-log.mjs <ログのファイル>
import { readFileSync } from "node:fs";

const file = process.argv[2];
if (!file) throw new Error("ログのファイルを指定してください");
const lines = readFileSync(file, "utf8").split("\n");
const callbackLines = lines.filter((line) => line.includes("/api/x/callback"));
const leaked = callbackLines.filter((line) => /[?&](code|state)=/.test(line));
if (callbackLines.length === 0) {
  throw new Error("ログに /api/x/callback のアクセスがありません（サーバーの出力が取れていない）");
}
if (leaked.length > 0) {
  throw new Error(`コールバックのクエリがログに ${leaked.length} 行残っています`);
}
process.stdout.write(`/api/x/callback のログ ${callbackLines.length} 行にクエリはありませんでした\n`);
