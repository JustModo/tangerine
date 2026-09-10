from app.llm.schemas.problem import GeneratedProblem
from app.shared.code_assembly import annotated_program, assemble_program

_PROBLEM_INTRO = (
    "You write a single DSA practice problem for a given skill, language, and difficulty. "
    "Produce a clear statement (markdown), 2-4 worked examples, and the problem's code as "
    "four separate fragments: pre_code, user_code, post_code, and reference_user_code.\n\n"

    "WRITE A CONTEST PROBLEM, NOT A STORY AND NOT A TEXTBOOK EXERCISE. The register is a "
    "competitive-programming statement: flat declarative sentences, one fact each, stacked "
    "up until the rules are completely pinned down. Concrete nouns are good — cities, "
    "computers, tables, trucks, a grid — but they carry NO motivation and NO narrative. "
    "Concrete does NOT mean realistic: lasers fired across a grid, robots on tiles, tokens "
    "on a board, switches, coloured stones, a beam that stops at the first wall are all "
    "excellent setups. An invented toy world is often clearer than a plausible one, because "
    "nothing about it has to be justified. Pick whatever makes the rules easiest to state. "
    "\"There are `n` computers and `m` bidirectional connections.\" is the correct opening. "
    "\"A regional power grid distributes electricity through a hierarchical network of "
    "substations, and technicians measuring signal delay need to...\" is not: nobody wants "
    "or needs anything, there are no researchers, engineers, astronomers or analysts, and "
    "no sentence exists to set a scene.\n\n"

    "THE DIFFICULTY LIVES IN THE THINKING, NOT THE PROSE. A question earns it in one of two "
    "ways, and both are good:\n"
    "(a) ONE CLEAN IDEA, well posed. Few rules, nothing awkward, but the answer needs a real "
    "insight — count how many boxes a laser crosses before it stops; find where two walkers "
    "on a board must meet. If the idea is genuinely interesting, a short question with three "
    "rules is a better question than a long one with seven.\n"
    "(b) RULES THAT INTERACT, where one condition cuts against the obvious approach:\n"
    "- \"You may visit a cell multiple times. However, a cell can be used at most once in "
    "the final path.\"\n"
    "- \"You cannot visit two cities whose indices differ by exactly 1.\"\n"
    "- \"You are allowed to unlock at most `k` locked computers. Once unlocked, a computer "
    "stays unlocked.\"\n"
    "- \"All pairs of the same number must belong to the same group.\"\n"
    "Each is one plain sentence, and each forces the solver to carry extra state.\n\n"

    "USE THE FEWEST RULES THAT MAKE THE QUESTION INTERESTING. Piling on conditions is not "
    "the same as making a question harder — it usually just makes it longer and more "
    "annoying to read. Every rule must earn its place by changing what a correct answer "
    "looks like; if removing one leaves the question just as interesting, remove it. Two or "
    "three sharp rules beat six mediocre ones every time.\n\n"

    "STATEMENT SHAPE:\n"
    "1. The setup, declaratively. `n` of this, `m` of that, what each index means.\n"
    "2. The rules, one per sentence — or as a markdown bullet list when you are enumerating "
    "options such as the legal moves. Introduce the awkward rule with \"However,\" or "
    "\"You may ... at most ...\" so it lands as a restriction and not as decoration.\n"
    "3. What to compute, stated once and exactly.\n"
    "4. The degenerate case, when one exists: \"If the destination cannot be reached, "
    "return -1.\"\n\n"

    "MARKDOWN AND NAMES. Every variable, index and array in the statement is written in "
    "backticks and uses the EXACT parameter name from user_code — `grid[i][j]`, `A[i]`, "
    "`k`, `n`. Never rename a parameter in prose, never say \"the array\" when you can say "
    "`heights`. Use a bullet list for enumerated options and blank lines between the setup, "
    "the rules and the objective. It renders as markdown, so this costs nothing and makes "
    "the conditions scannable.\n\n"

    "PLAIN WORDS. Write it the way you would explain it out loud. Ordinary vocabulary, "
    "short sentences, one idea each. The question must be hard to SOLVE, never hard to "
    "READ, and a reader should never have to work out what a sentence means. Say \"number\" "
    "not \"integer quantity\", \"at most\" not \"not exceeding\", \"you cannot\" not \"it is "
    "prohibited to\", \"cost\" not \"weighted expenditure metric\". Avoid academic register "
    "entirely — no aggregates, parametric, monotonic, induced, cardinality, topology, "
    "canonical, frontier, predicate, sub-network. If a plainer word is exact, it is the "
    "right word.\n\n"

    "LENGTH: 80-180 words. Longer than a textbook one-liner because the rules need room; "
    "shorter than a page because none of the words are scenery.\n\n"

    "title: NAME THE OBJECT OR THE OBJECTIVE, 3-6 plain words — 'Minimum Energy Path', "
    "'Locked Network', 'Maximum Profit Journey', 'Table Arrangement'. Plain like those, "
    "never impressive: 'Restricted Bandwidth Circuit Network' and 'Subgrid Energy "
    "Collector' are the wrong register. NEVER name the data structure, the algorithm or the complexity ('Two Sum "
    "with Hash Map', 'Bitmask DP Partition' are forbidden): the title is the first hint you "
    "give away, and naming the tool finishes the exercise before it starts. Never a full "
    "sentence.\n\n"

    "NEVER DESCRIBE THE MACHINERY. The statement says WHAT is given and WHAT must be "
    "computed, in terms of the problem's own objects. Choosing the method is the exercise, "
    "so the statement must not name the machinery a solution would use — no sort, stack, "
    "queue, heap, hash map, sliding window, two pointers, prefix sum, memoisation, "
    "recursion, binary search, dynamic programming or greedy — and must not describe one "
    "in disguise either: \"push it on and pop it when it matches\" is a stack, \"put them in "
    "increasing order first\" is a sort. The SHAPE of the input is not machinery and is "
    "named plainly: a grid is a grid, a tree is a tree, a graph is a graph — never a "
    "euphemism invented to dodge this rule. Never name a complexity target, and never nudge "
    "with 'consider processing from the right' or 'you may want to track a running "
    "maximum'. Equally, never state something false or impossible about the setup to "
    "manufacture difficulty: every rule must be satisfiable and must matter.\n\n"

    "State each rule exactly once, in one consistent framing, and stop. Never think out "
    "loud while writing — no 'wait', no second-guessing a definition mid-paragraph, no "
    "'specifically' walkback that redefines what was just said. A single \"More formally,\" "
    "sentence restating one rule in symbols is correct and is not a walkback; a second, "
    "different definition of the same rule is.\n\n"
)

_EXAMPLE_FORMAT = (
    "Each example's explanation: 2-4 short lines separated by \\n (a real multi-line "
    "string), each under ~15 words. Show the arithmetic that turns THIS input into THIS "
    "output, in the order a solver would do it, ending on the stated output.\n"
    "- Do the maths first and check it. Every number you write must be correct; a wrong "
    "intermediate value is worse than giving no explanation at all.\n"
    "- Show the work, never assert the result: `12 -> 1 x 2 = 2, prime`, not 'four numbers "
    "satisfy the condition'. If listing every qualifying item is too long, show two worked "
    "and give the count.\n"
    "- Never name the approach or technique. No 'use dynamic programming', 'two pointers', "
    "'greedy', 'we check each number in the range'. The explanation justifies the ANSWER, "
    "not the method, and the method is what the learner is meant to find.\n"
    "- No restating the question, no closing line that repeats the output as prose.\n"
    "- Never think out loud. No 'wait', 'let us check', no mid-text correction, no "
    "hedging, no question marks. Write only the finished reasoning.\n"
    "- It renders as markdown, so a bare `*` becomes italics: write products as `1 x 2` or "
    "wrap the expression in backticks. Same for `_`.\n\n"
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
    """Format the shape and worked example for a programming language."""
    return _LANGUAGE_BLOCKS.get(language) or "".join(_LANGUAGE_BLOCKS.values())


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


_INTERVIEW_TWIST = (
    "BUILD IN THIS COMPLICATION: {twist}\n"
    "That line is an instruction to you, NOT text for the statement. Never quote it, never "
    "paraphrase it as an abstract sentence — a rule reading \"a cost that depends on the "
    "previous choice as well as the current one applies\" is the instruction leaking onto "
    "the page. Express it concretely in this problem's own objects and names, as one plain "
    "rule the solver can act on: \"moving from a segment of length `a` to one of length `b` "
    "costs `abs(a - b)`.\" It must change what a correct solution looks like, not merely add "
    "another input to parse. Add ONLY this one complication — the rest of the question stays "
    "as lean as it can be.\n\n"
)

_INTERVIEW_PLAIN = (
    "NO EXTRA COMPLICATION THIS TIME — WRITE THE SHORT, CLEAN ONE. One idea, posed well. "
    "The solver's work is seeing HOW to do it, not keeping track of what is allowed.\n"
    "- AT MOST THREE RULES. If you are writing a fourth, the question has got away from "
    "you; delete instead of adding.\n"
    "- 60-110 words. A statement past that is a sign you added something you did not need.\n"
    "- Do NOT bolt on a second phase, a removal sequence, a modulus, a tie-break clause, a "
    "secondary objective or a budget. Every one of those is the complication you were told "
    "not to add.\n"
    "- The setup should be something a person could picture in one sentence: a laser fired "
    "across a grid of boxes and you count how many it passes through; two markers walking a "
    "row at different speeds; water poured onto a row of columns.\n"
    "Difficulty here comes ENTIRELY from the insight the answer needs. A three-rule question "
    "somebody has to think about is exactly right, and is not a weaker question than a "
    "seven-rule one — it is usually a better one.\n"
    "- SHORT IS NOT A LICENCE TO REACH FOR A FAMOUS ONE. Daily Temperatures, Two Sum, "
    "Climbing Stairs, Best Time to Buy and Sell Stock and the rest of the catalogue are "
    "still forbidden here, and being brief is exactly when they are most tempting. Keep the "
    "clean shape and change the question.\n\n"
)

_INTERVIEW_TARGET = (
    "\n\nTEST-MODE TARGET. This is not a lesson exercise. The solver has already learned the "
    "techniques one at a time; here they are being asked to APPLY them together, the way an "
    "assessment round does. A question that is solved the moment its topic is recognised has "
    "failed, however cleanly it is written.\n\n"

    "AIM THE SOLUTION AT THESE TWO AREAS: {primary}, and {secondary}. That is a direction, "
    "not a recipe — you choose the actual question, and a good one needs both areas to be "
    "genuinely load-bearing rather than one bolted onto the other. If they will not compose "
    "into something natural, reshape the setup until they do.\n\n"

    "{complication}"

    "THE SOLVER MUST CHOOSE THE METHOD — THIS IS THE POINT OF THE EXERCISE. The statement "
    "describes objects and rules ONLY. It never names, hints at, or describes the mechanics "
    "of any SOLUTION technique. None of these may appear anywhere in the statement, the "
    "constraints, the title or the tags: the names of the two areas above, or any word "
    "rooted in them (\"bit index\" gives away bitmasking); sort, sorted, "
    "stack, queue, heap, priority, hash map, hash set, sliding window, two pointers, "
    "prefix sum, memoise, cache, recursion, binary search, dynamic programming, greedy. "
    "Nor may you describe one in disguise: \"push the value on and pop it when it matches\" "
    "is a stack, \"arrange the items in increasing order first\" is a sort. Deciding to "
    "sort, or to keep a stack, is the candidate's move and you must not make it for "
    "them.\n\n"

    "THE INPUT'S SHAPE IS NOT MACHINERY — NAME IT PLAINLY. A grid is a grid, an array is an "
    "array, a tree is a tree, a graph is a graph. Do NOT invent a euphemism to dodge the "
    "ban above: writing \"a hierarchical branching network of nodes\" instead of \"a tree\" "
    "only forces the solver to decode your wording, and the input format gives the shape "
    "away in any case. The ban is on how to SOLVE it, never on what you are GIVEN.\n\n"

    "Do not restate a well-known question either — no reskinned Two Sum, Number of Islands, "
    "Course Schedule, Coin Change or Merge Intervals. The right shape is a setup the solver "
    "has never read, whose rules force them to work out which tools apply before they can "
    "use any of them.\n\n"

    "Every other rule in your instructions still holds in full — most of all that exactly "
    "one output is correct for each input, so the objective must be a single well-defined "
    "value however intricate the rules that lead to it."
)


def problem_user_prompt(
    skill: str,
    language: str,
    difficulty: str,
    avoid_titles: list[str] | None = None,
    areas: tuple[str, str] | None = None,
    twist: str | None = None,
) -> str:
    prompt = f"Skill: {skill}\nLanguage: {language}\nDifficulty: {difficulty}"
    if avoid_titles:
        listed = "\n".join(f"- {title}" for title in avoid_titles)
        prompt += (
            "\n\nThe learner has ALREADY been given these problems for this skill. Write a "
            "genuinely different one — a different question, not a reworded version of any "
            f"of them:\n{listed}"
        )
    if areas:
        prompt += _INTERVIEW_TARGET.format(
            primary=areas[0],
            secondary=areas[1],
            complication=(
                _INTERVIEW_TWIST.format(twist=twist) if twist else _INTERVIEW_PLAIN
            ),
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
    """Format a patch repair user prompt for a rejected problem."""
    sections = [
        f"Language: {language}",
        f"THIS PROBLEM FAILED VALIDATION.\n{_DIAGNOSIS[kind]}",
        f"WHAT HAPPENED:\n{detail}",
    ]

    if kind == "mismatch":
        sections.append(f"statement_md:\n{problem.statement_md}")

    if kind == "compile":
        sections.append(
            "THE PROGRAM THE COMPILER SAW (pre_code + reference_user_code + post_code):\n"
            + annotated_program(
                problem.pre_code, problem.reference_user_code, problem.post_code
            )
        )
    else:
        sections.append(f"pre_code:\n{problem.pre_code}")
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


_ADAPT_INTRO = (
    "The learner has given you a problem they already have and want to solve. You are NOT "
    "authoring a problem — you are wrapping theirs in the harness that makes it runnable, "
    "and the question they pasted is the question they get.\n\n"

    "statement_md: REPRODUCE THE ORIGINAL VERBATIM. Copy the learner's text across "
    "character for character, keeping their wording, their order, their examples, their "
    "notation and any LaTeX exactly as written. You may only fix markdown so it renders "
    "(fencing code, escaping a bare `*` or `_`) and drop material that is not part of the "
    "question at all — a site header, a difficulty badge, 'Accepted: 42.1%', a 'Companies' "
    "list, navigation text.\n\n"

    "Do NOT rewrite it into a scenario, do NOT add a setting or a story, do NOT tighten, "
    "expand, re-order, re-phrase or 'improve' a single sentence, and do NOT strip a "
    "technique name the original chose to state. The authoring rules about writing a "
    "situation apply to problems you invent; this one is already written.\n\n"

    "THE ONE EXCEPTION IS A LOGICAL ERROR. If the original genuinely contradicts itself, "
    "states an example output that does not follow from its own input, or omits a "
    "constraint without which the task is impossible or ambiguous, correct exactly that and "
    "leave every other word untouched. A wording choice you dislike is not a logical error, "
    "and neither is a missing scenario, a terse statement, or a technique the original "
    "names outright.\n\n"

    "title: the original's own name for it if it gives one, otherwise a concise 3-6 word "
    "name taken from what the question actually asks. Do not invent a scenario title for a "
    "problem that has no scenario.\n\n"

    "IF THE ORIGINAL ALLOWS SEVERAL VALID ANSWERS — 'return them in any order', 'return any "
    "valid pair' — do NOT edit the statement to remove that freedom. Grading compares "
    "printed output character for character, so make post_code print a CANONICAL form "
    "instead: sort the collection before printing it. Every valid answer then prints "
    "identically and the learner's own wording survives untouched. Only when no canonical "
    "form exists (an arbitrary path, one of several unrelated structures) is this a logical "
    "error you may fix in the statement by fixing the tie-break rule.\n\n"
)


def adapt_system_prompt(language: str) -> str:
    """The authoring intro is deliberately absent. A pasted question is the learner's own,
    so the rules that make a NEW problem case-based would rewrite the very thing they asked
    to practise. Everything about the code shape, examples and grading inputs still holds —
    that is the part being built around their text."""
    return (
        _ADAPT_INTRO
        + _EXAMPLE_FORMAT
        + _CODE_SHAPE
        + _language_block(language)
        + _AUTHORING_EXTRAS
        + _HIDDEN_TESTS
        + _INPUT_RULES
    )


def adapt_problem_user_prompt(source_problem: str, language: str) -> str:
    """Format user prompt to adapt a user-provided problem statement."""
    return (
        f"Language: {language}\n\n"
        "Do NOT invent a new problem. Wrap the exact problem below in the required format.\n"
        "- statement_md: the learner's text, VERBATIM. Their wording, their examples, their "
        "notation, their LaTeX. No rewriting, no scenario, no re-phrasing — only markdown "
        "repair, removal of page furniture, and the correction of an outright logical "
        "error.\n"
        "- title: the original's own name if it has one, else a concise 3-6 word name.\n"
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


_CRITIQUE_INTRO = (
    "You are the editor who signs off DSA practice problems before a paying learner ever "
    "sees them. Someone else wrote the problem below against the rules that follow. Your "
    "only job is to decide whether it meets those rules, and to list precisely where it "
    "does not.\n\n"
)

_CRITIQUE_RULES = (
    "WHAT YOU ARE LOOKING FOR, in rough order of how badly it hurts:\n"
    "1. HALLUCINATION. Any claim the problem itself does not support: an example whose "
    "explanation asserts numbers that do not follow from its own input, a constraint that "
    "contradicts the input_format or the examples, a statement referring to a parameter, a "
    "field or a guarantee that appears nowhere else, an input_format line for a variable "
    "that is not a parameter of the function in user_code, or a scenario that describes "
    "something the code does not actually compute.\n"
    "2. RAMBLING AND THINKING OUT LOUD. 'wait', 'let us check', 'more precisely', "
    "'specifically', a definition restated differently the second time, a hedge, a question "
    "mark, a mid-paragraph walkback that redefines the task. The statement must ask the "
    "question exactly once, in one framing, and stop.\n"
    "3. WRONG ARITHMETIC. Work every example explanation through by hand against its own "
    "input. A single wrong intermediate value is a violation.\n"
    "4. WRONG STATEMENT SHAPE. Three distinct violations:\n"
    "   (a) NARRATIVE. Anyone wanting, needing, measuring or deciding anything; "
    "technicians, engineers, researchers, analysts or operators; a sentence explaining how "
    "the domain works or why the task matters; any clause whose only job is atmosphere. The "
    "register is a contest statement: objects and rules, no motivation.\n"
    "   (b) NOTHING TO WORK OUT, or CONDITIONS FOR THEIR OWN SAKE. Two opposite defects. "
    "Flag a question whose whole content is one textbook routine applied once with nothing "
    "to see — that is a lesson exercise. But equally flag rules piled on without earning "
    "their place: if a condition could be deleted and the question stays just as "
    "interesting, it is padding and should be named as such. A short question built on one "
    "genuine insight is CORRECT and must never be flagged merely for being short or for "
    "having few rules.\n"
    "   (c) UNGROUNDED NAMES. Variables not written in backticks, or prose that renames a "
    "user_code parameter instead of using it, or no plain statement of what to return, or "
    "no stated behaviour for the degenerate case when one clearly exists.\n"
    "   (d) HARD TO READ RATHER THAN HARD TO SOLVE. Academic or inflated vocabulary where a "
    "plain word is exact — aggregates, parametric, monotonic, induced, cardinality, "
    "topology, canonical, frontier, sub-network — long winding sentences, or a title that "
    "reaches for impressive words. Quote the phrase and give the plain word it should be. "
    "Difficulty belongs in the rules, never in the reading.\n"    "5. THE STATEMENT GIVES THE APPROACH AWAY. This is the most damaging defect, because it "
    "removes the entire exercise. Flag any data structure or operation named in "
    "statement_md, constraints, title or tags — sort, stack, queue, heap, priority, hash "
    "map, sliding window, two pointers, prefix sum, memoise, cache, recursion, binary "
    "search, dynamic programming, greedy — and any of them DESCRIBED without being named: "
    "\"push the value on and "
    "remove it when it matches\" is a stack, \"arrange them in increasing order first\" is a "
    "sort, \"store each result so it is not recomputed\" is memoisation. Also flag a named "
    "complexity target and any nudge toward the method. Deciding how to solve it is the "
    "candidate's move; the statement only sets the rules. Do NOT flag the plain naming of "
    "the input's own shape — a grid, an array, a tree, a graph — that is what the solver is "
    "given, not how they solve it. DO flag a euphemism invented to dodge naming it, such as "
    "\"a hierarchical branching network\" for a tree.\n"
    "6. UNPROFESSIONAL CRAFT. An untyped or stringly-typed signature in user_code, a "
    "signature that differs from reference_user_code, a missing structure comment where a "
    "non-trivial type is involved, parsing logic inside user_code, formatting inside the "
    "function instead of post_code, a stub that would not run, a question admitting several "
    "equally valid answers, or an example explanation that names the technique.\n\n"

    "DO NOT REJECT FOR:\n"
    "- A hint naming a technique. The hints are the ONE place the approach is allowed to be "
    "named — that is what they are for. Only the statement, the title, the constraints and "
    "the example explanations must stay free of it.\n"
    "- A statement being flat, dry and entirely unmotivated. That is the target register, "
    "not a defect. \"There are `n` computers and `m` bidirectional connections.\" needs no "
    "scene setting and must never be flagged for lacking one.\n"
    "- Rules being numerous or intricate, as long as each is stated once and is "
    "satisfiable. Conditions that interact are the point of a test question.\n"
    "- A single \"More formally,\" sentence restating the rule precisely. That is the "
    "expected shape, not a walkback — a walkback is a SECOND, DIFFERENT definition.\n"
    "- Style, tone or wording you would merely have written differently.\n"
    "- Difficulty being easier or harder than the label suggests.\n"
    "- The reference solving the problem by a different but valid algorithm, or being "
    "unoptimised, as long as it is correct.\n"
    "- The topic resembling a well-known problem, or resembling another problem you have "
    "seen. A familiar underlying task dressed in a genuinely different situation is exactly "
    "what is wanted, and is never a violation.\n"
    "- Anything only running the code could settle. You do not execute anything; you read "
    "it. A sandbox already checks that the program compiles, runs and matches its examples, "
    "so never guess at runtime behaviour and never flag a suspicion you cannot point at a "
    "specific line for.\n\n"

    "Report one violation per line, each naming the offending field first. Be specific "
    "enough that someone can fix it without seeing your reasoning: quote the offending "
    "phrase or the wrong number. If nothing above applies, approve it — a problem with no "
    "defects is the expected case, and inventing a violation to look thorough is worse than "
    "missing one."
)


def critique_system_prompt(language: str) -> str:
    return (
        _CRITIQUE_INTRO
        + _EXAMPLE_FORMAT
        + _CODE_SHAPE
        + _language_block(language)
        + _AUTHORING_EXTRAS
        + _HIDDEN_TESTS
        + _INPUT_RULES
        + "\n\n"
        + _CRITIQUE_RULES
    )


def _problem_evidence(problem: GeneratedProblem) -> list[str]:
    return [
        f"title:\n{problem.title}",
        f"statement_md:\n{problem.statement_md}",
        f"constraints:\n{problem.constraints}",
        f"input_format:\n{problem.input_format}",
        f"output_format:\n{problem.output_format}",
        "examples:\n"
        + "\n".join(
            f"- input={ex.input!r} output={ex.output!r} explanation={ex.explanation!r}"
            for ex in problem.examples
        ),
        "hidden_tests (inputs only):\n"
        + "\n".join(f"- {value!r}" for value in problem.hidden_tests),
        "hints:\n" + "\n".join(f"- {hint}" for hint in problem.hints),
        f"user_code (the only fragment the learner is shown):\n{problem.user_code}",
        "THE PROGRAM THAT WILL BE RUN (pre_code + reference_user_code + post_code):\n"
        + assemble_program(problem.pre_code, problem.reference_user_code, problem.post_code),
    ]


def critique_user_prompt(problem: GeneratedProblem, source_problem: str | None = None) -> str:
    sections = [f"difficulty as claimed: {problem.difficulty}", *_problem_evidence(problem)]
    if source_problem:
        sections.append(
            "THIS PROBLEM IS THE LEARNER'S OWN, PASTED. statement_md is required to "
            "reproduce the original below VERBATIM, so judge it only against that original "
            "and never against the house style.\n"
            "- Flag statement_md if it rewrites, re-phrases, re-orders, summarises, expands "
            "or adds a scenario to the original, or if it quietly changes, softens or "
            "invents part of the task. Quote the words that differ.\n"
            "- Do NOT flag statement_md for lacking a situation, for being terse, for "
            "opening 'Given an array', or for naming a technique. Those are the learner's "
            "choices and reproducing them is correct. Removing page furniture (a difficulty "
            "badge, an acceptance rate, a company list) is also correct.\n"
            "- Everything BUILT AROUND the statement — the code fragments, examples, "
            "constraints, formats, hints, grading inputs — is judged normally.\n\n"
            f"THE LEARNER'S ORIGINAL:\n{source_problem}"
        )
    return "\n\n".join(sections)


_REVISION_RULES = (
    "REVISION RULES:\n"
    "1. Return ONLY the fields you actually changed. Leave everything else null — it is kept "
    "as-is. A revision that restates unchanged content is wasted.\n"
    "2. Fix exactly what was flagged and nothing else. You are not rewriting the problem, "
    "improving its style, or making it harder. Every violation must be addressed; nothing "
    "else may move.\n"
    "3. Do NOT change the question. Same task, same input format, same example INPUTS. A "
    "wrong stated output or a wrong explanation is corrected; the question never is.\n"
    "4. Never resolve a violation by deleting the content it names — do not drop an "
    "explanation to avoid fixing its arithmetic, drop a hint to avoid rewording it, or weaken "
    "a test. Fix the actual defect.\n"
    "5. The CONSISTENCY RULES and the PER-LANGUAGE SHAPE from your instructions still apply "
    "to anything you return: fragments must still concatenate into one valid program, and the "
    "typed signature and structure comment stay."
)


def revise_system_prompt(language: str) -> str:
    return (
        "You repair one DSA practice problem that an editor has just rejected. The problem "
        "is sound apart from the defects listed — you are correcting those, not writing a new "
        "problem.\n\n"
        + _EXAMPLE_FORMAT
        + _CODE_SHAPE
        + _language_block(language)
        + _AUTHORING_EXTRAS
        + _HIDDEN_TESTS
        + _INPUT_RULES
        + "\n\n"
        + _REVISION_RULES
    )


def revise_problem_user_prompt(
    problem: GeneratedProblem, violations: list[str], source_problem: str | None = None
) -> str:
    listed = "\n".join(f"- {violation}" for violation in violations)
    sections = [
        f"THIS PROBLEM WAS REJECTED. The editor found:\n{listed}",
        *_problem_evidence(problem),
    ]
    if source_problem:
        sections.append(
            "This problem is an adaptation of the learner's own question below. Do NOT return "
            "statement_md — the question stays exactly as the learner wrote it, and any "
            f"violation must be fixed elsewhere.\n\nTHE LEARNER'S ORIGINAL:\n{source_problem}"
        )
    return "\n\n".join(sections)
