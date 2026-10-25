"use client";

import { useState } from "react";

import { DiagnosePanel } from "@/components/diagnose/DiagnosePanel";
import { LoginPanel } from "@/components/login/LoginPanel";
import { useSession } from "@/components/session/SessionProvider";
import { messages } from "@/lib/messages";

/**
 * ホーム画面。ログインしているアカウントが変わったら（ログアウトも含む）、中身をまるごと作り直す。
 * 診断の結果は画面のメモリにしか置かないので、作り直せば前のアカウントの結果は残らない。
 * 実行中の診断も、DiagnosePanel が外れるときに止まる。
 */
export function HomeScreen() {
  const { state: session } = useSession();
  const account = session.status === "authenticated" ? session.session.did : "anonymous";
  return <HomeContent key={account} />;
}

/**
 * ホーム画面の中身。診断の結果が出たら、タイトルとログイン中の表示をしまい、結果だけを見せる。
 * ログアウトはページの一番下に小さく残す。
 */
function HomeContent() {
  const { state: session, logout } = useSession();
  const [revealed, setRevealed] = useState(false);
  const showResult = revealed && session.status === "authenticated";
  const name = messages.app.name;

  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:px-8 sm:py-20">
      {!showResult && (
        <>
          <header className="mb-14">
            <p className="mb-3 text-sm tracking-[0.3em] text-ink/60">{messages.home.tagline}</p>
            {/* 最後の1文字だけを点滅させる */}
            <h1 className="horror-title text-5xl leading-tight sm:text-7xl">
              {name.slice(0, -1)}
              <span className="horror-blink">{name.slice(-1)}</span>
            </h1>
            <p className="mt-5 max-w-xl text-ink/80">{messages.home.lead}</p>
          </header>
          <LoginPanel />
        </>
      )}
      {/* 結果を出している間も、ページの名前は読み上げで伝える */}
      {showResult && <h1 className="sr-only">{name}</h1>}
      <DiagnosePanel onRevealedChange={setRevealed} />
      {showResult && (
        <footer className="mt-20 border-t border-ink/15 pt-6 text-sm text-ink/60">
          <button type="button" onClick={logout} className="underline underline-offset-4 hover:text-ink">
            {messages.login.logout}
          </button>
        </footer>
      )}
    </main>
  );
}
