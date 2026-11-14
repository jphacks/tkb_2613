import { THREADS_DIAGNOSE_STAGES, type ThreadsDiagnoseStage, type ThreadsErrorKey } from "@/lib/threads-i18n";

/** GET /api/threads/progress の応答。数は実際に読み終えた投稿だけで、見込みの割合は含まない */
export interface ThreadsProgress {
  readonly state: "idle" | "running" | "done" | "failed";
  readonly stage: ThreadsDiagnoseStage | null;
  readonly elapsed_ms: number | null;
  readonly posts_total: number | null;
  readonly posts_read: number;
  readonly read_post_ids: readonly string[];
  /** このセッションで実際に行う段階（モックでは投稿の取得などを行わない） */
  readonly stages: readonly ThreadsDiagnoseStage[];
  readonly error: "model_unavailable" | "failed" | null;
}

const STATES: readonly string[] = ["idle", "running", "done", "failed"];
const ERRORS: readonly unknown[] = ["model_unavailable", "failed", null];

function isStage(value: unknown): value is ThreadsDiagnoseStage {
  return (THREADS_DIAGNOSE_STAGES as readonly unknown[]).includes(value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

export function isThreadsProgress(value: unknown): value is ThreadsProgress {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  return typeof v.state === "string" && STATES.includes(v.state) &&
    (v.stage === null || isStage(v.stage)) &&
    (v.elapsed_ms === null || isCount(v.elapsed_ms)) &&
    (v.posts_total === null || isCount(v.posts_total)) &&
    isCount(v.posts_read) &&
    Array.isArray(v.read_post_ids) && v.read_post_ids.every((id) => typeof id === "string") &&
    Array.isArray(v.stages) && v.stages.every(isStage) &&
    ERRORS.includes(v.error);
}

/** 失敗のコードを画面のエラーに変える。GPU（モデル）が止まっているときは専用の文言にする */
export function progressErrorKey(error: ThreadsProgress["error"]): ThreadsErrorKey {
  return error === "model_unavailable" ? "modelUnavailable" : "failed";
}

/** 経過時間を「分:秒」（1時間を超えたら「時:分:秒」）にする */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const seconds = String(total % 60).padStart(2, "0");
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
}
