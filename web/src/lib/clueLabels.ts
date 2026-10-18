import type { ClueType } from "@/types/clue";

export const CLUE_LABELS: Readonly<Record<ClueType, string>> = {
  station_sign: "駅名標",
  address_text: "住所表示",
  postal_code: "郵便番号",
  phone: "電話番号",
  shop: "店名・看板",
  plate: "ナンバープレート",
  landmark: "目印になる建物",
  exif_gps: "位置情報（EXIF）",
  face: "顔",
  iris: "瞳の映り込み",
  key: "鍵",
  code: "バーコード・QR コード",
};
