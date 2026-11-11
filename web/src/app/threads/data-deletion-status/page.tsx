import Link from "next/link";

export default function ThreadsDataDeletionStatus() {
  return (
    <main className="mx-auto max-w-2xl px-5 py-12">
      <Link href="/threads" className="text-sm underline">Threads診断に戻る</Link>
      <h1 className="mt-8 font-display text-3xl">Threadsデータ削除の状況</h1>
      <p className="mt-5 leading-8">
        Metaから署名付きのデータ削除依頼を受けた場合、該当するThreadsアカウントの
        セッション、トークン、投稿、診断結果をメモリから直ちに消します。
        診断結果は通常、サーバーに永続保存しません。
      </p>
      <p className="mt-4 leading-8">確認コードはMetaへの応答に含めています。個別の結果については連絡先ページからお問い合わせください。</p>
      <Link href="/contact" className="mt-5 inline-block underline">連絡先</Link>
    </main>
  );
}
