# SSRF・取得先/送信先ガード（カテゴリ9）

[← 目次](README.md)

- 対象: みーつけた api（FastAPI） / commit df27bac
- 実施日: 2026-11-06 / ローカル実施・破壊的操作なし
- 環境: `PostImage` スキーマ検証と `ensure_team_endpoint` の関数単体検証

## 判定

画像取得先ガードは合格（許可リスト方式で堅い）。モデル送信先ガードに **Medium 指摘1点**（拒否リスト方式）。

## 結果

画像取得先（`PostImage` の URL 検証）：

| テスト | URL | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 正規 | `https://cdn.bsky.app/img/x.jpg` | 受理 | 受理 | 合格 |
| 別ホスト | `https://evil.example/x.jpg` | 拒否 | 拒否 | 合格 |
| メタデータIP | `http://169.254.169.254/` | 拒否 | 拒否 | 合格 |
| localhost | `http://localhost/x` | 拒否 | 拒否 | 合格 |
| userinfo偽装 | `https://cdn.bsky.app@evil.example/x` | 拒否 | 拒否 | 合格 |

モデル送信先（`ensure_team_endpoint`）：

| テスト | URL | 期待 | 実測 | 判定 |
|---|---|---|---|---|
| 既知の第三者AI | `https://api.openai.com/v1` | 拒否 | 拒否 | 合格 |
| 既知の第三者AI | `https://x.googleapis.com` | 拒否 | 拒否 | 合格 |
| 任意の第三者 | `https://evil.example/v1` | 拒否が望ましい | **許可** | 🟠 Medium |
| メタデータIP | `http://169.254.169.254/` | 拒否が望ましい | **許可** | 🟠 Medium |
| 非http(s) | `ftp://x/` | 拒否 | 拒否 | 合格 |

## 所見

- 画像取得（`fetch_images`）は `scheme=="https"` かつ `hostname=="cdn.bsky.app"` だけを許可。メタデータIP・localhost・`@`偽装・別ホストを拒否。`follow_redirects=False` でリダイレクト追従もなし。**許可リスト方式で堅い**。

## 🟠 Medium 指摘 — `ensure_team_endpoint` が拒否リスト方式

[detect/src/tkb_detect/guard.py](../../detect/src/tkb_detect/guard.py) は openai・googleapis・x.ai など既知の第三者AIホストだけを拒否する。リストに無いホスト（`evil.example`、`169.254.169.254` など）は通過する。ルール「送り先はチームのサーバーだけ」を実際には担保できていない。

- **悪用可能性は低い**: 送信先 `VLM_BASE_URL` は運用者が環境変数で設定する値で、利用者入力では変えられない。利用者からのSSRFにはならず、位置づけは「運用者の設定ミスに対する安全網」。その安全網が穴だらけという設計上の指摘。
- **推奨**: 画像側（`PostImage`）と同じ**許可リスト方式**に変える。設定されたチームのホストだけ許可し、最低でもプライベート・リンクローカルIP帯（10/8・172.16/12・192.168/16・127/8・169.254/16）を拒否する。

## 関連

- モデルへのプロンプトインジェクション（実VLMでの実測）は [11-prompt-injection.md](11-prompt-injection.md) を参照。
