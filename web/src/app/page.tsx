import { HideAndSeek } from "@/components/hide-and-seek/HideAndSeek";

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:px-8 sm:py-20">
      <header className="mb-14">
        <p className="mb-3 text-sm tracking-[0.3em] text-ink/60">投稿する前に</p>
        <h1 className="font-display text-5xl leading-tight sm:text-7xl">
          もういいかい<span className="text-seeker">？</span>
        </h1>
        <p className="mt-5 max-w-xl text-ink/80">
          写真に写り込んだ駅名標や看板、瞳の映り込みから、あなたの居場所を特定班AIが探します。写真はサーバーに保存されません。
        </p>
      </header>
      <HideAndSeek />
    </main>
  );
}
