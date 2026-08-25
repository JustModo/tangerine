# Split into blocks so the repair call can take the subset it actually needs. A patch
# cannot return a title, hints, tags or a stress test (see ProblemPatch), so the rules for
# writing those are dead weight on every repair — and repairs are budgeted at up to two
# per problem. Wording is unchanged; only the seams are new.
_PROBLEM_INTRO = (
    "You write a single DSA practice problem for a given skill, language, and difficulty. "
    "Produce a clear statement (markdown), 2-4 worked examples, and the problem's code as "
    "four separate fragments: pre_code, user_code, post_code, and reference_user_code.\n\n"

    "title: concise, 5-6 words maximum (e.g. 'Reverse a Linked List', 'Two Sum with Hash "
    "Map') — never a full sentence or a restatement of the whole problem.\n\n"
)

_EXAMPLE_FORMAT = (
    "Each example's explanation: 2-4 short lines separated by \\n (a real multi-line "
    "string), not one long paragraph. First line states the key insight; the remaining "
    "lines briefly walk through how that example's specific numbers produce its output. "
    "Keep each line under ~15 words.\n\n"
)

_CODE_SHAPE = (
    "EXECUTION MODEL: the backend concatenates pre_code + \"\\n\\n\" + user_code (or, for "
    "validation, reference_user_code) + \"\\n\\n\" + post_code into ONE source file and runs "
    "it as-is — no test harness, no injected imports, nothing else added. Your fragments "
    "must be independently-valid text that only becomes one coherent, compiling program "
    "once concatenated in exactly that order.\n\n"

    "WHAT GOES WHERE:\n"
    "- pre_code: everything that must appear BEFORE the learner's function — imports/"
    "includes, any struct/typedef declarations. In Python ONLY, pre_code also reads stdin "
    "and parses it into top-level variables (Python allows free top-level statements). In "
    "C, C++, and Java, pre_code must NOT read stdin — those languages have no free "
    "top-level statements, so parsing happens inside main() in post_code instead.\n"
    "- user_code: ONLY the function (or, for Java, ONLY the static method) the learner "
    "implements. Nothing else — no stdin reads, no prints, no other declarations. Give it "
    "a stub body (Python `pass` / a dummy `return 0`; Java/C/C++ a `// TODO` comment plus "
    "a dummy return) that runs without crashing but need not be correct.\n"
    "- post_code: everything that runs AFTER the learner's function. In Python: call the "
    "function with the exact variables pre_code already parsed, then print the result. In "
    "C, C++, and Java: a COMPLETE main (or main method) that reads stdin, calls the "
    "function, and prints the result.\n"
    "- reference_user_code: the exact same signature as user_code (identical function/"
    "method name, identical parameter names, order, and types, identical return type) but "
    "with the correct working solution instead of the stub. Used only to validate the "
    "problem before any learner ever sees it — it is never shown to a learner.\n\n"

    "CONSISTENCY RULES (violating any of these produces a program that fails to compile or "
    "run, and the problem will be discarded):\n"
    "1. The function/method name and full parameter list must be IDENTICAL, character-for-"
    "character, across user_code, reference_user_code, and the call site in post_code.\n"
    "2. Every variable pre_code parses from stdin (Python) and every variable post_code's "
    "main() parses from stdin (C/C++/Java) must be passed to the function using that exact "
    "name and in that exact order — no renaming, no reordering.\n"
    "3. post_code must print EXACTLY one thing: the function's return value, in the same "
    "textual form your example outputs show (e.g. a list becomes space-separated numbers "
    "with no brackets or quotes, unless an example's output literally contains brackets/"
    "quotes).\n"
    "4. Never put parsing logic in user_code/reference_user_code and never put solution "
    "logic in pre_code or post_code — the split is strict.\n\n"

    "PER-LANGUAGE SHAPE:\n"
    "- python: pre_code is top-level stdin reads (e.g. "
    "`nums = list(map(int, input().split()))`). user_code/reference_user_code is one "
    "`def solve(...):`. post_code is `result = solve(...)` then `print(result)`.\n"
    "- c: pre_code is `#include` lines plus any struct/typedef, nothing left open. "
    "user_code is one complete function, e.g. `int solve(int a, int b) { ... }`. post_code "
    "is a complete `int main(void) { <scanf the inputs>; printf(\"%d\\n\", solve(...)); "
    "return 0; }`.\n"
    "- cpp: same as c but `#include <iostream>` / `using namespace std;` in pre_code, "
    "`cin >>` in post_code's `int main()`, and `cout << solve(...) << endl;`.\n"
    "- java: pre_code ends with an UNCLOSED `public class Main {` (imports like "
    "`import java.util.Scanner;` above it). user_code is exactly one complete "
    "`static <type> solve(...) { ... }` method (its own matched braces). post_code starts "
    "with `public static void main(String[] args) { ... }` that uses Scanner to read "
    "stdin, calls solve(...), prints the result, and ends with the final `}` that closes "
    "the class opened in pre_code.\n\n"
)

_WORKED_EXAMPLES = (
    "WORKED EXAMPLE (python) — problem: read two integers from one line, return their sum:\n"
    "pre_code: `a, b = map(int, input().split())`\n"
    "user_code: `def solve(a, b):\\n    # TODO: implement\\n    return 0`\n"
    "post_code: `print(solve(a, b))`\n"
    "reference_user_code: `def solve(a, b):\\n    return a + b`\n"
    "Concatenated and run against stdin `2 3`, this prints `5`.\n\n"

    "WORKED EXAMPLE (java) — same problem:\n"
    "pre_code:\n"
    "```\n"
    "import java.util.Scanner;\n\n"
    "public class Main {\n"
    "```\n"
    "user_code:\n"
    "```\n"
    "    static int solve(int a, int b) {\n"
    "        // TODO: implement\n"
    "        return 0;\n"
    "    }\n"
    "```\n"
    "post_code:\n"
    "```\n"
    "    public static void main(String[] args) {\n"
    "        Scanner scanner = new Scanner(System.in);\n"
    "        int a = scanner.nextInt();\n"
    "        int b = scanner.nextInt();\n"
    "        System.out.println(solve(a, b));\n"
    "    }\n"
    "}\n"
    "```\n"
    "Concatenated, this is one valid Main.java that compiles and, against stdin `2 3`, "
    "prints `5`.\n\n"
)

# Everything here describes a field ProblemPatch cannot return, so repairs skip it.
_AUTHORING_EXTRAS = (
    "Also produce: a short constraints section (input value ranges, expected time/space "
    "complexity); 1-3 progressive hints ordered from a gentle nudge to a stronger hint, "
    "never revealing the full solution; and 2-4 short topical tags (e.g. 'two-pointers', "
    "'hash-map').\n\n"

    "stress_test: ONE more stdin input, separate from the others, sized at the top of the "
    "constraints you stated — big enough that an optimal solution and a brute-force one "
    "take visibly different amounts of time, while your reference solution still finishes "
    "in well under a second. Same stdin format as everything else. If the problem has no "
    "meaningful size to scale (fixed-size input, pure arithmetic), omit it rather than "
    "inventing one.\n\n"
)

_HIDDEN_TESTS = (
    "hidden_tests: 3-5 ADDITIONAL stdin inputs used only for grading, never shown to the "
    "learner. Same stdin format as the examples, but different values, chosen to catch the "
    "mistakes the examples don't — a single-element input, all-equal values, the minimum "
    "and maximum of the stated constraints, negative numbers, no-answer-exists. "
    "Give inputs only; expected outputs come from running the reference solution.\n\n"
)

_INPUT_RULES = (
    "EVERY INPUT MUST BE READABLE BY YOUR OWN HARNESS. Each example input, each hidden "
    "test and the stress test is fed to the program as stdin exactly as written, and your "
    "pre_code/post_code must be able to parse all of them. In particular:\n"
    "- NEVER give a completely empty input. `input()` raises EOFError on empty stdin, and "
    "Scanner/cin/scanf fare no better — the reference crashes on its own test case and the "
    "whole problem is discarded.\n"
    "- To test the empty-collection case, say it in a form your parser can read: if "
    "pre_code reads a count first, that is a line containing `0` (followed by an empty "
    "line only if your parser reads one). If your format has no count, the smallest valid "
    "input is one element — use that instead and do not test empty at all.\n"
    "- Read your own pre_code and post_code back against each input line by line. If any "
    "input would leave a read with nothing to consume, fix the input, not the harness."
)

PROBLEM_SYSTEM_PROMPT = (
    _PROBLEM_INTRO
    + _EXAMPLE_FORMAT
    + _CODE_SHAPE
    + _WORKED_EXAMPLES
    + _AUTHORING_EXTRAS
    + _HIDDEN_TESTS
    + _INPUT_RULES
)

# What a repair actually needs: how the fragments fit together, and the rules covering the
# fields ProblemPatch can return (code, examples, hidden_tests, statement). It is NOT
# writing a new problem, so the authoring intro, the worked examples and the
# hints/tags/stress-test rules are all left out.
PATCH_SYSTEM_PROMPT = (
    "You repair one DSA practice problem that failed automated validation. You are not "
    "writing a new problem — the question stays exactly as it is.\n\n"
    + _EXAMPLE_FORMAT
    + _CODE_SHAPE
    + _HIDDEN_TESTS
    + _INPUT_RULES
)


def problem_user_prompt(
    skill: str, language: str, difficulty: str, avoid_titles: list[str] | None = None
) -> str:
    prompt = f"Skill: {skill}\nLanguage: {language}\nDifficulty: {difficulty}"
    if avoid_titles:
        # Without this, learner gets the same problem on repeat attempts.
        listed = "\n".join(f"- {title}" for title in avoid_titles)
        prompt += (
            "\n\nThe learner has ALREADY been given these problems for this skill. Write a "
            "genuinely different one — a different question, not a reworded version of any "
            f"of them:\n{listed}"
        )
    return prompt


_PATCH_RULES = (
    "REPAIR RULES:\n"
    "1. Return ONLY the fields you actually changed. Leave everything else null — it is "
    "kept as-is. A repair that restates unchanged code is wasted.\n"
    "2. Do NOT change the question. The problem being asked stays exactly the same: same "
    "task, same input format, same example INPUTS. You are fixing the code and the stated "
    "answers around the question, never the question.\n"
    "3. Never weaken a test, drop a case, or make post_code print something easier just to "
    "get past validation. Fix the actual defect.\n"
    "4. The same CONSISTENCY RULES and PER-LANGUAGE SHAPE from your instructions still "
    "apply to anything you return — a fragment must still concatenate into one valid "
    "program."
)


def patch_problem_user_prompt(
    kind: str,
    detail: str,
    language: str,
    pre_code: str,
    reference_user_code: str,
    post_code: str,
    examples: list,
    hidden_tests: list[str],
    statement_md: str | None = None,
    user_code: str | None = None,
) -> str:
    """A repair prompt for a problem that already failed the sandbox. Deliberately carries
    the minimum that can explain the failure: the harness, the tests, and what actually
    happened. Everything the failure can't be about (title, hints, tags, constraints,
    skills) is left out — this call exists to be cheap enough to always be worth making."""
    diagnosis = {
        "runtime": "Running your reference solution against these inputs FAILED — it "
        "crashed, timed out, or printed nothing. Almost always the harness and the "
        "reference disagree (a signature mismatch, a parse that consumes the wrong number "
        "of tokens, a missing import) rather than the algorithm being wrong.",
        "mismatch": "Your reference solution RAN, but its output disagrees with the "
        "answer your own statement claims for that example. Decide which one is wrong and "
        "fix that one: either the reference computes the wrong thing, or the example's "
        "stated output is wrong.",
        "no_tests": "The problem has no usable grading inputs — the examples or the "
        "hidden tests came back blank. Every input is fed to the program as stdin exactly "
        "as written, so a blank one makes the reference crash on its own test case. Write "
        "real inputs in the same stdin format your harness parses.",
    }[kind]

    sections = [
        f"Language: {language}",
        f"THIS PROBLEM FAILED VALIDATION.\n{diagnosis}",
        f"WHAT HAPPENED:\n{detail}",
    ]
    if statement_md is not None:
        sections.append(f"statement_md:\n{statement_md}")
    sections.append(f"pre_code:\n{pre_code}")
    if user_code is not None:
        sections.append(f"user_code:\n{user_code}")
    sections.append(f"reference_user_code:\n{reference_user_code}")
    sections.append(f"post_code:\n{post_code}")
    sections.append(
        "examples:\n"
        + "\n".join(f"- input={ex.input!r} output={ex.output!r}" for ex in examples)
    )
    sections.append(
        "hidden_tests (inputs only):\n" + "\n".join(f"- {value!r}" for value in hidden_tests)
    )
    sections.append(_PATCH_RULES)
    return "\n\n".join(sections)


def adapt_problem_user_prompt(source_problem: str, language: str) -> str:
    """For a problem the learner pasted in (e.g. from LeetCode): keep THEIR question, and
    build the harness/examples/solution around it rather than inventing a new problem."""
    return (
        f"Language: {language}\n\n"
        "Do NOT invent a new problem. Adapt the exact problem below into the required "
        "format, keeping its meaning, constraints and examples faithful to the original.\n"
        "- statement_md: the same problem, lightly cleaned up as markdown. Keep any LaTeX.\n"
        "- title: a concise 5-6 word name for it.\n"
        "- difficulty: your honest rating of the original ('easy', 'medium' or 'hard').\n"
        "- examples: use the original's worked examples where it gives them; add one only "
        "if it gives none. Every example's input must match the stdin format your pre_code "
        "and post_code parse.\n"
        "- hidden_tests: still required. The original's examples are rarely enough to grade "
        "on, so add 3-5 extra edge-case inputs of your own in the same stdin format.\n"
        "- Everything else (pre_code, user_code, post_code, reference_user_code, "
        "constraints, hints, tags, skills) follows the same rules as always.\n\n"
        f"The learner's problem:\n{source_problem}"
    )
