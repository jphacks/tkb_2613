"use client";

import { useId, useState } from "react";

import { messages } from "@/lib/messages";
import { formatPeople } from "@/lib/residence";
import type { ResidenceEstimate, ResidenceMapCell } from "@/types/residence";

const t = messages.residence;
/**
 * 濃淡は対数で付ける。一番濃いマスの 1/10^SHADE_DECADES までを濃さの幅にする
 * （確率は数マスに集中するので、比のままだとほかのマスが見えない）
 */
const SHADE_DECADES = 4;
const SHADE_FLOOR = 0.04;
/** 層7の山は、頂上のまわりが見えるように濃さを強めに絞る */
const GEO_OPACITY = 0.6;
const GEO_POWER = 3;
const LABEL_SIZE = 1.1;
const TOWN_LABEL_DROP = 2.2;

export function shade(value: number, most: number): number {
  if (value <= 0 || most <= 0) return 0;
  const level = 1 + Math.log10(value / most) / SHADE_DECADES;
  return level <= 0 ? 0 : Math.max(SHADE_FLOOR, Math.min(1, level));
}

interface Grid {
  cols: number;
  rows: number;
  x: (lon: number) => number;
  y: (lat: number) => number;
}

/** マスの中心の緯度経度を、左上を 0 とするマス目の番号に直す（1マス＝1） */
function grid(cells: readonly ResidenceMapCell[], cellLat: number, cellLon: number): Grid {
  const lats = cells.map((c) => c.lat);
  const lons = cells.map((c) => c.lon);
  const north = Math.max(...lats) + cellLat / 2;
  const south = Math.min(...lats) - cellLat / 2;
  const west = Math.min(...lons) - cellLon / 2;
  const east = Math.max(...lons) + cellLon / 2;
  return {
    cols: Math.max(1, Math.round((east - west) / cellLon)),
    rows: Math.max(1, Math.round((north - south) / cellLat)),
    x: (lon) => (lon - west) / cellLon,
    y: (lat) => (north - lat) / cellLat,
  };
}

/**
 * 確率の地図。外部の地図タイルは使わず、100m マスの濃淡で描く。
 * 「よく行く場所の山を重ねる」を押すと、層7（参考の層）を掛けた濃淡と、層7だけの山を重ねる。
 */
export function ResidenceMap({ residence }: { residence: ResidenceEstimate }) {
  const [withGeo, setWithGeo] = useState(false);
  const noteId = useId();
  const { map, geoprofile } = residence;
  if (map.cells.length === 0) return null;
  const g = grid(map.cells, map.cell_lat, map.cell_lon);
  const value = (c: ResidenceMapCell) => (withGeo ? c.p_geo : c.p);
  const most = Math.max(...map.cells.map(value)) || 1;
  return (
    <div className="space-y-3">
      <div className="residence-map relative mx-auto aspect-square w-full max-w-md overflow-hidden bg-paper-deep" role="img" aria-label={t.mapLabel} aria-describedby={noteId}>
        <svg viewBox={`0 0 ${g.cols} ${g.rows}`} className="size-full" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
          {map.cells.map((c) => (
            <rect
              key={`${c.lat},${c.lon}`}
              x={g.x(c.lon) - 0.5}
              y={g.y(c.lat) - 0.5}
              width={1}
              height={1}
              className="residence-cell"
              style={{ fillOpacity: shade(value(c), most) }}
            />
          ))}
          {withGeo &&
            map.cells.map((c) => (
              <rect key={`geo-${c.lat},${c.lon}`} x={g.x(c.lon) - 0.5} y={g.y(c.lat) - 0.5} width={1} height={1} className="residence-geo" style={{ fillOpacity: GEO_OPACITY * Math.pow(c.geo, GEO_POWER) }} />
            ))}
          {map.cells
            .filter((c) => c.in_region)
            .map((c) => (
              <rect key={`r-${c.lat},${c.lon}`} x={g.x(c.lon) - 0.5} y={g.y(c.lat) - 0.5} width={1} height={1} className="residence-region" vectorEffect="non-scaling-stroke" />
            ))}
          {map.labels.map((label) => (
            <g key={`${label.kind}-${label.name}`} transform={`translate(${g.x(label.lon)} ${g.y(label.lat)})`}>
              {label.kind === "station" && <circle r={0.45} className="residence-station" />}
              <text x={0.8} y={label.kind === "station" ? 0.4 : TOWN_LABEL_DROP} fontSize={LABEL_SIZE} className={label.kind === "station" ? "residence-label" : "residence-label residence-town"}>
                {label.kind === "station" ? `${label.name}駅` : label.name}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <p id={noteId} className="text-xs text-ink/60">
        {t.mapNote}
      </p>
      {geoprofile && (
        <div className="space-y-1">
          <button type="button" aria-pressed={withGeo} onClick={() => setWithGeo((on) => !on)} className="residence-toggle border-2 border-ink px-3 py-1 text-sm font-bold">
            {t.geoToggle}
          </button>
          <p className="text-xs text-ink/70">
            {t.geoNote(geoprofile.places.join("・"), geoprofile.other_bases.join("・"))}
            {withGeo && <span className="block">{t.geoRegion(formatPeople(geoprofile.region.people))}</span>}
          </p>
        </div>
      )}
    </div>
  );
}
