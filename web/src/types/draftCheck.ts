import { isClue, type Clue } from "./clue";

export interface DraftEvidence {
  readonly post_id: string;
  readonly created_at: string;
}

export interface DraftOverlap {
  readonly clue: Clue;
  readonly evidence: readonly DraftEvidence[];
}

export interface DraftCheckResponse {
  readonly posts_checked: number;
  readonly overlaps: readonly DraftOverlap[];
  readonly mock_mode: boolean;
  readonly notices: readonly string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isDraftCheckResponse(value: unknown): value is DraftCheckResponse {
  return (
    isRecord(value) &&
    Number.isInteger(value.posts_checked) &&
    (value.posts_checked as number) >= 0 &&
    typeof value.mock_mode === "boolean" &&
    Array.isArray(value.notices) &&
    value.notices.every((notice) => typeof notice === "string") &&
    Array.isArray(value.overlaps) &&
    value.overlaps.every(
      (item) =>
        isRecord(item) &&
        isClue(item.clue) &&
        Array.isArray(item.evidence) &&
        item.evidence.length > 0 &&
        item.evidence.every(
          (entry) =>
            isRecord(entry) &&
            typeof entry.post_id === "string" &&
            typeof entry.created_at === "string" &&
            !Number.isNaN(Date.parse(entry.created_at)),
        ),
    )
  );
}
