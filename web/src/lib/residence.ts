/** 住まいの推定（点数の地図）を画面に出すときの、数の表し方と並べ方 */

import { messages } from "@/lib/messages";
import type { ResidenceEstimate, ResidenceStep } from "@/types/residence";

const t = messages.residence;
const MAN = 10_000;
/** 見出しなどに出す投稿の抜き出しの長さ */
export const EXCERPT_MAX = 28;

/** 人数を「約2,432人」「約2,958万人」「0.02人」のように出す（推定なので「約」を付ける） */
export function formatPeople(people: number): string {
  if (people >= MAN) {
    const man = people / MAN;
    return t.people.man(man >= 100 ? Math.round(man).toLocaleString("ja-JP") : man.toFixed(1));
  }
  if (people >= 1) return t.people.some(Math.round(people).toLocaleString("ja-JP"));
  return t.people.fraction(people.toPrecision(2));
}

/** 人数が前の段から変わった段だけ（最初の「投稿なし」は必ず残す） */
export function changedSteps(steps: readonly ResidenceStep[]): ResidenceStep[] {
  return steps.filter((step, i) => i === 0 || Math.round(step.people) !== Math.round(steps[i - 1].people) || step.same_birthday !== steps[i - 1].same_birthday);
}

export function excerpt(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (!flat) return t.noText;
  return flat.length > EXCERPT_MAX ? `${flat.slice(0, EXCERPT_MAX - 1)}…` : flat;
}

/** 一番濃いマスの説明（「文京区 弥生一丁目／東大前まで徒歩5分のあたり」） */
export function densestText(residence: ResidenceEstimate): string {
  const { region } = residence;
  const place = t.place(region.city, region.town);
  const walk = region.station && region.station_walk_minutes !== null ? `／${t.walk(region.station, region.station_walk_minutes)}` : "";
  return `${place}${walk}`;
}
