/**
 * 地域メッシュの番号から位置を計算する（Python は tkb_engine.walk_area.mesh_bounds）。
 * 500m メッシュ（9桁）：1次（緯度40分×経度1度）→ 2次（5分×7.5分）→ 3次（30秒×45秒）→ 4分割（15秒×22.5秒）。
 */

export const MESH_LAT = 15 / 3600;
export const MESH_LON = 22.5 / 3600;

/** 500m メッシュの [南, 西, 北, 東]（度） */
export function meshBounds(code: string): [number, number, number, number] {
  const d = (from: number, to: number) => Number(code.slice(from, to));
  const quarter = d(8, 9) - 1;
  const south = d(0, 2) / 1.5 + (d(4, 5) * 5) / 60 + (d(6, 7) * 30) / 3600 + Math.floor(quarter / 2) * MESH_LAT;
  const west = d(2, 4) + 100 + (d(5, 6) * 7.5) / 60 + (d(7, 8) * 45) / 3600 + (quarter % 2) * MESH_LON;
  return [south, west, south + MESH_LAT, west + MESH_LON];
}

/** その緯度での、緯度1度・経度1度の長さ（m） */
export function metersPerDegree(lat: number): [number, number] {
  const phi = (lat * Math.PI) / 180;
  return [
    111_132.954 - 559.822 * Math.cos(2 * phi) + 1.175 * Math.cos(4 * phi),
    111_412.84 * Math.cos(phi) - 93.5 * Math.cos(3 * phi),
  ];
}

/** center を原点に、東を x、南を y（画面の下）にしたメートルの座標へ */
export function toLocalMeters(center: readonly [number, number]): (lat: number, lon: number) => [number, number] {
  const [perLat, perLon] = metersPerDegree(center[0]);
  return (lat, lon) => [(lon - center[1]) * perLon, -(lat - center[0]) * perLat];
}
