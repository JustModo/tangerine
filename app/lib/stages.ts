/**
 * Real backend stages, not a timer - a bank hit is instant, while a miss can walk through
 * generation, an evaluator pass, a revision, sandbox validation, a repair attempt and a
 * revalidation. The agent reports which one it is actually in.
 *
 * Shared because two screens consume the same stage vocabulary, and a stale second copy
 * shows the fallback label forever on whichever one drifted.
 */
export const STAGE_LABELS: Record<string, string> = {
  selecting: "Selecting problem...",
  generating: "Generating problem...",
  evaluating: "Evaluating problem...",
  revising: "Revising problem...",
  validating: "Validating problem...",
  patching: "Patching problem...",
  revalidating: "Revalidating...",
  regenerating: "Regenerating problem...",
};
