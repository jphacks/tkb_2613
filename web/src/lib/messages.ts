import type { ClueType } from "@/types/clue";

/**
 * 画面に出す文言は、すべてここに置く。文言を変えるときはここだけを直す。
 * テストもここを参照するので、文言を変えてもテストは直さなくてよい。
 * 数が入る文言は関数にする。
 *
 * ここに置かないもの：
 * - types/profile.ts の項目名（Python の common/src/tkb_common/schemas.py と対の表で、点数と一緒に持つため）
 * - 開発者向けのエラー（SessionProvider の使い方の誤りなど。利用者の画面には出ない）
 * - api が作って送ってくる文言（手がかりの取り出しに失敗した理由、推理の補足 note）
 */

/** 手がかりの種類の表示名 */
const CLUE_TYPE_LABELS: Readonly<Record<ClueType, string>> = {
  station_sign: "駅名標",
  rail_view: "ホーム・線路",
  reflection: "映り込み",
  shop: "店名・看板",
  landmark: "目印になる建物",
  address_text: "住所表示",
  postal_code: "郵便番号",
  phone: "電話番号",
  plate: "ナンバープレート",
  uniform: "制服・作業着",
  face: "顔",
  key: "鍵",
  code: "バーコード・QR コード",
  name_text: "名前",
  org_text: "会社・学校・団体",
  handle_text: "SNS のユーザー名",
  place_text: "地名・駅名・店名",
  age_text: "年齢・誕生日",
  routine_text: "生活の決まり",
  relation_text: "家族・同居人",
};

/** engine の試作の項目名（attribute）の表示名。16項目への対応づけまでのつなぎ。ないものは attribute をそのまま出す */
const ATTRIBUTE_LABELS: Readonly<Record<string, string>> = {
  station: "最寄り駅",
  home_area: "住んでいる町",
  active_time: "よくいる時間",
  routine: "決まった外出",
  line: "使っている路線",
  full_name: "名前",
  given_name_or_nickname: "呼び名",
  age: "年齢",
  school: "学校",
  birthday: "生年月日",
};

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
  diagnose: {
    heading: "診断",
    start: "診断する",
    connecting: "特定班AIが投稿を取りに行っています…",
    reading: (posts: number) => `${posts} 件の投稿を調べています…`,
    searching: (searched: number, posts: number) => `手がかりを探しています…（${searched} / ${posts} 件）`,
    done: (posts: number) => `${posts} 件の投稿を読みました`,
    failed: "診断できませんでした",
    postsLabel: "読んだ投稿",
  },
  /** 診断の間の画面 */
  loading: {
    /** 診断を始めた直後に出す鬼の呼びかけ */
    calling: "もういいかい？",
    progressLabel: "手がかりを探し終えた投稿",
    feedLabel: "特定班AIの実況",
    /** 実況に流す、読んだ投稿の本文 */
    reading: (text: string) => `読んだ：「${text}」`,
    photoPost: (photos: number) => `写真 ${photos} 枚の投稿`,
    /** label は手がかりの種類の表示名 */
    found: (label: string) => `${label}を見つけた`,
    /** 数秒ごとに切り替える一言。煽らず、いま実際にしていることだけを書く */
    lines: [
      "写真の隅まで見ています",
      "写真に写った文字を読んでいます",
      "窓の外の景色も見ています",
      "投稿した時刻を並べています",
      "何気ない一言も読んでいます",
      "別々の投稿をつないでいます",
      "1件ずつは無害でも、組み合わせて見ています",
    ],
  },
  post: {
    /** 説明文（alt）のない写真の名前。index は 0 から */
    photoName: (index: number) => `写真 ${index + 1}`,
    photoUnavailable: (name: string) => `${name}（表示できません）`,
    cluesLabel: "この投稿の手がかり",
  },
  clues: {
    typeLabels: CLUE_TYPE_LABELS,
    none: "手がかりは見つかりませんでした",
    /** reason は api が送ってくる失敗の理由 */
    failed: (reason: string) => `手がかりを探せませんでした（${reason}）`,
  },
  board: {
    heading: "捜査ボード",
    /** 推理の結論が出た瞬間の鬼のかけ声。アプリ名と同じ言葉だが、名前を変えてもこちらは変えない */
    found: "みーつけた",
    /** 推定に使われた手がかりを留めた列 */
    evidence: "証拠",
    conclusionsLabel: "推定できたこと",
    inferred: "推定",
    attributeLabels: ATTRIBUTE_LABELS,
    reasons: (count: number) => `根拠（${count} 件）`,
    reasonsLabel: "根拠の手がかり",
    empty: "投稿からは、あなたについて推定できることは見つかりませんでした",
    /** 消したらどうなるかで、推定できなくなった項目 */
    unknown: "不明",
    unknownNote: "選んだ投稿を消すと、ここは推定できなくなります",
  },
  reveal: {
    /** 診断のあと、画面の一番上に大きく出す見出し */
    heading: "ぜんぶ、みえてる",
    conclusionsLabel: "あなたについて推定できたこと",
    evidenceLabel: "見つかった証拠",
    /** 推定の根拠になった証拠に付ける印 */
    used: "決め手",
    photoAlt: (type: string, value: string) => `${type}「${value}」が写った箇所`,
    fromText: "本文から",
    count: (clues: number, posts: number) => `${posts} 件の投稿から、手がかりを ${clues} 個`,
  },
  identity: {
    label: "推定した身元",
    /** 写真の枠。顔は出さず、人影を出す */
    silhouette: "顔は写していなくても",
    /** 写真の枠に、本人の投稿に写っていた顔を出したとき。本人とは限らない */
    faceCaption: "写っていた顔（本人とは限りません）",
    faceAlt: "投稿の写真に写っていた顔",
    nameLabel: "名前",
    nameUnknown: "名前は不明",
    cluesFound: "見つかった手がかり",
    cluesUnit: "個",
    inferred: "推定",
  },
  risky: {
    heading: "まーだだよ",
    lead: "この投稿を消すと、推定が崩れます。選んで「消したらどうなる」を押すと、消したあとの捜査ボードを見られます（ここではまだ消しません）。納得したら「Bluesky から消す」で実際に消せます。",
    listLabel: "危ない投稿",
    breaks: (labels: string) => `消すと不明に：${labels}`,
    breaksNothing: "これだけでは崩れません",
    noText: "（本文なし）",
    photos: (count: number) => `写真 ${count} 枚`,
    simulate: "消したらどうなる",
    simulating: "推理し直しています…",
    reset: "元に戻す",
    result: (deleted: number, broken: number) =>
      broken > 0 ? `${deleted} 件消すと、${broken} つの項目が不明になります` : `${deleted} 件消しても、推定は崩れません`,
    safe: "逃げ切り：最寄り駅・よくいる時間・決まった外出はもう推定できません",
    none: "推定を崩せる投稿は見つかりませんでした",
    failed: "推理し直せませんでした",
    /** ここから下は、Bluesky から実際に消すとき */
    deleteForReal: "Bluesky から消す",
    confirmHeading: "本当に消しますか？",
    confirmLead: (count: number) =>
      `Bluesky から次の ${count} 件の投稿を削除します。写真も本文も、いいねや返信もいっしょに消え、元に戻せません。`,
    confirmListLabel: "消す投稿",
    confirm: "削除する",
    cancel: "やめる",
    deleting: "Bluesky から消しています…",
    deleteFailed: "消せませんでした",
  },
  /** 実際に消したあと */
  escaped: {
    heading: "もういいよ",
    deleted: (count: number) => `${count} 件の投稿を Bluesky から消しました`,
    failed: (count: number) => `${count} 件は消せませんでした。Bluesky のアプリから直接消してください`,
    rediagnose: "もう一度「診断する」を押すと、残った投稿で最初から調べ直します",
  },
  hideAndSeek: {
    pickerLabel: "写真の選択",
    pick: "写真を選ぶ",
    search: "みーつけた",
    searching: "さがしています…",
    found: "みーつけた",
    failed: "うまく探せませんでした",
    previewAlt: "選んだ写真のプレビュー",
    photoAlt: "選んだ写真",
    cluesLabel: "見つかった手がかり",
  },
  errors: {
    unsupportedType: "JPEG・PNG・WebP・HEIC の写真を選んでください",
    tooLarge: (megabytes: number) => `写真が大きすぎます（${megabytes}MB まで）`,
    network: "サーバーに接続できませんでした",
    server: (status: number) => `サーバーでエラーが起きました（${status}）`,
    invalidResponse: "サーバーの応答を読み取れませんでした",
    wrongCredentials: "ハンドル名かパスワードが違います",
    sessionExpired: "ログインし直してください",
    diagnoseInterrupted: "診断の途中で接続が切れました",
    diagnoseFirst: "先に診断してください",
  },
} as const;
