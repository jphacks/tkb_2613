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
  local_item: "地域の品物",
  notice: "掲示・案内板",
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
  home_city: "住んでいる市区町村",
  home_district: "ゴミの収集地区",
  home_area: "住んでいる町",
  home_block: "住所の区画",
  active_time: "よくいる時間",
  routine: "決まった外出",
  name: "名前",
  age: "年齢",
  occupation: "仕事",
  line: "使っている路線",
  full_name: "名前",
  given_name_or_nickname: "呼び名",
  school: "学校",
  birthday: "生年月日",
  home_school_commute: "住まいと通学先のつながり",
  long_term_home_absence: "家を空ける時期",
  frequent_shop: "よく行く店",
  workplace: "勤務先・バイト先",
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
  /** ログインなしの体験デモ（/demo）。架空アカウントの結果だけを見せる */
  demo: {
    banner: "これは架空のアカウントです。実在の人物ではなく、JPHACKS 2026 のデモ用に作った投稿です。",
    heading: "体験デモ：架空のアカウントを診断すると",
    lead: "ログインせずに、特定班AIが架空の人物の投稿から何を推定するかを試せます。モデルにも Bluesky にも接続しません。",
    entry: "ログインせずに、架空のアカウントで試す",
    loading: "架空のアカウントの診断結果を読み込んでいます…",
    failed: "体験デモを読み込めませんでした。時間を置いてもう一度お試しください",
    candidatesHeading: "消したらどうなる？",
    candidatesLead: "危ない投稿を選んで、消したあとの捜査ボードを確かめられます。体験デモなので、何も消えません。",
    candidatesLabel: "削除候補の投稿",
    backHome: "Bluesky でログインして、自分の投稿を調べる",
  },
  login: {
    formLabel: "Bluesky にログイン",
    heading: "Bluesky のアカウントでログイン",
    handle: "ハンドル名",
    handlePlaceholder: "alice.bsky.social",
    password: "パスワード",
    passwordHint:
      "Bluesky の「設定 → プライバシーとセキュリティ → アプリパスワード」で作ったアプリパスワードを入力してください。ログインに使った後は保存しません。",
    submit: "ログイン",
    checking: "ログイン状態を確認しています…",
    pending: "Bluesky にログインしています…",
    failed: "ログインできませんでした",
    oauthFailed: "Bluesky でのログインに失敗しました。もう一度お試しください",
    loggedIn: "ログイン中",
    expired: "時間が切れました。もう一度ログインしてください",
    logout: "ログアウト",
    // 同意と、アプリパスワードの取り消しの案内（文章の続きは web/src/lib/legal.ts）
    consentBefore: "ログインすると、",
    consentTerms: "利用規約",
    consentAnd: "と",
    consentPrivacy: "プライバシーポリシー",
    consentAfter: "に同意したものとします。投稿の本文と写真は、チームの GPU サーバーでだけ読み、診断結果は保存しません。",
  },
  diagnose: {
    heading: "診断",
    start: "診断する",
    /** 結果のあとに出す、控えめな再診断ボタン。1日の回数を使うので、その注意を添える */
    rediagnose: "もう一度診断する",
    // 1日の上限回数と残りの回数は画面に届かないので、数字は書かない（api の DIAGNOSE_DAILY_LIMIT）
    rediagnoseNote: "1日に診断できる回数には上限があります。押すと1回分を使います。",
    connecting: "特定班AIが投稿を取りに行っています…",
    reading: (posts: number) => `${posts} 件の投稿を調べています…`,
    searching: (searched: number, posts: number) => `手がかりを探しています…（${searched} / ${posts} 件）`,
    done: (posts: number) => `${posts} 件の投稿を読みました`,
    failed: "診断できませんでした",
    deletedBadge: "削除済み",
    postsLabel: "読んだ投稿",
    /** 結果が出たあと、読んだ投稿の一覧を折りたたむときの見出し */
    postsSummary: (posts: number) => `読んだ投稿 ${posts} 件と、見つけた手がかり`,
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
    /** 投稿を横断したプロフィール推定の、根拠経路ごとの比較（折りたたみ）の見出し */
    whatIfSummary: "詳しく比べる：投稿を仮に外すと、どの推定の根拠がなくなるか",
    heading: "捜査ボード",
    /** 推理の結論が出た瞬間の鬼のかけ声。アプリ名と同じ言葉だが、名前を変えてもこちらは変えない */
    found: "みーつけた",
    /** 推定に使われた手がかりを留めた列 */
    evidence: "証拠",
    conclusionsLabel: "推定できたこと",
    inferred: "推定",
    /** 確からしさが弱い推定にだけ付ける印（数字は出さない。web/src/types/diagnose.ts の STRONG_CONFIDENCE 未満） */
    confidence: { weak: "確からしさ：弱い" },
    attributeLabels: ATTRIBUTE_LABELS,
    reasons: (count: number) => `根拠（${count} 件）`,
    reasonsLabel: "根拠の手がかり",
    /** 推理の連鎖（この投稿 → この手がかり → この推定） */
    chain: {
      summary: "推理の流れをたどる",
      label: "推理の流れ",
      post: "投稿",
      clue: "手がかり",
      conclusion: "推定",
      photo: (n: number) => `写真 ${n} 枚目`,
      noText: "（本文なし）",
    },
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
    originalPhoto: "元の投稿写真（赤枠が手がかりの位置）",
    faceObserved: "顔が写っています",
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
  /** 結果の先頭に出す、消す投稿の要約と、いまどの段階か */
  plan: {
    label: "消す投稿の要約",
    stepsLabel: "診断の流れ",
    steps: ["もういいかい", "みーつけた", "まーだだよ", "もういいよ"],
    stepNotes: ["投稿を読む", "推定を見る", "消す投稿を選ぶ", "消して逃げ切る"],
    /** labels は不明になる項目の表示名。1件ずつ消したときに崩れる項目を合わせたもの */
    breaks: (count: number, labels: string) => `この ${count} 件を消すと、少なくとも「${labels}」が不明になります`,
    direct: (count: number) => `この ${count} 件に、名前や住所などの手がかりが直接残っています`,
    none: "消すと推定が崩れる投稿は見つかりませんでした",
    show: "消す投稿を見る",
  },
  risky: {
    heading: "まーだだよ",
    lead: "名前・生年月日・住まいなどの推定と、写真や本文に残った顔・名前・住所を重く見て選びました。「消したらどうなる」で削除後の捜査ボードを確認できます。ここではまだ消しません。",
    listLabel: "危ない投稿",
    breaks: (labels: string) => `消すと不明に：${labels}`,
    breaksNothing: "単独では推定は崩れません",
    directClues: (labels: string) => `投稿に残った手がかり：${labels}`,
    noText: "（本文なし）",
    photos: (count: number) => `写真 ${count} 枚`,
    simulate: "消したらどうなる",
    simulating: "推理し直しています…",
    reset: "元に戻す",
    result: (deleted: number, broken: number) =>
      broken > 0 ? `${deleted} 件消すと、${broken} つの項目が不明になります` : `${deleted} 件消しても、推定は崩れません`,
    safe: "重要な推定と直接写った手がかりがなくなりました",
    /** 消す前後の、推定できた項目の数 */
    countHeading: "推定できた項目",
    countLabel: (before: number, after: number) => `推定できた項目は ${before} から ${after} になります`,
    none: "重要な推定や直接写った手がかりを減らせる投稿は見つかりませんでした",
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
  /** 友だちを誘う Bluesky の投稿画面（結果の最後）。本文に診断の中身は入れない */
  invite: {
    link: "友だちにも「診断してみて」と誘う",
    note: "Bluesky の投稿画面が開きます。誘い文とこのサイトの URL だけが入り、あなたの診断結果は入りません。",
    text: "Bluesky の自分の投稿から、どこまで特定されるか試せる「みーつけた」。診断してみて",
  },
  /** 実際に消したあと */
  escaped: {
    heading: "もういいよ",
    deleted: (count: number) => `${count} 件の投稿を Bluesky から消しました`,
    failed: (count: number) => `${count} 件は消せませんでした。Bluesky のアプリから直接消してください`,
    blueskyBusy: (count: number) =>
      `Bluesky が混雑しているため、${count} 件は消せませんでした。少し待ってから消し直すか、Bluesky のアプリから直接消してください`,
    rediagnose: "下の「もう一度診断する」を押すと、残った投稿で最初から調べ直します",
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
    // 診断を始められないとき（api が理由のコードつきで断ったとき。web/src/lib/refusal.ts）
    dailyLimit: (limit?: number) =>
      `${limit ? `今日の診断は ${limit} 回までです` : "今日の診断回数の上限に達しました"}。明日の 0:00（日本時間）からまた診断できます`,
    busy: "混雑しています。しばらくしてからもう一度お試しください",
    alreadyRunning: "このアカウントの別の診断が進んでいます。終わってからもう一度お試しください",
    closed: (opensAt: string) => `公開時間外です。次は${opensAt}からです`,
    ended: "公開は終了しました。ありがとうございました",
    modelUnavailable: "ただいま準備中です。しばらくしてからもう一度お試しください",
    blueskyBusy: "Bluesky が混雑しています。しばらくしてからもう一度お試しください",
    shareDisabled: "閲覧リンクの機能は、いまは使えません",
  },
} as const;
