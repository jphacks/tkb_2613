import { LoginPanel } from "@/components/login/LoginPanel";

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:px-8 sm:py-20">
      <header className="mb-14">
        <p className="mb-3 text-sm tracking-[0.3em] text-ink/60">あなたの投稿、組み合わせると</p>
        <h1 className="font-display text-5xl leading-tight sm:text-7xl">
          もういいかい<span className="text-seeker">？</span>
        </h1>
        <p className="mt-5 max-w-xl text-ink/80">
          Bluesky の自分の投稿を特定班AIが読み、1件ずつは無害な投稿の組み合わせから、何がわかるかを見せます。調べられるのはログインした本人のアカウントだけです。
        </p>
      </header>
      <LoginPanel />
    </main>
  );
}
