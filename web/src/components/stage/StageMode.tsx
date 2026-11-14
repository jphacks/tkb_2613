"use client";

import { useEffect } from "react";

import "./stage.css";

/** 発表モードを覚えておくキー。タブを閉じれば消える（sessionStorage） */
export const STAGE_KEY = "tkb_stage";

/** ?stage=1 で入れ、?stage=0 で外す。クエリがなければ、このタブで前に決めた状態に従う */
function stageOn(search: string): boolean {
  const param = new URLSearchParams(search).get("stage");
  try {
    if (param === "1") window.sessionStorage.setItem(STAGE_KEY, "1");
    if (param === "0") window.sessionStorage.removeItem(STAGE_KEY);
    return window.sessionStorage.getItem(STAGE_KEY) === "1";
  } catch {
    // 保存できないブラウザでも、?stage=1 を付けた画面だけは発表モードにする
    return param === "1";
  }
}

/**
 * 発表モード。プロジェクターで後ろの席から読めるよう文字を全体に大きくし、Reveal の演出の間を少し伸ばす。
 * html に stage を付けるだけで、普段の表示は変えない（stage.css）。
 */
export function StageMode() {
  useEffect(() => {
    document.documentElement.classList.toggle("stage", stageOn(window.location.search));
  }, []);
  return null;
}
