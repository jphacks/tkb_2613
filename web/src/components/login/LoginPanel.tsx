"use client";

import Link from "next/link";
import { useActionState, useEffect, useState } from "react";

import { BlueskyLogo } from "@/components/brand/BlueskyLogo";
import { useSession } from "@/components/session/SessionProvider";
import { ApiError, getFeatures } from "@/lib/api";
import { REVOKE_APP_PASSWORD } from "@/lib/legal";
import { messages } from "@/lib/messages";
import { normalizeHandle } from "@/types/session";

const t = messages.login;

/** web/src/app/auth/callback/route.ts が失敗時に付けるクエリ */
const AUTH_ERROR_PARAM = "auth_error";

function hasAuthError(): boolean {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).has(AUTH_ERROR_PARAM);
}

interface LoginFormState {
  error: string | null;
  /** 失敗したときに、ハンドル名を入力欄に戻すため */
  handle: string;
}

const INITIAL_STATE: LoginFormState = { error: null, handle: "" };

/**
 * ログイン画面。診断できるのはログインした本人のアカウントだけ。
 * 送信が終わると React がフォームを空に戻すので、パスワードは入力欄に残らない。
 */
export function LoginPanel() {
  const { state: session, login, logout } = useSession();
  const [authMode, setAuthMode] = useState<"oauth" | "app_password" | null>(null);
  const [oauthPending, setOauthPending] = useState(false);
  // OAuth の戻り（auth/callback）が失敗すると /?auth_error=1 に戻るので、その文言から始める
  const [oauthError, setOauthError] = useState<string | null>(() => (hasAuthError() ? t.oauthFailed : null));

  useEffect(() => {
    const controller = new AbortController();
    getFeatures({ signal: controller.signal }).then((features) => {
      if (!controller.signal.aborted) setAuthMode(features.auth_mode ?? "app_password");
    });
    return () => controller.abort();
  }, []);

  // 再読み込みで同じ文言を繰り返さないよう、auth_error をクエリから消す
  useEffect(() => {
    if (!hasAuthError()) return;
    const url = new URL(window.location.href);
    url.searchParams.delete(AUTH_ERROR_PARAM);
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }, []);

  async function startOAuth(handle: string) {
    setOauthPending(true);
    setOauthError(null);
    try {
      const response = await fetch("/auth/start", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle }), credentials: "same-origin",
      });
      const body: unknown = await response.json();
      if (!response.ok || typeof body !== "object" || body === null || !("redirectUrl" in body) || typeof body.redirectUrl !== "string") {
        throw new Error("Bluesky との接続を開始できませんでした");
      }
      window.location.assign(body.redirectUrl);
    } catch {
      setOauthError("Bluesky との接続を開始できませんでした");
      setOauthPending(false);
    }
  }

  const [form, formAction, isPending] = useActionState(
    async (_prev: LoginFormState, formData: FormData): Promise<LoginFormState> => {
      const handle = normalizeHandle(String(formData.get("handle") ?? ""));
      try {
        await login(handle, String(formData.get("password") ?? ""));
        return INITIAL_STATE;
      } catch (err) {
        const error = err instanceof ApiError ? err.message : t.failed;
        return { error, handle };
      }
    },
    INITIAL_STATE,
  );

  if (session.status === "checking" || authMode === null) {
    return (
      <p role="status" className="text-ink/70">
        {t.checking}
      </p>
    );
  }

  if (session.status === "authenticated") {
    return (
      <section aria-label={t.loggedIn} className="flex flex-wrap items-center gap-4">
        <p className="flex items-center gap-2">
          <BlueskyLogo className="size-5" />
          <span className="text-sm text-ink/60">{t.loggedIn}</span>
          <span className="font-bold">@{session.session.handle}</span>
        </p>
        <button
          type="button"
          onClick={logout}
          className="rounded-sm border-2 border-ink px-4 py-2 text-sm font-bold transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-seeker"
        >
          {t.logout}
        </button>
        {authMode === "app_password" && <p className="basis-full text-sm text-ink/60">{REVOKE_APP_PASSWORD}</p>}
      </section>
    );
  }

  return (
    <form action={authMode === "oauth" ? (formData) => { void startOAuth(normalizeHandle(String(formData.get("handle") ?? ""))); } : formAction} aria-label={t.formLabel} className="max-w-md">
      <p className="mb-5 flex items-center gap-2.5 font-bold">
        <BlueskyLogo className="size-7" />
        {t.heading}
      </p>
      <fieldset disabled={isPending || oauthPending} aria-busy={isPending || oauthPending} className="space-y-5 disabled:opacity-60">
        <label className="block space-y-1.5">
          <span className="block font-bold">{t.handle}</span>
          <input
            name="handle"
            required
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            placeholder={t.handlePlaceholder}
            defaultValue={form.handle}
            className="w-full rounded-sm border-2 border-ink bg-paper px-3 py-2 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-seeker"
          />
        </label>

        {authMode === "app_password" && <div className="space-y-1.5">
          <label htmlFor="password" className="block font-bold">
            {t.password}
          </label>
          <input
            id="password"
            aria-describedby="password-hint"
            name="password"
            type="password"
            required
            autoComplete="current-password"
            spellCheck={false}
            className="w-full rounded-sm border-2 border-ink bg-paper px-3 py-2 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-seeker"
          />
          <p id="password-hint" className="text-sm text-ink/70">
            {t.passwordHint}
          </p>
        </div>}

        <button
          type="submit"
          className="inline-flex items-center gap-3 rounded-sm bg-seeker px-6 py-3 font-display text-lg text-paper shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink active:translate-y-0.5 active:shadow-none disabled:cursor-not-allowed disabled:shadow-none"
        >
          {isPending && (
            <span
              aria-hidden
              className="size-4 animate-spin rounded-full border-2 border-paper border-t-transparent motion-reduce:animate-none"
            />
          )}
          {authMode === "oauth" ? "Bluesky でログイン" : t.submit}
        </button>
      </fieldset>

      {/* 画面ではボタンのくるくるで伝わるので、文字は読み上げだけにする */}
      {isPending && (
        <p role="status" className="sr-only">
          {t.pending}
        </p>
      )}
      <p className="mt-6 text-sm text-ink/70">
        {t.consentBefore}
        <Link href="/terms" className="underline underline-offset-4 hover:text-seeker">
          {t.consentTerms}
        </Link>
        {t.consentAnd}
        <Link href="/privacy" className="underline underline-offset-4 hover:text-seeker">
          {t.consentPrivacy}
        </Link>
        {t.consentAfter}
      </p>
      {authMode === "app_password" && <p className="mt-2 text-sm text-ink/70">{REVOKE_APP_PASSWORD}</p>}

      {!isPending && form.error && (
        <p role="alert" className="mt-4 border-l-4 border-seeker bg-seeker/10 px-4 py-3">
          {form.error}
        </p>
      )}
      {oauthError && <p role="alert" className="mt-4 border-l-4 border-seeker bg-seeker/10 px-4 py-3">{oauthError}</p>}
    </form>
  );
}
