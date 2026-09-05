"""What each `edit_learning_plan` operation does, as data.

Every operation reduces to the same shape: validate the arguments the model supplied, then
name a label, an action to run, and how to describe the result. Nothing here knows about
streaming, chat messages or SSE — the caller owns all of that, and owns it once instead of
once per operation.

The refusal strings are prompt input, not user-facing copy. The model reads `summary` and
acts on it, so the wording is load-bearing.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

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


def _regenerate_problem(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    step = str(args.get("step") or "").strip()
    if not step:
        return Refusal(
            "NOT RUN — no step named. Ask the user which step's question they want "
            "replaced.",
            "Which step's question should I replace?",
        )
    return PlanEdit(
        f"Replacing step {step}'s question...",
        lambda: curriculum.regenerate_step_problem(plan_id, step),
        lambda plan: (
            f"Retired step {step}'s question and discarded their attempt at it. The step "
            "generates a different one the moment they open it. Tell them to open that "
            "step to get it. The plan's steps are unchanged — say nothing about having "
            "edited the question itself, because you did not: a new one is written on open."
        ),
    )


def _step_shape(plan) -> list[tuple[int, str, str | None]]:
    """What a rework is allowed to change. Compared before and after so a rework that came
    back with the identical plan cannot be reported as a change that happened."""
    return [(n.sequence_index, n.skill_name or n.skill_id, n.difficulty) for n in plan.nodes]


def _rework(args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    instruction = args.get("instruction") or user_message
    before: list[tuple[int, str, str | None]] = []

    async def run():
        nonlocal before
        current = await curriculum.get(plan_id)
        before = _step_shape(current) if current is not None else []
        return await curriculum.edit_plan(plan_id, instruction)

    return PlanEdit(
        "Updating your learning plan...",
        run,
        lambda plan: (
            # The failure this closes: a rework that returned the plan untouched still
            # reported "Updated the plan", and the model narrated a fix that never happened.
            f"NOT CHANGED — the rework came back with the same {len(plan.nodes)} steps, so "
            "nothing was edited. Tell the user plainly that nothing changed and ask what "
            "they want done differently. Do NOT claim anything was fixed or updated. If "
            "they were asking about the QUESTION on a step rather than the step itself, "
            "say a rework cannot touch a question and offer regenerate_problem."
            if _step_shape(plan) == before
            else f"Updated the plan. {plan_step_summary(plan)}"
        ),
    )


PLAN_EDITS: dict[str, Callable[[dict, str, Any, str], Outcome]] = {
    "change_language": _change_language,
    "change_step_difficulty": _change_step_difficulty,
    "add_step": _add_step,
    "add_problem": _add_problem,
    "remove_step": _remove_step,
    "reorder_step": _reorder_step,
    "regenerate_problem": _regenerate_problem,
    "rework": _rework,
}


def build(operation: str, args: dict, plan_id: str, curriculum, user_message: str) -> Outcome:
    """A NAMED operation that does not exist is refused, not quietly reworked.

    Falling back to _rework meant the model asking for something this chat cannot do got a
    whole-plan rework that changed nothing and reported success — it then told the user it
    had fixed a question. An unnamed operation still reworks: that is a broad request, not
    a wrong one.
    """
    handler = PLAN_EDITS.get(operation)
    if handler is None:
        return Refusal(
            f"NOT RUN — '{operation}' is not one of the operations and NOTHING was changed. "
            f"The operations are: {', '.join(PLAN_EDITS)}. Either call this again with the "
            "one that matches what they asked, or tell them plainly that this chat cannot "
            "do it. Never describe it as done.",
            "I can't do that to your plan — could you put it another way?",
        )
    return handler(args, plan_id, curriculum, user_message)
