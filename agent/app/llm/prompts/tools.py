from app.llm.domain.requests import ToolDeclaration
from app.shared.types import SUPPORTED_LANGUAGES, Language

GENERATE_PLAN_TOOL = ToolDeclaration(
    name="generate_learning_plan",
    description=(
        "Generate or regenerate the structured learning plan/curriculum for this "
        "session once the user has confirmed what they want."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "The DSA topic or skill area to build a curriculum for. If the user "
                    "signalled how deep to go ('in-depth', 'thorough', 'quick', 'just the "
                    "basics', 'simple'), fold that qualifier into this string, e.g. 'graphs "
                    "(in-depth)' or 'two pointers (quick overview)' — the curriculum "
                    "generator reads it from here to size the plan."
                ),
            },
            "language": {
                "type": "string",
                "enum": [language.value for language in Language],
                "description": (
                    "Programming language for the practice problems. Set this ONLY to a "
                    "language the user actually stated. Never guess or default — if they "
                    "haven't said, omit it and ask them instead."
                ),
            },
            "level": {
                "type": "string",
                "description": "Skill level to start at, e.g. beginner, intermediate, advanced.",
            },
            "step_count": {
                "type": "integer",
                "description": (
                    "Only set this if the user explicitly asked for a specific number of "
                    "steps/lessons ('just one problem', 'two lessons'). Omit otherwise and "
                    "a sensible length is chosen for them."
                ),
            },
            "target_problem": {
                "type": "string",
                "description": (
                    "If the user pasted a specific coding problem they want to solve (e.g. "
                    "from LeetCode), put its FULL text here verbatim. The curriculum then "
                    "becomes prerequisite steps leading up to it, with that exact problem "
                    "as the final step. Omit when they only named a topic."
                ),
            },
        },
        "required": ["topic", "level"],
    },
)

EDIT_PLAN_TOOL = ToolDeclaration(
    name="edit_learning_plan",
    description=(
        "Change one specific thing about the EXISTING learning plan, or rework it broadly. "
        "Pick the operation that matches what the user asked for EXACTLY — most requests "
        "are one of the structured operations below, applied instantly with no other step "
        "touched; 'rework' is the fallback for requests that genuinely don't fit one of "
        "them. Use this instead of generate_learning_plan whenever a plan already exists "
        "and the user wants it changed rather than replaced from scratch."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "change_language",
                    "change_step_difficulty",
                    "add_step",
                    "add_problem",
                    "remove_step",
                    "reorder_step",
                    "regenerate_problem",
                    "rework",
                ],
                "description": (
                    "change_language: switch what language the whole plan's remaining "
                    "problems generate in ('swap this to Python', 'do it in Java instead') "
                    "— requires language.\n"
                    "change_step_difficulty: make one existing step easier/harder "
                    "('make step 3 harder') — requires step and difficulty.\n"
                    "add_step: insert a new step on a TOPIC, whose problem is generated "
                    "fresh ('add one on hash maps') — requires skill, optionally difficulty "
                    "and position.\n"
                    "add_problem: put a problem they ALREADY have onto the plan, so they "
                    "can work it there ('I want to solve that one', 'add the two sum one') "
                    "— requires problem_id from a find_problems result. Nothing is "
                    "generated; the step opens that exact question.\n"
                    "remove_step: drop one existing step ('drop the recursion step') — "
                    "requires step.\n"
                    "reorder_step: move one existing step to a different position "
                    "('move step 4 to the start') — requires step and to_position.\n"
                    "regenerate_problem: throw away the QUESTION on one step and get a "
                    "different one ('this question is wrong', 'give me another problem for "
                    "step 5', 'regenerate that') — requires step. The step itself stays; "
                    "only the question is replaced, and it is written fresh when they next "
                    "open that step. This is the ONLY operation that touches a question — "
                    "rework cannot, and no operation can edit a statement or a test case.\n"
                    "rework: anything that doesn't fit the above — a genuinely broad "
                    "change ('redo the whole thing around graphs', 'focus more on "
                    "interview patterns') — requires instruction."
                ),
            },
            "language": {
                "type": "string",
                "enum": [language.value for language in Language],
                "description": "change_language only: the language to switch the plan to.",
            },
            "step": {
                "type": "string",
                "description": (
                    "change_step_difficulty/remove_step/reorder_step/regenerate_problem "
                    "only: which existing "
                    "step, EXACTLY as the user identified it — its number as shown in the "
                    "plan (e.g. '3') or its skill/topic name (e.g. 'hash maps'). Never "
                    "guess a step the user didn't name."
                ),
            },
            "difficulty": {
                "type": "string",
                "enum": ["easy", "medium", "hard"],
                "description": "change_step_difficulty: the step's new difficulty. add_step: the new step's difficulty, if the user said one.",
            },
            "skill": {
                "type": "string",
                "description": "add_step only: the exact topic/skill of the new step, faithful to what the user asked for.",
            },
            "problem_id": {
                "type": "string",
                "description": (
                    "add_problem only: the exact id from a find_problems result. Never "
                    "invent one — call find_problems first if you do not have it."
                ),
            },
            "position": {
                "type": "integer",
                "description": (
                    "add_step only: 1-indexed position to insert at, ONLY if the user said "
                    "where (e.g. 'after step 2' means position 3). Omit to append at the end."
                ),
            },
            "to_position": {
                "type": "integer",
                "description": "reorder_step only: the 1-indexed position to move the step to.",
            },
            "instruction": {
                "type": "string",
                "description": (
                    "rework only: what to change, in plain language, FAITHFUL to what the "
                    "user actually asked — e.g. 'redo the whole thing around graphs'. Keep "
                    "their exact subject and count. Never substitute your own judgement "
                    "for their request."
                ),
            },
        },
        "required": ["operation"],
    },
)

GET_PLAN_TOOL = ToolDeclaration(
    name="get_learning_plan",
    description=(
        "Read the learner's current plan: every step in order, with its skill, the problem "
        "on it, its status and difficulty. Call this before answering ANY question about "
        "the plan — 'what's on my plan', 'what is step 5', 'how many steps', 'is X in "
        "there' — you cannot know its contents otherwise. Pass step to also get that "
        "step's full question: its statement, constraints and worked examples. You MUST "
        "pass step before saying anything about what a question asks, whether its test "
        "cases are right, or whether the user's complaint about it is correct — you cannot "
        "see any of that otherwise, and agreeing about a question you have not read is how "
        "you end up confirming a bug that does not exist. Read-only: it changes nothing."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "step": {
                "type": "string",
                "description": (
                    "Optional: which step's full question to include, EXACTLY as the user "
                    "identified it — its number as shown in the plan (e.g. '5') or its "
                    "skill/topic name. Omit to list the steps alone."
                ),
            },
        },
    },
)

FIND_PROBLEMS_TOOL = ToolDeclaration(
    name="find_problems",
    description=(
        "Search the problems this learner actually has — solved, failed, flagged, or "
        "anything in the bank. Call this WHENEVER they refer to a problem they have seen "
        "before ('that array one', 'the question I flagged', 'what have I solved', 'do I "
        "have a two sum problem'), and ALWAYS before offering to revise or redo anything. "
        "It returns titles and ids, never statements. This is the only way to know which "
        "problems exist — never invent one."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "What the learner called it, in their words — 'two sum', 'the coin "
                    "one', 'binary search'. Matched against titles, statements and tags, "
                    "so a rough or partial description works. Omit to list by scope alone."
                ),
            },
            "scope": {
                "type": "string",
                "enum": ["flagged", "solved", "practiced", "attempted", "all"],
                "description": (
                    "Which problems to look in. 'flagged' = marked to come back to. "
                    "'solved' = completed. 'practiced' = solved or submitted-and-failed, "
                    "the right scope for revision. 'attempted' = started but not finished. "
                    "'all' = the whole bank including ones they have never seen. Default "
                    "to 'all' for 'is there a X problem', and to the specific scope "
                    "whenever they name one."
                ),
            },
            "skill": {
                "type": "string",
                "description": (
                    "Restrict to one topic by NAME as the user says it ('graphs', 'dynamic "
                    "programming'). Not an id — this is matched loosely against skill names."
                ),
            },
            "language": {
                "type": "string",
                "enum": SUPPORTED_LANGUAGES,
                "description": (
                    "Restrict to one programming language, when and only when they name one "
                    "('the python ones I solved'). Omit otherwise — do NOT fill this in from "
                    "their default language, or you will hide problems they do have."
                ),
            },
        },
    },
)

CREATE_PRACTICE_PLAN_TOOL = ToolDeclaration(
    name="create_practice_plan",
    description=(
        "Build a plan whose steps are specific problems the learner already has — for "
        "'make me a plan to practice my flagged questions' or 'a plan to redo everything I "
        "got wrong'. Every step reopens that exact problem, nothing is regenerated. Call "
        "find_problems first to get the ids. For a plan on a TOPIC rather than on specific "
        "problems, use generate_learning_plan instead."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "problem_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ids from a find_problems result, in the order they should be "
                    "practiced. Never invent one."
                ),
            },
            "topic": {
                "type": "string",
                "description": "Short name for the plan, e.g. 'Flagged questions'.",
            },
        },
        "required": ["problem_ids"],
    },
)

SET_PROBLEM_FLAG_TOOL = ToolDeclaration(
    name="set_problem_flag",
    description=(
        "Flag a problem to come back to, or clear that flag — for 'flag that one', "
        "'remind me about this', 'unflag the two sum one'. Get the id from find_problems "
        "first."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "problem_id": {
                "type": "string",
                "description": "The exact id from a find_problems result.",
            },
            "flagged": {
                "type": "boolean",
                "description": "true to flag it, false to clear the flag.",
            },
        },
        "required": ["problem_id", "flagged"],
    },
)

PRACTICE_RECORD_TOOL = ToolDeclaration(
    name="get_practice_record",
    description=(
        "Look up how this learner is actually doing: which skills they have practiced, their "
        "mastery score on each, and how long since they last saw it. Call this before "
        "recommending what to study next, what they are weak in, or what to focus on for "
        "interviews — it is the only way to know. Takes no arguments. Do not call it for "
        "anything else."
    ),
    parameters_schema={"type": "object", "properties": {}},
)
