# web

Next.js（App Router）+ TypeScript（strict）+ Tailwind CSS。

- `src/types/clue.ts`：手がかりの形式（TypeScript 側の正。`api/src/tkb_api/schemas.py` と同時に変更する）
- `src/lib/api.ts`：`POST /api/detect` を呼ぶ。写真は本文そのものとして送る
- `src/components/hide-and-seek/`：写真を選ぶ → 探す → 結果表示の流れ
- `src/components/result-frame/`：写真の上に手がかりの位置を重ね、一覧を並べる
- フォントは `@fontsource` で自前配信する（実行時に Google Fonts へ接続しない）

```bash
pnpm dev        # http://localhost:3000（api は make dev-api で別に起動）
pnpm test       # vitest（カバレッジ 80% 以上）
pnpm lint && pnpm typecheck
```

`AGENTS.md` は `next dev` が自動で書き足すファイル。消してもまた作られるのでコミットしておく。
