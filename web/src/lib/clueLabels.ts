import type { ClueType } from "@/types/clue";

export const CLUE_LABELS: Readonly<Record<ClueType, string>> = {
  station_sign: "駅名標",
  rail_view: "ホーム・線路",
  reflection: "映り込み",
  shop: "店名・看板",
  landmark: "目印になる建物",
  address_text: "住所表示",
  postal_code: "郵便番号",
  phone: "電話番号",
  plate: "ナンバープレート",
  uniform: "制服・作業着",
  face: "顔",
  key: "鍵",
  code: "バーコード・QR コード",
  name_text: "名前",
  org_text: "会社・学校・団体",
  handle_text: "SNS のユーザー名",
  place_text: "地名・駅名・店名",
  age_text: "年齢・誕生日",
  routine_text: "生活の決まり",
  relation_text: "家族・同居人",
};
