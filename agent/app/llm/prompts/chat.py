from app.llm.domain.requests import ToolDeclaration
from app.shared.types import Language

CHAT_SYSTEM_PROMPT_BASE = (
    "You are Tangerine, an assistant that helps a user build a personalized DSA "
    "(data structures & algorithms) practice curriculum. Have a brief, natural "
    "conversation to learn: the topic/skill they want to practice, the programming "
    "language (default to python if they don't say), and their level (default to "
    "beginner if they don't say). Once you have enough and the user has confirmed "
    "they want to proceed — including a short affirmative like 'yes' or 'do it' — "
    "call the generate_learning_plan tool yourself. Do not describe what you're "
    "about to generate and then stop and wait; actually call the tool. If the "
    "request is unclear or off-topic, ask one short clarifying question instead of "
    "calling the tool. Keep replies to 2-3 sentences.\n\n"
    "Formatting: replies render as GitHub-flavoured markdown with KaTeX math. Use $...$ "
    "for inline math and $$...$$ for a displayed formula whenever real notation helps — "
    "e.g. $O(\\log n)$, $n / 2^k$, $A = P(1 + r/100)^t$. Use inline code for identifiers "
    "and code (`left`, `arr[mid]`), not for math. Only use $ when you mean math."
)

GENERATE_PLAN_TOOL = ToolDeclaration(
    name="generate_learning_plan",
    description=(
        "Generate or regenerate the structured learning plan/curriculum for this "
        "session once the user has confirmed what they want."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "The DSA topic or skill area to build a curriculum for."},
            "language": {
                "type": "string",
                "enum": [language.value for language in Language],
                "description": "Programming language for the practice problems.",
            },
            "level": {
                "type": "string",
                "description": "Skill level to start at, e.g. beginner, intermediate, advanced.",
            },
        },
        "required": ["topic", "language", "level"],
    },
)

EDIT_PLAN_TOOL = ToolDeclaration(
    name="edit_learning_plan",
    description=(
        "Revise the EXISTING learning plan in place when the user asks for a change to it "
        "— adding or removing a step, making one step harder or easier, reordering, or "
        "reworking the whole plan. Preserves steps the user has already completed. Use "
        "this instead of generate_learning_plan whenever a plan already exists and the "
        "user wants it changed rather than replaced from scratch."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": (
                    "What to change, in plain language, quoting the user's intent — e.g. "
                    "'add one more step on hash maps after step 2', 'make step 3 harder', "
                    "'drop the recursion step'. If the user named a specific step number, "
                    "include that number here."
                ),
            }
        },
        "required": ["instruction"],
    },
)


def chat_system_prompt(existing_plan: bool) -> str:
    plan_note = (
        "\n\nA learning plan already exists for this session. If the user asks to CHANGE it "
        "— add or remove a step, make a specific step harder or easier, reorder, or rework "
        "it — call edit_learning_plan with their instruction; it edits in place and keeps "
        "steps they've already completed. Only call generate_learning_plan again if they "
        "want a plan for a genuinely different topic, language, or level."
        if existing_plan
        else "\n\nNo learning plan exists yet for this session."
    )
    return CHAT_SYSTEM_PROMPT_BASE + plan_note
