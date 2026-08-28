"""What each `edit_learning_plan` operation does, as data.

Every operation reduces to the same shape: validate the arguments the model supplied, then
name a label, an action to run, and how to describe the result. Nothing here knows about
streaming, chat messages or SSE — the caller owns all of that, and owns it once instead of
once per operation.

The refusal strings are prompt input, not user-facing copy. The model reads `summary` and
acts on it, so the wording is load-bearing.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.llm.prompts.chat import SUPPORTED_LANGUAGES
from app.shared.types import Language


@dataclass(frozen=True)
class PlanEdit:
    label: str
    action: Callable[[], Awaitable[Any]]
    done_text: Callable[[Any], str]


@dataclass(frozen=True)
class Refusal:
    summary: str
    fallback: str


Outcome = PlanEdit | Refusal


def plan_step_summary(plan) -> str:
    steps = ", ".join(f"{n.sequence_index + 1}. {n.skill_name or n.skill_id}" for n in plan.nodes)
    return f"It now has {len(plan.nodes)} steps: {steps}."


def _change_language(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    requested = (args.get("language") or "").strip().lower()
    try:
        language = Language(requested)
    except ValueError:
        supported = ", ".join(SUPPORTED_LANGUAGES)
        return Refusal(
            f"NOT RUN — '{requested or 'no language'}' is not a supported "
            f"language. Nothing was changed. Tell the user the supported languages "
            f"are {supported} and ask them to pick one.",
            f"I can do {supported} — which would you like?",
        )
    return PlanEdit(
        f"Switching the plan to {language.value}...",
        lambda: curriculum.set_plan_language(plan_id, language),
        lambda plan: (
            f"Switched the plan to {plan.language.value}. Steps and completed progress "
            "are unchanged; new problems will generate in the new language."
        ),
    )


def _change_step_difficulty(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    step = str(args.get("step") or "").strip()
    difficulty = (args.get("difficulty") or "").strip().lower()
    if not step or difficulty not in {"easy", "medium", "hard"}:
        return Refusal(
            "NOT RUN — missing which step or what difficulty to set. Ask the user "
            "which step and how much harder/easier.",
            "Which step, and how much harder or easier?",
        )
    return PlanEdit(
        f"Adjusting step {step}...",
        lambda: curriculum.set_step_difficulty(plan_id, step, difficulty),
        lambda plan: f"Updated that step's difficulty. {plan_step_summary(plan)}",
    )


def _add_step(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    skill = str(args.get("skill") or "").strip()
    if not skill:
        return Refusal(
            "NOT RUN — no skill/topic given for the new step. Ask the user what it "
            "should cover.",
            "What should the new step cover?",
        )
    difficulty = args.get("difficulty") or None
    position = args.get("position")
    return PlanEdit(
        f"Adding a step on {skill}...",
        lambda: curriculum.add_step(plan_id, skill, difficulty, position),
        lambda plan: f"Added the new step. {plan_step_summary(plan)}",
    )


def _add_problem(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    problem_id = str(args.get("problem_id") or "").strip()
    if not problem_id:
        return Refusal(
            "NOT RUN — no problem id given. Call find_problems to get one, then try "
            "again. Do not invent an id.",
            "Which problem did you want me to add?",
        )
    return PlanEdit(
        "Adding that problem to your plan...",
        lambda: curriculum.add_problem_step(plan_id, problem_id),
        lambda plan: (
            "Added it to their plan as a new step — it opens that exact problem, nothing "
            f"regenerated. Tell them it's on their plan and ready to start. "
            f"{plan_step_summary(plan)}"
        ),
    )


def _remove_step(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    step = str(args.get("step") or "").strip()
    if not step:
        return Refusal(
            "NOT RUN — no step named to remove. Ask the user which one.",
            "Which step should I remove?",
        )
    return PlanEdit(
        f"Removing step {step}...",
        lambda: curriculum.remove_step(plan_id, step),
        lambda plan: f"Removed that step. {plan_step_summary(plan)}",
    )


def _reorder_step(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    step = str(args.get("step") or "").strip()
    to_position = args.get("to_position")
    if not step or to_position is None:
        return Refusal(
            "NOT RUN — missing which step or where to move it. Ask the user for both.",
            "Which step, and where should it move to?",
        )
    return PlanEdit(
        f"Reordering step {step}...",
        lambda: curriculum.reorder_step(plan_id, step, to_position),
        lambda plan: f"Reordered the plan. {plan_step_summary(plan)}",
    )


def _rework(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    instruction = args.get("instruction") or user_message
    return PlanEdit(
        "Updating your learning plan...",
        lambda: curriculum.edit_plan(plan_id, instruction),
        lambda plan: f"Updated the plan. {plan_step_summary(plan)}",
    )


PLAN_EDITS: dict[str, Callable[[dict, str, Any, str], Outcome]] = {
    "change_language": _change_language,
    "change_step_difficulty": _change_step_difficulty,
    "add_step": _add_step,
    "add_problem": _add_problem,
    "remove_step": _remove_step,
    "reorder_step": _reorder_step,
    "rework": _rework,
}


def build(operation: str, args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    """Unrecognised operations rework, matching the old chain's else branch."""
    return PLAN_EDITS.get(operation, _rework)(args, plan_id, curriculum, user_message)
