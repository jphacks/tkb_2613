import { DiagnosePanel } from "@/components/diagnose/DiagnosePanel";
import { LoginPanel } from "@/components/login/LoginPanel";
import { messages } from "@/lib/messages";

export default function Home() {
  const name = messages.app.name;
  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:px-8 sm:py-20">
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
      <DiagnosePanel />
    </main>
  );
}
