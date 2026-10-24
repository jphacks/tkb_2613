/**
 * 画面に出す文言。文言を変えるときはここだけを直す。
 * テストもここを参照するので、文言を変えてもテストは直さなくてよい。
 * 今はホームとログイン画面だけ。ほかの画面も、作業が落ち着いたらここへ移す。
 */
export const messages = {
  app: {
    name: "みーつけた",
    description: "Bluesky の自分の投稿の組み合わせから何がわかるかを見せ、最小限の削除で逃げ切るかくれんぼ",
  },
  home: {
    tagline: "あなたの投稿、組み合わせると",
    lead: "Bluesky の自分の投稿を特定班AIが読み、1件ずつは無害な投稿の組み合わせから、何がわかるかを見せます。調べられるのはログインした本人のアカウントだけです。",
  },
  login: {
    formLabel: "Bluesky にログイン",
    heading: "Bluesky のアカウントでログイン",
    handle: "ハンドル名",
    handlePlaceholder: "alice.bsky.social",
    password: "パスワード",
    passwordHint:
      "Bluesky のパスワードでログインできます。パスワードは保存しません。アプリパスワード（「設定 → プライバシーとセキュリティ → アプリパスワード」で作れます）を使うと、あとで取り消せるので、より安心です。",
    submit: "ログイン",
    checking: "ログイン状態を確認しています…",
    pending: "Bluesky にログインしています…",
    failed: "ログインできませんでした",
    loggedIn: "ログイン中",
    logout: "ログアウト",
  },
} as const;
