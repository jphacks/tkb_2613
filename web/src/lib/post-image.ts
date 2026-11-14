import type { PostImage } from "@/types/post";

/** Resolve an image to the mock-only API route when the fixture declares a local asset. */
export function postImageSrc(image: PostImage): string {
  return image.mock_asset
    ? `/api/mock-assets/${encodeURIComponent(image.mock_asset)}`
    : image.url;
}
