"use client";

import { createContext, type ReactNode, use, useCallback, useEffect, useMemo, useState } from "react";

import { createSession, deleteSession, getSession } from "@/lib/api";
import type { SessionResponse } from "@/types/session";

/**
 * ログイン状態。画面に置くのはハンドル名と DID だけで、パスワードやトークンは持たない
 * （トークンは api のメモリにあり、ブラウザには HttpOnly の Cookie しかない）。
 */
export type SessionState =
  | { status: "checking" }
  | { status: "anonymous" }
  | { status: "authenticated"; session: SessionResponse };

interface SessionContextValue {
  state: SessionState;
  /** 失敗したら ApiError を投げる */
  login: (handle: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "checking" });

  // 開き直したときに、api 側のセッション（Cookie）が残っていればログイン状態に戻す
  useEffect(() => {
    const controller = new AbortController();
    getSession({ signal: controller.signal })
      .then((session) => setState(session ? { status: "authenticated", session } : { status: "anonymous" }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "anonymous" });
      });
    return () => controller.abort();
  }, []);

  const login = useCallback(async (handle: string, password: string) => {
    const session = await createSession(handle, password);
    setState({ status: "authenticated", session });
  }, []);

  const logout = useCallback(async () => {
    try {
      await deleteSession();
    } catch {
      // api 側のセッションは 30 分で消えるので、画面はそのままログアウト扱いにする
    }
    setState({ status: "anonymous" });
  }, []);

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);
  return <SessionContext value={value}>{children}</SessionContext>;
}

export function useSession(): SessionContextValue {
  const value = use(SessionContext);
  if (!value) throw new Error("useSession は SessionProvider の内側で使うこと");
  return value;
}
