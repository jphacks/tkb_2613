import type { PublicPatternKind } from "@/lib/threads-public-check";

/**
 * Threads 画面の表示言語。既定は日本語。英語は Meta の審査員向けで、審査後も残す。
 * 投稿本文・ユーザー名・投稿IDなど、Threads から取得したデータは翻訳しない。
 */
export type ThreadsLang = "ja" | "en";

export const THREADS_LANG_KEY = "tkb_threads_lang";

export function parseThreadsLang(value: string | null | undefined): ThreadsLang | null {
  return value === "ja" || value === "en" ? value : null;
}

/** エラーは文字列ではなくキーで持ち、表示するときに現在の言語へ翻訳する（切り替えに追従させる） */
export type ThreadsErrorKey =
  | "timeout" | "network" | "modelUnavailable" | "busy" | "forbidden" | "loginAgain" | "failed"
  | "diagnosisUnreadable" | "configUnreadable" | "connectFailed" | "sessionUnreadable"
  | "postsUnreadable" | "authorizeUnverified" | "simulationUnreadable"
  | "authDenied" | "authState" | "authFailed";

export class ThreadsError extends Error {
  constructor(readonly key: ThreadsErrorKey) {
    super(key);
    this.name = "ThreadsError";
  }
}

export interface ThreadsText {
  readonly htmlLang: string;
  readonly dateLocale: string;
  readonly langLabel: string;
  readonly back: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly intro: string;
  readonly startAria: string;
  readonly consent: string;
  readonly consentWithImage: string;
  readonly noMedia: string;
  readonly withMedia: string;
  readonly mockLogin: string;
  readonly gpuLogin: string;
  readonly liveLogin: string;
  readonly preparing: string;
  readonly accountAria: string;
  readonly logout: string;
  readonly loading: string;
  readonly reviewPosts: string;
  readonly postsAria: string;
  readonly postsFetched: (count: number) => string;
  readonly postsFetchedWithImages: (count: number) => string;
  readonly detailsSummary: string;
  readonly postId: string;
  readonly postTime: string;
  readonly media: string;
  readonly mediaValue: string;
  readonly mediaValueImage: string;
  readonly imageDiagnosis: string;
  readonly checkTitle: string;
  readonly checkIntro: string;
  readonly checkButton: string;
  readonly checkResult: string;
  readonly checkAll: string;
  readonly checkPost: (index: number, findings: string) => string;
  readonly checkNone: string;
  readonly checkNote: string;
  readonly findingLabels: Readonly<Record<PublicPatternKind, string>>;
  readonly listSeparator: string;
  readonly aiSummary: string;
  readonly aiNote: string;
  readonly aiNoteWithImages: string;
  readonly aiButton: string;
  readonly aiBusy: string;
  readonly resultFull: string;
  readonly resultRe: string;
  readonly resultCount: (posts: number, clues: number, conclusions: number) => string;
  readonly elapsed: (ms: number) => string;
  readonly postErrors: (count: number) => string;
  readonly evidenceTitle: string;
  readonly postRef: (id: string, date: string) => string;
  readonly basis: (quote: string) => string;
  readonly postsTitle: string;
  readonly postsNote: string;
  readonly exclude: string;
  readonly simulate: string;
  readonly rediagnose: string;
  readonly showAll: string;
  readonly brokenItems: (items: string) => string;
  readonly none: string;
  readonly errors: Readonly<Record<ThreadsErrorKey, string>>;
}

const ja: ThreadsText = {
  htmlLang: "ja",
  dateLocale: "ja-JP",
  langLabel: "表示言語",
  back: "みーつけたに戻る",
  eyebrow: "Threads / 本人投稿の確認",
  title: "Threadsで、みーつけた",
  intro: "自分の投稿本文と投稿時刻を取得して一覧・詳細を表示し、固定ルールによる公開情報のセルフチェックを行います。 セルフチェックはAIではありません。Threadsへの投稿・編集・削除は行いません。",
  startAria: "Threads診断の開始",
  consent: "Threadsから自分の投稿ID・本文・投稿時刻・メディア種別を取得し、一覧・詳細表示とAIを使わない公開情報セルフチェックに利用することに同意します。取得データはログアウトまたはセッション期限で消えます。",
  consentWithImage: "Threadsから自分の投稿ID・本文・投稿時刻・メディア種別と、画像付き投稿の画像1枚目を取得し、一覧・詳細表示、公開情報セルフチェック、任意のAI診断に利用することに同意します。取得データはログアウトまたはセッション期限で消えます。",
  noMedia: "画像・動画のURLやデータは取得しません。表示とセルフチェックには本文と投稿時刻を使います。任意のAI診断はモデル稼働時だけ利用できます。",
  withMedia: "画像付き投稿では画像1枚目を取得し、プレビューと任意のAI診断に使います。動画・複数画像・カルーセルは対象外です。",
  mockLogin: "架空のThreads投稿で試す",
  gpuLogin: "架空のThreads投稿をGPUで診断",
  liveLogin: "Threadsでログイン",
  preparing: "現在、Threads診断は公開準備中です。",
  accountAria: "Threadsアカウント",
  logout: "ログアウト",
  loading: "処理中…",
  reviewPosts: "本人投稿を確認",
  postsAria: "取得した本人投稿",
  postsFetched: (count) => `本人投稿 ${count} 件を取得しました。本文と投稿時刻だけを表示しています。この表示にAIは使っていません。`,
  postsFetchedWithImages: (count) => `本人投稿 ${count} 件を取得しました。画像付き投稿は画像1枚目も表示します。この表示にAIは使っていません。`,
  detailsSummary: "取得情報の詳細",
  postId: "投稿ID：",
  postTime: "投稿時刻：",
  media: "メディア：",
  mediaValue: "種別だけをAPIへ要求し、画像・動画のURLやデータは取得していません",
  mediaValueImage: "画像1枚目をプレビューと任意のAI診断に使用します",
  imageDiagnosis: "画像つき診断",
  checkTitle: "AIを使わない公開情報セルフチェック",
  checkIntro: "取得済み本文をこのブラウザ内の固定ルールで確認します。外部サービスやモデルへ送信せず、文字列の所有者・実在性・意味は推定しません。",
  checkButton: "公開情報をセルフチェック",
  checkResult: "チェック結果",
  checkAll: "すべての投稿で、本文と投稿時刻がThreads APIから取得できる公開情報として表示されています。",
  checkPost: (index, findings) => `投稿 ${index}：${findings}`,
  checkNone: "定型的な連絡先・URLの文字列は見つかりませんでした",
  checkNote: "この結果は固定パターンとの一致であり、個人情報かどうかを判定するAI診断ではありません。",
  findingLabels: {
    url: "URLらしき文字列",
    email: "メールアドレスらしき文字列",
    phone: "電話番号らしき文字列",
    postal: "郵便番号らしき文字列",
    handle: "@ユーザーネームらしき文字列",
  },
  listSeparator: "、",
  aiSummary: "任意機能：AI診断（モデル稼働時のみ）",
  aiNote: "この機能はMeta審査の操作には不要です。チーム管理の本文モデルが停止中は利用できません。上のセルフチェックとは別機能です。",
  aiNoteWithImages: "画像付き投稿は本文・投稿時刻・画像1枚目をチーム管理のモデルで診断します。モデル停止中は利用できません。上のセルフチェックとは別機能です。",
  aiButton: "AI診断を試す",
  aiBusy: "AI診断中…",
  resultFull: "診断結果",
  resultRe: "仮除外後の再診断",
  resultCount: (posts, clues, conclusions) => `投稿 ${posts} 件・手がかり ${clues} 件・推定 ${conclusions} 件`,
  elapsed: (ms) => `・処理 ${ms} ms`,
  postErrors: (count) => `${count} 件の投稿は読み取れなかったため、診断に含めていません。`,
  evidenceTitle: "推定の根拠投稿",
  postRef: (id, date) => `投稿 ${id}・${date}`,
  basis: (quote) => `根拠「${quote}」`,
  postsTitle: "診断した投稿",
  postsNote: "投稿を選んで仮除外できます。Threads上の投稿は削除されません。",
  exclude: "仮除外する",
  simulate: "仮除外を試す",
  rediagnose: "選択した投稿を除いて再診断",
  showAll: "全投稿の結果に戻す",
  brokenItems: (items) => `仮除外で不明になる項目：${items}`,
  none: "ありません",
  errors: {
    timeout: "通信がタイムアウトしました。時間を置いて再度お試しください。",
    network: "通信に失敗しました。接続を確認して再度お試しください。",
    modelUnavailable: "AI診断モデルは現在利用できません。本人投稿の確認と公開情報セルフチェックは引き続き利用できます。",
    busy: "Threads APIが混雑しています。時間を置いてください。",
    forbidden: "この操作は現在利用できません。Threadsの設定を確認してください。",
    loginAgain: "Threadsにログインし直してください。",
    failed: "操作に失敗しました。再度お試しください。",
    diagnosisUnreadable: "診断結果を読み取れませんでした。",
    configUnreadable: "Threads診断の設定を読み取れませんでした。",
    connectFailed: "接続に失敗しました。",
    sessionUnreadable: "接続状態を読み取れませんでした。",
    postsUnreadable: "本人投稿を読み取れませんでした。",
    authorizeUnverified: "Threadsの認証先を確認できませんでした。",
    simulationUnreadable: "仮除外の結果を読み取れませんでした。",
    authDenied: "Threadsの認可が完了しませんでした。もう一度お試しください。",
    authState: "認証を確認できませんでした。最初からログインし直してください。",
    authFailed: "Threadsの認証に失敗しました。時間を置いて再度お試しください。",
  },
};

const en: ThreadsText = {
  htmlLang: "en",
  dateLocale: "en-US",
  langLabel: "Display language",
  back: "Back to Miitsuketa",
  eyebrow: "Threads / Review your own posts",
  title: "Miitsuketa for Threads",
  intro: "This page retrieves the text and timestamps of your own Threads posts, shows them as a list with details, and runs a fixed-rule self-check for publicly visible information. The self-check is not AI. This app never publishes, edits, or deletes anything on Threads.",
  startAria: "Start the Threads review",
  consent: "I agree that this app retrieves my own Threads post IDs, text, timestamps, and media types, and uses them to show the list and details and to run the non-AI public-information self-check. The retrieved data is removed when I log out or when the session expires.",
  consentWithImage: "I agree that this app retrieves my own Threads post IDs, text, timestamps, media types, and the first image of image posts for display, the public-information self-check, and the optional AI diagnosis. The retrieved data is removed when I log out or when the session expires.",
  noMedia: "Image and video URLs and data are not retrieved. The display and the self-check use only post text and timestamps. The optional AI diagnosis is available only while the model is running.",
  withMedia: "For image posts, the first image is retrieved for preview and the optional AI diagnosis. Videos, multiple images, and carousels are not supported.",
  mockLogin: "Try with fictional Threads posts",
  gpuLogin: "Diagnose fictional Threads posts on GPU",
  liveLogin: "Log in with Threads",
  preparing: "The Threads review is being prepared for release.",
  accountAria: "Threads account",
  logout: "Log out",
  loading: "Working…",
  reviewPosts: "Review my posts",
  postsAria: "Retrieved own posts",
  postsFetched: (count) => `Retrieved ${count} of your own ${count === 1 ? "post" : "posts"}. Only the text and timestamps are shown. No AI is used for this display.`,
  postsFetchedWithImages: (count) => `Retrieved ${count} of your own ${count === 1 ? "post" : "posts"}. The first image is also shown for image posts. No AI is used for this display.`,
  detailsSummary: "Retrieved data details",
  postId: "Post ID: ",
  postTime: "Timestamp: ",
  media: "Media: ",
  mediaValue: "Only the media type is requested from the API. Image and video URLs and data are not retrieved.",
  mediaValueImage: "The first image is used for preview and the optional AI diagnosis.",
  imageDiagnosis: "Image diagnosis",
  checkTitle: "Public-information self-check (not AI)",
  checkIntro: "This check applies fixed text patterns to the retrieved text inside your browser. Nothing is sent to external services or models, and it does not infer who owns a string, whether it is real, or what it means.",
  checkButton: "Check visible public information",
  checkResult: "Check result",
  checkAll: "For every post, the text and timestamp are shown as public information retrieved from the Threads API.",
  checkPost: (index, findings) => `Post ${index}: ${findings}`,
  checkNone: "No URL or contact-like strings were found",
  checkNote: "This result is a match against fixed patterns. It is not an AI diagnosis and does not decide whether anything is personal information.",
  findingLabels: {
    url: "URL-like string",
    email: "email-address-like string",
    phone: "phone-number-like string",
    postal: "postal-code-like string",
    handle: "@username-like string",
  },
  listSeparator: ", ",
  aiSummary: "Optional: AI diagnosis (only while the model is running)",
  aiNote: "This feature is not needed to review the app. It is unavailable while the team-managed text model is stopped. It is separate from the self-check above.",
  aiNoteWithImages: "Image posts are diagnosed using the text, timestamp, and first image on the team-managed model. It is unavailable while the model is stopped and is separate from the self-check above.",
  aiButton: "Try the AI diagnosis",
  aiBusy: "AI diagnosis in progress…",
  resultFull: "Diagnosis result",
  resultRe: "Re-diagnosis after provisional exclusion",
  resultCount: (posts, clues, conclusions) => `${posts} posts · ${clues} clues · ${conclusions} inferences`,
  elapsed: (ms) => ` · processed in ${ms} ms`,
  postErrors: (count) => `${count} ${count === 1 ? "post" : "posts"} could not be read and ${count === 1 ? "was" : "were"} left out of the diagnosis.`,
  evidenceTitle: "Posts behind each inference",
  postRef: (id, date) => `Post ${id} · ${date}`,
  basis: (quote) => `Basis: “${quote}”`,
  postsTitle: "Diagnosed posts",
  postsNote: "Select posts to exclude them provisionally. Posts on Threads are not deleted.",
  exclude: "Exclude provisionally",
  simulate: "Preview the exclusion",
  rediagnose: "Re-diagnose without the selected posts",
  showAll: "Back to the result for all posts",
  brokenItems: (items) => `Items that become unknown after exclusion: ${items}`,
  none: "none",
  errors: {
    timeout: "The request timed out. Please wait a moment and try again.",
    network: "The connection failed. Please check your network and try again.",
    modelUnavailable: "The AI diagnosis model is currently unavailable. Reviewing your posts and the public-information self-check remain available.",
    busy: "The Threads API is busy. Please wait a moment.",
    forbidden: "This action is currently unavailable. Please check your Threads settings.",
    loginAgain: "Please log in with Threads again.",
    failed: "The action failed. Please try again.",
    diagnosisUnreadable: "The diagnosis result could not be read.",
    configUnreadable: "The Threads settings could not be read.",
    connectFailed: "The connection failed.",
    sessionUnreadable: "The connection status could not be read.",
    postsUnreadable: "Your posts could not be read.",
    authorizeUnverified: "The Threads authorization destination could not be verified.",
    simulationUnreadable: "The exclusion preview could not be read.",
    authDenied: "Threads authorization was not completed. Please try again.",
    authState: "The login could not be verified. Please start the login again.",
    authFailed: "Threads authentication failed. Please wait a moment and try again.",
  },
};

export const THREADS_TEXT: Readonly<Record<ThreadsLang, ThreadsText>> = { ja, en };
