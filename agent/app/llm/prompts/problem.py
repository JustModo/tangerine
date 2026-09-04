from app.llm.schemas.problem import GeneratedProblem
from app.shared.code_assembly import annotated_program

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
    "once concatenated in exactly that order. The LANGUAGE SHAPE section below is the exact "
    "form your four fragments must take for the language you were asked for — follow it "
    "literally, and never borrow another language's shape.\n\n"

    "WHAT GOES WHERE:\n"
    "- pre_code: everything that must appear BEFORE the learner's function — imports/"
    "includes, any struct/typedef declarations, and the stdin parsing if (and only if) your "
    "LANGUAGE SHAPE puts it there.\n"
    "- user_code: ONLY the single function the learner implements. Nothing else — no stdin "
    "reads, no prints, no other declarations. Give it a stub body (a `// TODO`/`pass` plus a "
    "dummy return) that COMPILES and runs without crashing but need not be correct. The "
    "signature MUST use precise, fully declared types, never a stringly-typed stand-in. This "
    "is the learner's ONLY view of the shapes involved: user_code is the one fragment they "
    "are shown, so a vague parameter type is a guess they have to make.\n"
    "- STRUCTURE COMMENT: if any parameter or the return value is a non-trivial structure "
    "(tree node, linked-list node, graph node, custom struct), user_code opens with a "
    "minimal comment directly above the signature restating that definition exactly as "
    "pre_code declares it — the shape only, no prose about the algorithm. e.g. python "
    "`# Definition for a binary tree node.\\n# class TreeNode:\\n#     def __init__(self, "
    "val=0, left=None, right=None): ...`. The same comment appears verbatim in "
    "reference_user_code. The type itself is DECLARED in pre_code, and pre_code/post_code "
    "are solely responsible for building it from stdin and serialising the answer back to "
    "text — never user_code.\n"
    "- post_code: everything that runs AFTER the learner's function — it calls the function "
    "and prints the result, plus the stdin parsing if your LANGUAGE SHAPE puts it there.\n"
    "- reference_user_code: the exact same signature as user_code (identical function/"
    "method name, identical parameter names, order, and types, identical return type) but "
    "with the correct working solution instead of the stub. Used only to validate the "
    "problem before any learner ever sees it — it is never shown to a learner.\n\n"

    "CONSISTENCY RULES (violating any of these produces a program that fails to compile or "
    "run, and the problem will be discarded):\n"
    "1. The function/method name and full parameter list must be IDENTICAL, character-for-"
    "character, across user_code, reference_user_code, and the call site in post_code.\n"
    "2. Every variable pre_code parses from stdin (Python) and every variable post_code's "
    "main() parses from stdin (C/C++/Java) that is passed to the function must use that "
    "exact name and that exact order — no renaming, no reordering. A leading count read "
    "purely to know how many values follow (e.g. `n` before an array) may be parsed and then "
    "left unpassed if the array's own length already tells the function everything it needs "
    "— but when that's the plan, do not pass a redundant `n` OR document it in input_format "
    "either; input_format only ever lists actual function parameters (see below).\n"
    "3. RETURN THE NATURAL TYPE, FORMAT IN post_code. The function returns the answer as a "
    "real typed value in your language's natural collection/bool/int type — never a "
    "pre-formatted string standing in for a collection (returning `\"1 2 3\"` instead of a "
    "list makes the learner's job string formatting), and never a collection to express a "
    "scalar. ALL text formatting lives in post_code, in the exact form your LANGUAGE SHAPE "
    "gives. Booleans print as lowercase `true`/`false` in every language; no-answer-exists "
    "prints `-1` or an empty line, whichever your examples state. post_code prints EXACTLY "
    "one thing, and its printed form must match your example outputs character-for-"
    "character.\n"
    "4. Never put parsing logic in user_code/reference_user_code and never put solution "
    "logic in pre_code or post_code — the split is strict.\n"
    "5. EXACTLY ONE CORRECT OUTPUT PER INPUT. The learner is graded by comparing their "
    "printed output against the reference's, character for character, so a question with "
    "several equally valid answers marks correct solutions wrong. Never write 'return any "
    "valid answer', 'if there are multiple answers return any of them', or 'any order is "
    "accepted'. When the natural question genuinely admits several answers, CONSTRAIN it "
    "until one survives, and say so in the statement: ask for the lexicographically "
    "smallest valid answer, require the result sorted, fix the tie-break rule explicitly "
    "(smallest index first), or ask for the COUNT or the length instead of one of the "
    "answers. A topological order, a set of paths, a grouping and a subsequence all need "
    "this. Your reference must then implement that exact rule, not merely happen to "
    "produce one acceptable answer.\n\n"
)

# The only language-specific text in this file, and the only thing that changes when a
# language is added: one entry per Language value, each carrying that language's fragment
# shape, its printing idiom, and one worked example aimed at what actually breaks in it.
# Exactly ONE entry is sent per call, so a C generation no longer pays for Python's rules.
_LANGUAGE_BLOCKS: dict[str, str] = {
    "python": (
        "LANGUAGE SHAPE (python):\n"
        "- pre_code: imports and any class declarations, then top-level stdin reads into "
        "named variables (`nums = list(map(int, input().split()))`) — Python is the one "
        "language here that allows free top-level statements, so the parsing lives here.\n"
        "- user_code: one `def solve(...) -> <type>:` with EVERY parameter and the return "
        "annotated, preferring builtin generics (`list`, `dict`, `tuple`, `X | None`) over "
        "`typing` imports — if a `typing` name is genuinely needed, pre_code imports it.\n"
        "- post_code: `result = solve(...)` called with the exact variables pre_code parsed, "
        "then the print matching the return type: `print(result)` for a scalar, "
        "`print(\" \".join(map(str, result)))` for a list (a bare `print(result)` on a list "
        "prints `[1, 2]` and contradicts your own examples), "
        "`print(\"true\" if result else \"false\")` for a bool.\n\n"

        "WORKED EXAMPLE (python) — a binary tree given as a level-order line where `-1` "
        "marks a missing child, return its inorder traversal. Note the typed signature, the "
        "structure comment, the LIST return, and post_code doing the formatting:\n"
        "pre_code:\n"
        "```\n"
        "from collections import deque\n\n"
        "class TreeNode:\n"
        "    def __init__(self, val=0, left=None, right=None):\n"
        "        self.val = val\n"
        "        self.left = left\n"
        "        self.right = right\n\n"
        "values = list(map(int, input().split()))\n"
        "root = None\n"
        "if values and values[0] != -1:\n"
        "    root = TreeNode(values[0])\n"
        "    queue = deque([root])\n"
        "    i = 1\n"
        "    while queue and i < len(values):\n"
        "        node = queue.popleft()\n"
        "        if i < len(values) and values[i] != -1:\n"
        "            node.left = TreeNode(values[i])\n"
        "            queue.append(node.left)\n"
        "        i += 1\n"
        "        if i < len(values) and values[i] != -1:\n"
        "            node.right = TreeNode(values[i])\n"
        "            queue.append(node.right)\n"
        "        i += 1\n"
        "```\n"
        "user_code:\n"
        "```\n"
        "# Definition for a binary tree node.\n"
        "# class TreeNode:\n"
        "#     def __init__(self, val=0, left=None, right=None):\n"
        "#         self.val = val\n"
        "#         self.left = left\n"
        "#         self.right = right\n"
        "def solve(root: TreeNode | None) -> list[int]:\n"
        "    # TODO: implement\n"
        "    return []\n"
        "```\n"
        "post_code: `print(\" \".join(map(str, solve(root))))`\n"
        "reference_user_code: same comment and same signature, with the traversal filled in "
        "and still returning a `list[int]` — the join stays in post_code.\n"
        "Against stdin `2 1 3`, this prints `1 2 3`.\n\n"
    ),
    "cpp": (
        "LANGUAGE SHAPE (cpp):\n"
        "- pre_code: the `#include` lines you need, `using namespace std;`, and any struct "
        "declarations. NO stdin reads — C++ has no free top-level statements, so all parsing "
        "happens inside main() in post_code.\n"
        "- user_code: one complete function with precise types (`vector<int>`, `TreeNode*`), "
        "taking collections by const reference.\n"
        "- post_code: a COMPLETE `int main() { ... }` that reads stdin with `cin >>`, calls "
        "solve, prints, and returns 0. Print a vector with a space-separated loop, a bool as "
        "`cout << (result ? \"true\" : \"false\") << endl;`.\n\n"

        "WORKED EXAMPLE (cpp) — read n, then n integers, return the running prefix sums. "
        "Note that main() does ALL the parsing and ALL the formatting:\n"
        "pre_code:\n"
        "```\n"
        "#include <iostream>\n"
        "#include <vector>\n"
        "using namespace std;\n"
        "```\n"
        "user_code:\n"
        "```\n"
        "vector<int> solve(const vector<int>& nums) {\n"
        "    // TODO: implement\n"
        "    return {};\n"
        "}\n"
        "```\n"
        "post_code:\n"
        "```\n"
        "int main() {\n"
        "    int n;\n"
        "    cin >> n;\n"
        "    vector<int> nums(n);\n"
        "    for (int i = 0; i < n; i++) cin >> nums[i];\n"
        "    vector<int> result = solve(nums);\n"
        "    for (size_t i = 0; i < result.size(); i++) {\n"
        "        if (i > 0) cout << ' ';\n"
        "        cout << result[i];\n"
        "    }\n"
        "    cout << endl;\n"
        "    return 0;\n"
        "}\n"
        "```\n"
        "reference_user_code: the same signature with the sums filled in.\n"
        "Against stdin `3\\n1 2 3` this prints `1 3 6`. `n` is read only to size the vector "
        "and is NOT a parameter, so it is not a line in input_format either.\n\n"
    ),
    "java": (
        "LANGUAGE SHAPE (java):\n"
        "- pre_code: imports (`import java.util.Scanner;`), then an UNCLOSED "
        "`public class Main {`. Any helper class is declared as a `static` nested class "
        "inside it. NO stdin reads — parsing happens inside main() in post_code.\n"
        "- user_code: exactly one complete `static <type> solve(...) { ... }` method with its "
        "own matched braces and precise types (`int[]`, `List<Integer>`, `TreeNode`).\n"
        "- post_code: `public static void main(String[] args) { ... }` that reads stdin with "
        "Scanner, calls solve, prints, and then the FINAL `}` that closes the class pre_code "
        "opened — forget it and nothing compiles. Print an int[] with a StringBuilder loop, a "
        "boolean with `System.out.println(result)` (already lowercase).\n\n"

        "WORKED EXAMPLE (java) — read n, then n integers, return the running prefix sums. "
        "Note the unclosed class in pre_code and the closing brace at the end of post_code:\n"
        "pre_code:\n"
        "```\n"
        "import java.util.Scanner;\n\n"
        "public class Main {\n"
        "```\n"
        "user_code:\n"
        "```\n"
        "    static int[] solve(int[] nums) {\n"
        "        // TODO: implement\n"
        "        return new int[0];\n"
        "    }\n"
        "```\n"
        "post_code:\n"
        "```\n"
        "    public static void main(String[] args) {\n"
        "        Scanner scanner = new Scanner(System.in);\n"
        "        int n = scanner.nextInt();\n"
        "        int[] nums = new int[n];\n"
        "        for (int i = 0; i < n; i++) nums[i] = scanner.nextInt();\n"
        "        int[] result = solve(nums);\n"
        "        StringBuilder sb = new StringBuilder();\n"
        "        for (int i = 0; i < result.length; i++) {\n"
        "            if (i > 0) sb.append(' ');\n"
        "            sb.append(result[i]);\n"
        "        }\n"
        "        System.out.println(sb.toString());\n"
        "    }\n"
        "}\n"
        "```\n"
        "reference_user_code: the same signature with the sums filled in.\n"
        "Concatenated this is one valid Main.java; against stdin `3\\n1 2 3` it prints "
        "`1 3 6`. `n` is read only to size the array and is NOT a parameter, so it is not a "
        "line in input_format either.\n\n"
    ),
    "c": (
        "LANGUAGE SHAPE (c):\n"
        "- pre_code: the `#include` lines you need plus any struct/typedef, nothing left "
        "open. NO stdin reads — parsing happens inside main() in post_code.\n"
        "- user_code: one complete function with precise types.\n"
        "- COLLECTION ANSWERS: C cannot safely return an array, so when the answer is a "
        "collection there is exactly ONE permitted idiom — a caller-allocated out-array plus "
        "an int return giving how many values were written: "
        "`int solve(const int* nums, int n, int* out)`. post_code allocates `out` large "
        "enough, calls solve, and prints exactly the returned count of values. NEVER malloc "
        "inside solve and return the pointer, never use a global, never report the length "
        "through another pointer parameter. Because the function genuinely needs the length, "
        "`n` IS a real parameter here and DOES belong in input_format.\n"
        "- post_code: a COMPLETE `int main(void) { ... }` that scanfs the input, calls solve, "
        "prints, and returns 0. Print a bool as "
        "`printf(\"%s\\\\n\", result ? \"true\" : \"false\");`.\n\n"

        "WORKED EXAMPLE (c) — read n, then n integers, return the running prefix sums. Note "
        "the out-array idiom and the count return:\n"
        "pre_code:\n"
        "```\n"
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "```\n"
        "user_code:\n"
        "```\n"
        "int solve(const int* nums, int n, int* out) {\n"
        "    // TODO: implement\n"
        "    return 0;\n"
        "}\n"
        "```\n"
        "post_code:\n"
        "```\n"
        "int main(void) {\n"
        "    int n;\n"
        "    if (scanf(\"%d\", &n) != 1) return 0;\n"
        "    int* nums = malloc(n * sizeof(int));\n"
        "    for (int i = 0; i < n; i++) scanf(\"%d\", &nums[i]);\n"
        "    int* out = malloc(n * sizeof(int));\n"
        "    int count = solve(nums, n, out);\n"
        "    for (int i = 0; i < count; i++) {\n"
        "        if (i > 0) printf(\" \");\n"
        "        printf(\"%d\", out[i]);\n"
        "    }\n"
        "    printf(\"\\\\n\");\n"
        "    free(nums);\n"
        "    free(out);\n"
        "    return 0;\n"
        "}\n"
        "```\n"
        "reference_user_code: the same signature, writing the sums into `out` and returning "
        "`n`.\n"
        "Against stdin `3\\n1 2 3` this prints `1 3 6`.\n\n"
    ),
}


def _language_block(language: str) -> str:
    """The shape and worked example for one language. A language with no entry yet (a new
    Language value added before its block is written) falls back to all of them rather than
    to nothing — verbose, but the model still sees a valid shape to copy."""
    return _LANGUAGE_BLOCKS.get(language) or "".join(_LANGUAGE_BLOCKS.values())

# Everything here describes a field ProblemPatch cannot return, so repairs skip it.
_AUTHORING_EXTRAS = (
    "Also produce these as their OWN fields — never restate them inside statement_md, "
    "which is the problem description only:\n"
    "- constraints: input value ranges and input-size bounds ONLY. Do NOT state the "
    "expected time or space complexity: naming the target complexity names the approach, "
    "which is most of the exercise. Use the hints for that instead.\n"
    "- input_format: derive this from user_code's parameter list, not from stdin "
    "independently. One line per function parameter (separated by \\n), in parameter order, "
    "using that exact parameter's name and type — never a stdin variable that has no "
    "matching parameter (e.g. a separate count `n` when the function only takes the list; "
    "if pre_code/post_code needs to read a count to know how many values follow, that "
    "reading is internal parsing detail and is NOT a line in input_format, since it is not "
    "part of what solve() receives). No prose, no blank lines.\n"
    "- output_format: same style as input_format — one point per line, separated by \\n, "
    "concise. Cover what the function returns (type included) and what the single printed "
    "line looks like.\n\n"

    "Then 1-3 progressive hints ordered from a gentle nudge to a stronger hint, "
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

def problem_system_prompt(language: str) -> str:
    """Only the target language's shape and worked example ride along. Sending all four —
    as this did — spent most of the code budget on languages the call cannot produce, and
    left no room for a worked example of the case that actually fails (a collection or a
    structure in c/cpp/java)."""
    return (
        _PROBLEM_INTRO
        + _EXAMPLE_FORMAT
        + _CODE_SHAPE
        + _language_block(language)
        + _AUTHORING_EXTRAS
        + _HIDDEN_TESTS
        + _INPUT_RULES
    )


def patch_system_prompt(language: str) -> str:
    """What a repair actually needs: how the fragments fit together, the language's own
    shape, and the rules covering the fields ProblemPatch can return (code, examples,
    hidden_tests, statement). It is NOT writing a new problem, so the authoring intro and
    the hints/tags/stress-test rules are left out. The worked example stays — for a compile
    failure it is the single most useful thing in the prompt, being a concatenation known
    to build."""
    return (
        "You repair one DSA practice problem that failed automated validation. You are not "
        "writing a new problem — the question stays exactly as it is.\n\n"
        + _EXAMPLE_FORMAT
        + _CODE_SHAPE
        + _language_block(language)
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
    "program.\n"
    "5. Keep the typed signature and the structure comment. Never repair a failure by "
    "dropping type hints or by weakening the return type into a pre-formatted string — the "
    "formatting belongs in post_code, and that is where the fix goes."
)


# One entry per FailureKind (app.problems.application.repair), and the only place a failure
# kind is described. test_problem_prompts asserts the two stay in step.
_DIAGNOSIS: dict[str, str] = {
    "compile": "Your fragments do NOT compile, so nothing ran at all. The compiler's own "
    "output is below, and its line numbers refer to the numbered program that follows it — "
    "the single file your four fragments concatenate into. Find the named line, see which "
    "fragment it falls in, and fix that fragment. For java that is usually the class brace "
    "(pre_code opens `public class Main {` and post_code must close it); for c/cpp a missing "
    "include or a type that does not match the call in main().",
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
}


def patch_problem_user_prompt(
    kind: str, detail: str, language: str, problem: GeneratedProblem
) -> str:
    """A repair prompt for a problem that already failed the sandbox. Carries the minimum
    that can explain the failure: the harness, the tests, and what actually happened.

    Which sections a kind needs is decided HERE and nowhere else, so the caller passes the
    whole problem and never reasons about it."""
    sections = [
        f"Language: {language}",
        f"THIS PROBLEM FAILED VALIDATION.\n{_DIAGNOSIS[kind]}",
        f"WHAT HAPPENED:\n{detail}",
    ]

    # Only a mismatch disagrees with the statement, so only it needs the statement.
    if kind == "mismatch":
        sections.append(f"statement_md:\n{problem.statement_md}")

    if kind == "compile":
        # One numbered file, so the compiler's line numbers resolve.
        sections.append(
            "THE PROGRAM THE COMPILER SAW (pre_code + reference_user_code + post_code):\n"
            + annotated_program(
                problem.pre_code, problem.reference_user_code, problem.post_code
            )
        )
    else:
        sections.append(f"pre_code:\n{problem.pre_code}")
        # The stub matters only when the fix is about the stdin format it is written against.
        if kind == "no_tests":
            sections.append(f"user_code:\n{problem.user_code}")
        sections.append(f"reference_user_code:\n{problem.reference_user_code}")
        sections.append(f"post_code:\n{problem.post_code}")

    sections.append(
        "examples:\n"
        + "\n".join(f"- input={ex.input!r} output={ex.output!r}" for ex in problem.examples)
    )
    sections.append(
        "hidden_tests (inputs only):\n"
        + "\n".join(f"- {value!r}" for value in problem.hidden_tests)
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
        "constraints, input_format, output_format, hints, tags, skills) follows the same "
        "rules as always.\n\n"
        f"The learner's problem:\n{source_problem}"
    )
