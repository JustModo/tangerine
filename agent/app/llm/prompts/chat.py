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
    "calling the tool. Keep replies to 2-3 sentences."
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


def chat_system_prompt(existing_plan: bool) -> str:
    plan_note = (
        "\n\nA learning plan already exists for this session — if the user wants "
        "something different, call generate_learning_plan again to update it."
        if existing_plan
        else "\n\nNo learning plan exists yet for this session."
    )
    return CHAT_SYSTEM_PROMPT_BASE + plan_note
