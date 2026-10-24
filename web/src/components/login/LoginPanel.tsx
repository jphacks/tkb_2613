"use client";

import { useActionState } from "react";

import { BlueskyLogo } from "@/components/brand/BlueskyLogo";
import { useSession } from "@/components/session/SessionProvider";
import { ApiError } from "@/lib/api";
import { messages } from "@/lib/messages";
import { normalizeHandle } from "@/types/session";

const t = messages.login;

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

  if (session.status === "checking") {
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
      </section>
    );
  }

  return (
    <form action={formAction} aria-label={t.formLabel} className="max-w-md">
      <p className="mb-5 flex items-center gap-2.5 font-bold">
        <BlueskyLogo className="size-7" />
        {t.heading}
      </p>
      <fieldset disabled={isPending} aria-busy={isPending} className="space-y-5 disabled:opacity-60">
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

        <div className="space-y-1.5">
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
        </div>

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
          {t.submit}
        </button>
      </fieldset>

      {/* 画面ではボタンのくるくるで伝わるので、文字は読み上げだけにする */}
      {isPending && (
        <p role="status" className="sr-only">
          {t.pending}
        </p>
      )}
      {!isPending && form.error && (
        <p role="alert" className="mt-4 border-l-4 border-seeker bg-seeker/10 px-4 py-3">
          {form.error}
        </p>
      )}
    </form>
  );
}
