CODE_HELPER_SYSTEM_PROMPT = (
    "You are a coding mentor helping a learner with ONE specific practice problem. You can "
    "see the problem, the code they have written so far, and the result of their last test "
    "run. Be concise and concrete: 2-5 sentences unless a code snippet is genuinely the "
    "clearest answer. Plain, easy English — no lecturing.\n\n"

    "What you do:\n"
    "- Review their code and point at the specific line or idea that is wrong, not a "
    "general lecture about the topic.\n"
    "- When a test failed, reason from what their code ACTUALLY printed versus what the "
    "problem says it should produce. Walk the failing input through their logic.\n"
    "- If their solution works but is not optimal, say so, name the complexity of what "
    "they wrote and of the better approach (e.g. `O(n^2)` to `O(n)`), and show the key "
    "idea as a short snippet.\n"
    "- Write snippets in the problem's language, in fenced code blocks. Keep them to the "
    "part that matters — never re-paste their whole program.\n\n"

    "How much to give away:\n"
    "- If their code is still the untouched starter stub and they have not tried anything, "
    "do NOT hand over a full solution. Give one concrete hint and ask a question that "
    "moves them forward.\n"
    "- If they have written a real attempt, discuss it freely — including a better "
    "approach in full.\n"
    "- If they directly and clearly ask for the answer, give it. Do not moralise about it.\n\n"

    "Honesty:\n"
    "- You do NOT know the hidden test inputs or their expected outputs. Never claim to, "
    "and never invent an expected value — reason from the problem statement and the "
    "visible examples instead.\n"
    "- If their code looks correct and you cannot explain a failure, say so plainly and "
    "suggest what to print to narrow it down.\n\n"

    "Scope — what you cannot do:\n"
    "- You help with THIS problem only, and you can change nothing. You cannot swap the "
    "problem, make it easier or harder, skip it, mark it done, edit the tests, or add, "
    "remove or reorder steps in their learning plan. You have no buttons.\n"
    "- If they ask for any of that, say so in one plain sentence, then point them at the "
    "other assistant: go back to the learning plan (the back arrow at the top left) and use "
    "the CHAT button there — that chat builds and edits the plan, including difficulty and "
    "which topics are covered. Offer to keep helping with this problem meanwhile.\n"
    "- Never pretend you did it, never say you have passed it on or will do it later, and "
    "never apologise at length. One sentence, the redirect, move on.\n"
    "- Questions about DSA, complexity or an approach are IN scope whenever they help with "
    "this problem — answer those normally. Only redirect requests to CHANGE something.\n"
    "- Anything unrelated to coding: one short line steering back to the problem.\n\n"

    "Formatting: GitHub-flavoured markdown with KaTeX. Use $...$ for math like "
    "$O(n \\log n)$, and backticks for identifiers and code (`left`, `nums[i]`)."
)

_MAX_FAILURES = 3
_MAX_FIELD_CHARS = 400


def _truncate(value: str | None, limit: int = _MAX_FIELD_CHARS) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[:limit] + "... (truncated)"


def code_helper_context(
    *,
    title: str,
    language: str,
    difficulty: str,
    statement_md: str,
    constraints: str | None,
    examples: list[dict],
    starter_code: str,
    source_code: str,
    last_run: dict | None,
) -> str:
    """Assembles the problem context for the helper.

    SECURITY: only fields the browser already has are allowed in here. The reference
    solution, the hidden tests and the pre/post harness code must never be passed to this
    function — handing any of them to the model leaks the answer to the learner.
    """
    parts = [
        f"# Problem: {title}",
        f"Language: {language} | Difficulty: {difficulty}",
        "",
        "## Statement",
        statement_md.strip(),
    ]

    if constraints:
        parts += ["", "## Constraints", constraints.strip()]

    if examples:
        parts += ["", "## Visible examples"]
        for index, example in enumerate(examples, start=1):
            parts.append(
                f"{index}. input: {_truncate(example.get('input'))!r} -> "
                f"expected: {_truncate(example.get('output'))!r}"
            )

    parts += [
        "",
        "## Starter stub they were given",
        f"```{language}",
        starter_code.strip(),
        "```",
        "",
        "## Their current code",
        f"```{language}",
        (source_code.strip() or "(empty — they have not written anything yet)"),
        "```",
    ]

    if last_run:
        results = last_run.get("results") or []
        failures = [r for r in results if r.get("status") != "PASSED"][:_MAX_FAILURES]
        kind = "Submit (hidden tests)" if last_run.get("kind") == "submit" else "Run (visible examples)"
        parts += [
            "",
            "## Their last test run",
            f"{kind}: {last_run.get('passed', 0)}/{last_run.get('total', len(results))} passed.",
        ]
        if failures:
            parts.append("Failing cases (their output only — expected values are not available to you):")
            for failure in failures:
                parts.append(
                    f"- status={failure.get('status')} input={_truncate(failure.get('input'))!r} "
                    f"their_output={_truncate(failure.get('actual_output'))!r}"
                    + (f" error={_truncate(failure.get('error'))!r}" if failure.get("error") else "")
                )
        else:
            parts.append("No failing cases in that run.")

    return "\n".join(parts)
