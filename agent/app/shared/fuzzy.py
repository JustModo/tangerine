"""Tolerant substring matching, shared by everything that searches text the user typed.

Lives outside any one repository because the problem browser and the chat agent's library
lookup both rank on it, and must rank identically.
"""

import difflib


def match_score(needle: str, haystack: str) -> float:
    """Longest common substring, normalised by needle length. Tolerant of a partial or
    typo'd query in a way SequenceMatcher.ratio() is not.

    autojunk=False matters: with it on, a haystack over ~200 chars (every real problem
    statement) can zero out an exact substring match. Verified with "hash" against a
    haystack containing "hash-table".
    """
    needle = needle.lower().strip()
    if not needle:
        return 0.0
    matcher = difflib.SequenceMatcher(None, needle, haystack.lower(), autojunk=False)
    match = matcher.find_longest_match(0, len(needle), 0, len(haystack))
    return match.size / len(needle)
