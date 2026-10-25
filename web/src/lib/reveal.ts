import type { Clue, ClueType, Region } from "@/types/clue";
import type { Conclusion } from "@/types/diagnose";
import type { Post, PostImage } from "@/types/post";

/** 診断のあとに叩きつける証拠の最大枚数 */
export const MAX_REVEAL = 8;

/** 見せたときに効く順。名前や住所のように、それだけで本人に近づくものを先にする */
const DANGER_ORDER: readonly ClueType[] = [
  "name_text",
  "address_text",
  "postal_code",
  "station_sign",
  "phone",
  "plate",
  "org_text",
  "uniform",
  "shop",
  "place_text",
  "landmark",
  "rail_view",
  "handle_text",
  "age_text",
  "relation_text",
  "routine_text",
  "reflection",
  "code",
  "key",
  "face",
];

export interface RevealItem {
  /** 診断の clues の並びでの番号 */
  clueIndex: number;
  clue: Clue;
  post: Post;
  /** 写真の手がかりなら、その写真 */
  image: PostImage | null;
  /** 推定の根拠になった手がかりか */
  used: boolean;
}

function dangerRank(type: ClueType): number {
  const i = DANGER_ORDER.indexOf(type);
  return i === -1 ? DANGER_ORDER.length : i;
}

/**
 * 叩きつける証拠を選ぶ。推定の根拠になったものを先に、そのあとは危ない種類の順に並べる。
 * 同じ種類で同じ値の手がかり（別の投稿の「夜勤明け」など）は 1 枚にまとめる。
 */
export function pickReveal(
  posts: readonly Post[],
  clues: readonly Clue[],
  conclusions: readonly Conclusion[],
  max: number = MAX_REVEAL,
): RevealItem[] {
  const byId = new Map(posts.map((p) => [p.post_id, p]));
  const used = new Set(conclusions.flatMap((c) => c.clue_indices));
  const items = clues.flatMap((clue, clueIndex): RevealItem[] => {
    const post = byId.get(clue.post_id);
    if (!post) return [];
    const image = clue.image_index === null ? null : (post.images[clue.image_index] ?? null);
    return [{ clueIndex, clue, post, image, used: used.has(clueIndex) }];
  });

  items.sort(
    (a, b) =>
      Number(b.used) - Number(a.used) ||
      dangerRank(a.clue.type) - dangerRank(b.clue.type) ||
      b.clue.confidence - a.clue.confidence ||
      a.clueIndex - b.clueIndex,
  );

  const seen = new Set<string>();
  return items
    .filter(({ clue }) => {
      const key = `${clue.type}\u0000${clue.value}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, max);
}

/**
 * 写真の手がかりの位置を、まわりを少し含めて切り抜くための位置。
 * 返すのは、枠の縦横比と、枠に対する写真の大きさと位置（%）と、枠の中での手がかりの位置（%）。
 */
export function cropStyle(
  [x1, y1, x2, y2]: Region,
  { width, height }: { width: number; height: number },
  margin = 0.15,
) {
  const padX = (x2 - x1) * margin;
  const padY = (y2 - y1) * margin;
  const left = Math.max(0, x1 - padX);
  const top = Math.max(0, y1 - padY);
  const right = Math.min(width, x2 + padX);
  const bottom = Math.min(height, y2 + padY);
  const w = right - left;
  const h = bottom - top;
  const pct = (n: number) => `${n * 100}%`;
  return {
    aspectRatio: `${w} / ${h}`,
    image: { width: pct(width / w), height: pct(height / h), left: pct(-left / w), top: pct(-top / h) },
    mark: { left: pct((x1 - left) / w), top: pct((y1 - top) / h), width: pct((x2 - x1) / w), height: pct((y2 - y1) / h) },
  };
}

/** 身元カードの名前に使う推定。先にあるものを使う（engine の R5） */
const NAME_ATTRIBUTES: readonly string[] = ["full_name", "given_name_or_nickname"];

/**
 * 身元カードに大きく出す名前と、その下に並べる残りの推定。
 * 推定したフルネーム、呼び名の順に使い、どちらもなければ写っていた名前の文字（pickName）。
 * 名前に使った推定は、残りの推定の行には出さない（同じ名前を2回出さない）。
 */
export function identityName(
  clues: readonly Clue[],
  conclusions: readonly Conclusion[],
): { name: string | null; rest: readonly Conclusion[] } {
  for (const attribute of NAME_ATTRIBUTES) {
    const found = conclusions.find((c) => c.attribute === attribute);
    if (found) return { name: found.value, rest: conclusions.filter((c) => !NAME_ATTRIBUTES.includes(c.attribute)) };
  }
  return { name: pickName(clues), rest: conclusions };
}

/**
 * 身元カードに出す名前。写真や本文に写っていた文字（name_text）をそのまま使い、推測で補わない。
 * 読めない文字（x）の少ないもの、確からしいものを選ぶ。なければ null。
 */
export function pickName(clues: readonly Clue[]): string | null {
  const unreadable = (value: string) => (value.match(/x/gi) ?? []).length;
  const names = clues
    .filter((c) => c.type === "name_text" && c.value.trim())
    .sort((a, b) => unreadable(a.value) - unreadable(b.value) || b.confidence - a.confidence);
  return names[0]?.value.trim() ?? null;
}

/**
 * 顔を写真の枠に出すときの、顔の手がかりの確からしさの下限。
 * これは「そこに顔が写っているか」の確からしさで、本人かどうかではない（顔で照合はしない）。
 */
export const FACE_MIN_CONFIDENCE = 0.8;

export interface FacePhoto {
  clue: Clue;
  image: PostImage;
}

/**
 * 身元カードの写真の枠に出す顔。本人の投稿の写真に写っていた顔の手がかりのうち、
 * 位置があり、確からしさが FACE_MIN_CONFIDENCE 以上で、いちばん確からしいもの。なければ null。
 */
export function pickFace(posts: readonly Post[], clues: readonly Clue[]): FacePhoto | null {
  const byId = new Map(posts.map((p) => [p.post_id, p]));
  const faces = clues
    .flatMap((clue): FacePhoto[] => {
      if (clue.type !== "face" || !clue.region || clue.image_index === null) return [];
      if (clue.confidence < FACE_MIN_CONFIDENCE) return [];
      const image = byId.get(clue.post_id)?.images[clue.image_index];
      return image ? [{ clue, image }] : [];
    })
    .sort((a, b) => b.clue.confidence - a.clue.confidence);
  return faces[0] ?? null;
}
