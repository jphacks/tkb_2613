/** テストと画面の確認に使う、住まいの推定の見本（架空の数字。実際の推定ではない） */
import type { ResidenceEstimate } from "../types/residence";

const POST = (n: number): string => `at://did:plc:demo/app.bsky.feed.post/${n}`;

function grid(): ResidenceEstimate["map"]["cells"] {
  const cells = [];
  for (let r = 0; r < 12; r += 1) {
    for (let c = 0; c < 12; c += 1) {
      const d = Math.hypot(r - 6, c - 5);
      const p = Math.exp(-d * 1.4) * 0.3;
      cells.push({
        lat: 35.711 + r * (3 / 3600),
        lon: 139.758 + c * (4.5 / 3600),
        p,
        p_geo: p * Math.exp(-Math.hypot(r - 4, c - 6) * 0.2),
        geo: Math.exp(-Math.hypot(r - 4, c - 6) * 0.3),
        in_region: d < 1,
      });
    }
  }
  return cells;
}

export const SAMPLE_RESIDENCE: ResidenceEstimate = {
  age_class: "20〜24歳",
  region: {
    people: 28,
    cells: 2,
    city: "文京区",
    town: "弥生一丁目",
    station: "東大前",
    station_walk_minutes: 5,
    same_birthday: 0.015,
  },
  geoprofile: {
    region: {
      people: 28,
      cells: 2,
      city: "文京区",
      town: "弥生一丁目",
      station: "東大前",
      station_walk_minutes: 5,
      same_birthday: 0.015,
    },
    places: ["東京大学", "千駄木", "湯島"],
    other_bases: ["運河"],
    buffer_m: 1292,
  },
  map: {
    cell_lat: 3 / 3600,
    cell_lon: 4.5 / 3600,
    cells: grid(),
    labels: [
      { kind: "station", name: "根津", lat: 35.7179, lon: 139.7652 },
      { kind: "station", name: "東大前", lat: 35.7176, lon: 139.7579 },
      { kind: "town", name: "弥生一丁目", lat: 35.7166, lon: 139.761 },
    ],
  },
  steps: [
    { post_id: null, people: 29581605, cells: 229318, same_birthday: null },
    { post_id: POST(1), people: 24411861, cells: 160230, same_birthday: null },
    { post_id: POST(3), people: 943082, cells: 4004, same_birthday: null },
    { post_id: POST(4), people: 47989, cells: 193, same_birthday: null },
    { post_id: POST(5), people: 327, cells: 2, same_birthday: null },
    { post_id: POST(13), people: 28, cells: 2, same_birthday: null },
    { post_id: POST(14), people: 28, cells: 2, same_birthday: 0.015 },
  ],
  influence: [
    { post_id: POST(1), people_without: 2489, delta: 2461, contradiction: false },
    { post_id: POST(4), people_without: 2373, delta: 2345, contradiction: false },
    { post_id: POST(5), people_without: 2223, delta: 2195, contradiction: false },
    { post_id: POST(13), people_without: 327, delta: 299, contradiction: false },
    { post_id: POST(3), people_without: 124, delta: 97, contradiction: false },
    { post_id: POST(14), people_without: 28, delta: 0, contradiction: false },
  ],
  evidence: [
    { post_id: POST(1), layer: 2, kind: "line", value: "千代田線", excerpt: "千代田線、また止まってる…", applied: true, clue_indices: [] },
    { post_id: POST(3), layer: 1, kind: "walk_minutes", value: "5", excerpt: "最寄り駅まで徒歩5分の部屋にして正解だった", applied: true, clue_indices: [] },
    { post_id: POST(4), layer: 2, kind: "line", value: "南北線", excerpt: "南北線の駅も歩いて行けるの、地味に便利", applied: true, clue_indices: [] },
    { post_id: POST(5), layer: 5, kind: "town", value: "弥生", excerpt: "近所の秋祭り、法被の背中に『弥生』って入ってて地元感あった", applied: true, clue_indices: [] },
    { post_id: POST(13), layer: 0, kind: "age", value: "22", excerpt: "22歳、いまだに自炊がうまくならない", applied: true, clue_indices: [] },
    { post_id: POST(14), layer: 8, kind: "birthday", value: "4月14日", excerpt: "誕生日が4月14日だと…", applied: true, clue_indices: [] },
  ],
  assumptions: ["層どうしは独立とみなす", "当てはまらないマスにも 0.01 を残す"],
  sources: ["出典：e-Stat 国勢調査を加工して作成", "© OpenStreetMap contributors（ODbL）"],
};
