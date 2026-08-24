"""Tolerant substring matching, shared by every place that searches text the user typed.

Kept apart from any one repository because both the problem browser and the chat agent's
library lookup rank on it — two copies would drift, and the autojunk trap below is exactly
the kind of thing you only get right once.
"""

import difflib


def match_score(needle: str, haystack: str) -> float:
    """Longest common contiguous substring, normalised by needle length — tolerant of a
    typo'd or partial query without penalising a short query against a long haystack the
    way SequenceMatcher.ratio() would.

    autojunk=False: the default heuristic marks characters "popular" (and ignores them)
    once the haystack passes ~200 chars, which a real problem statement always does — left
    on, it can silently zero out an otherwise exact substring match (verified: "hash"
    against a >200-char haystack containing "hash-table" returns a length-0 match).
    """
    needle = needle.lower().strip()
    if not needle:
        return 0.0
    matcher = difflib.SequenceMatcher(None, needle, haystack.lower(), autojunk=False)
    match = matcher.find_longest_match(0, len(needle), 0, len(haystack))
    return match.size / len(needle)
