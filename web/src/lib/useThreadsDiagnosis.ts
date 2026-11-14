"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ThreadsError, type ThreadsErrorKey } from "@/lib/threads-i18n";
import { isThreadsProgress, progressErrorKey, type ThreadsProgress } from "@/lib/threads-progress";

/** 診断中の表示の状態。progress はサーバーから届いた最新の進み具合 */
export interface ThreadsDiagnosing {
  /** 診断を始めた時刻（Date.now() の値）。サーバーの経過時間が届けばそれに合わせる */
  readonly startedAt: number;
  readonly progress: ThreadsProgress | null;
  /** 再読み込みや 409 のあとに、前に始めた診断の終わりを待っている */
  readonly resumed: boolean;
}

/** /api/threads/ の下を呼ぶ関数。失敗は ThreadsError で投げる */
export type ThreadsCall = (path: string, method?: "GET" | "POST") => Promise<unknown>;

interface Handlers<T> {
  readonly onResult: (result: T) => void;
  readonly onError: (key: ThreadsErrorKey) => void;
}

/** 診断中に進み具合を聞きに行く間隔 */
export const PROGRESS_POLL_MS = 1500;
/** 前の診断を待つ上限。POST /diagnose の待ち時間の上限（page.tsx の call）と同じ */
const FOLLOW_LIMIT_MS = 2_100_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Threads の診断の開始・待機・再読み込み後の復帰。
 *
 * - POST /diagnose の応答を待つ間、GET /progress で実際の段階と件数を聞く
 * - 409（同じセッションで診断中）なら、前の診断が終わるまで progress を聞いて結果を読み込む
 * - 二重クリックは state の更新より速いので、ref で同時に1つだけにする
 */
export function useThreadsDiagnosis<T>(
  call: ThreadsCall,
  parse: (value: unknown) => T,
  handlers: Handlers<T>,
) {
  const [diagnosing, setDiagnosing] = useState<ThreadsDiagnosing | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const applyProgress = useCallback((progress: ThreadsProgress) => {
    if (progress.state !== "running") return;
    setDiagnosing((current) => current && {
      ...current,
      progress,
      // 経過時間はサーバーの値に合わせる（再読み込みしても続きから数える）
      startedAt: progress.elapsed_ms === null ? current.startedAt : Date.now() - progress.elapsed_ms,
    });
  }, []);

  const deliver = useCallback(async () => {
    const result = parse(await call("diagnosis"));
    if (mounted.current) latest.current.onResult(result);
  }, [call, parse]);

  /** 診断が終わるまで progress を聞き続け、終わったら結果を読み込む。失敗なら ThreadsError を投げる */
  const waitForDiagnosis = useCallback(async (alreadyRunning = false) => {
    const deadline = Date.now() + FOLLOW_LIMIT_MS;
    let sawRunning = alreadyRunning;
    while (mounted.current) {
      const progress = await call("progress");
      if (!isThreadsProgress(progress)) throw new ThreadsError("diagnosisUnreadable");
      if (progress.state === "running") {
        if (Date.now() > deadline) throw new ThreadsError("timeout");
        sawRunning = true;
        applyProgress(progress);
        await sleep(PROGRESS_POLL_MS);
        continue;
      }
      if (progress.state === "failed") throw new ThreadsError(progressErrorKey(progress.error));
      // 走っていた診断が結果なしで終わった（中断など）なら、もう一度試せるように知らせる。
      // 一度も走っていなければ、409 の理由は診断ではない処理（投稿の取得）だった
      if (progress.state === "idle") throw new ThreadsError(sawRunning ? "diagnosisEnded" : "diagnosing");
      await deliver();
      return;
    }
  }, [call, applyProgress, deliver]);

  const track = useCallback(async (action: () => Promise<void>, resumed: boolean, progress: ThreadsProgress | null) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setDiagnosing({ startedAt: Date.now() - (progress?.elapsed_ms ?? 0), progress, resumed });
    try {
      await action();
    } catch (cause) {
      if (mounted.current) latest.current.onError(cause instanceof ThreadsError ? cause.key : "failed");
    } finally {
      inFlight.current = false;
      if (mounted.current) setDiagnosing(null);
    }
  }, []);

  /** 診断を始める。待つ間は progress を並行して聞き、409 なら前の診断の終わりを待つ */
  const start = useCallback(() => track(async () => {
    const polling = { stopped: false };
    void (async () => {
      while (!polling.stopped && mounted.current) {
        await sleep(PROGRESS_POLL_MS);
        if (polling.stopped) return;
        const progress = await call("progress").catch(() => null);
        if (!polling.stopped && isThreadsProgress(progress)) applyProgress(progress);
      }
    })();
    try {
      const result = parse(await call("diagnose", "POST"));
      if (mounted.current) latest.current.onResult(result);
    } catch (cause) {
      if (!(cause instanceof ThreadsError) || cause.key !== "diagnosing") throw cause;
      setDiagnosing((current) => current && { ...current, resumed: true });
      await waitForDiagnosis();
    } finally {
      polling.stopped = true;
    }
  }, false, null), [track, call, parse, applyProgress, waitForDiagnosis]);

  /**
   * 結果がないときに呼ぶ。再読み込みの前に始めた診断が続いていれば、終わるまで待って結果を出す。
   * 前の診断が失敗していれば、その理由（GPU 停止など）を知らせる。診断を待ったときは true を返す
   */
  const resume = useCallback(async (): Promise<boolean> => {
    const progress = await call("progress").catch(() => null);
    if (!mounted.current || !isThreadsProgress(progress)) return false;
    if (progress.state === "running") {
      // いま progress を聞いたばかりなので、次は1周期あとに聞く
      await track(async () => {
        await sleep(PROGRESS_POLL_MS);
        await waitForDiagnosis(true);
      }, true, progress);
      return true;
    }
    if (progress.state === "failed") latest.current.onError(progressErrorKey(progress.error));
    return false;
  }, [call, track, waitForDiagnosis]);

  return { diagnosing, start, resume } as const;
}
