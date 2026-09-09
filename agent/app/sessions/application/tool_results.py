"""Render tool results into text representation for the model."""

from app.curriculum.domain.models import LessonPlan
from app.revision.domain.models import RevisionCandidate


def mastery_context(candidates: list[RevisionCandidate], limit: int = 8) -> str:
    """Render practice record candidates into prompt context."""
    if not candidates:
        return (
            "PRACTICE RECORD: empty — this learner has not completed any practice problems "
            "yet, so there is nothing to be weak or strong at. Tell them that plainly and "
            "recommend from general DSA knowledge and what they tell you."
        )

    shown = candidates[:limit]
    buckets: dict[str, list[str]] = {"Weak": [], "In progress": [], "Solid": []}
    for candidate in shown:
        if candidate.mastery_score < 0.5:
            bucket = "Weak"
        elif candidate.mastery_score > 0.7:
            bucket = "Solid"
        else:
            bucket = "In progress"
        buckets[bucket].append(
            f"{candidate.skill_name} (id: {candidate.skill_id}, {candidate.mastery_score:.2f}, "
            f"last practiced {round(candidate.days_since_seen)}d ago)"
        )

    lines = ["PRACTICE RECORD (mastery 0.00-1.00, from their own solved problems):"]
    for name, entries in buckets.items():
        if entries:
            lines.append(f"- {name}: {', '.join(entries)}")
    hidden = len(candidates) - len(shown)
    if hidden:
        lines.append(
            f"- (plus {hidden} more not listed — these are the {limit} weakest/most overdue, "
            "not the whole record.)"
        )
    lines.append(
        "Skills absent from this list have never been practiced at all."
    )
    return "\n".join(lines)


def library_context(entries: list, scope: str, stats=None) -> str:
    """Render library problem search results into prompt context."""
    header = f"PROBLEMS FOUND (scope: {scope}) — these are real rows from their bank:"
    if not entries:
        return (
            f"NO PROBLEMS FOUND for scope '{scope}'. Say so plainly. Do NOT invent a title "
            "or an id, and do not describe a problem they have not actually got."
        )

    lines = [header]
    for entry in entries:
        marks = [entry.status.replace("_", " ").lower() if entry.status else "never opened"]
        if entry.flagged:
            marks.append("FLAGGED")
        lines.append(
            f"- {entry.title} (id: {entry.problem_id}) — {entry.difficulty}, "
            f"{entry.language}{f', {entry.skill}' if entry.skill else ''} [{', '.join(marks)}]"
        )
    if stats is not None:
        lines.append(
            f"Overall: {stats.solved_total} solved all time, {stats.solved_this_week} this "
            f"week, best streak {stats.best_streak}."
        )
    lines.append(
        "To put one on their plan, call edit_learning_plan with operation 'add_problem' and "
        "its id exactly as given; to build a new plan out of several, call "
        "create_practice_plan with their ids. Never invent an id, and never claim a problem "
        "exists that is not on this list."
    )
    return "\n".join(lines)


def library_memo(entries: list) -> str:
    """Format compact problem IDs memo for subsequent conversational turns."""
    if not entries:
        return ""
    lines = ["Problems last shown to this user (ids for your use only):"]
    lines += [
        f"{entry.problem_id} | {entry.title} | {entry.language}"
        f"{' | FLAGGED' if entry.flagged else ''}"
        for entry in entries
    ]
    return "\n".join(lines)


def plan_context(plan: LessonPlan | None) -> str:
    """Render lesson plan into prompt context."""
    if plan is None:
        return (
            "NO PLAN EXISTS for this session — there is nothing to describe. Say so plainly "
            "and ask what they want to learn. Do NOT invent steps."
        )

    lines = [
        f"CURRENT PLAN — '{plan.topic}' ({plan.language.value}, {plan.level}), "
        f"{len(plan.nodes)} steps:"
    ]
    lines += [
        f"{node.sequence_index + 1}. {node.skill_name or node.skill_id}"
        f"{f' — {node.problem_title}' if node.problem_title else ''}"
        f" [{node.status.lower()}{f', {node.difficulty}' if node.difficulty else ''}]"
        for node in plan.nodes
    ]
    lines.append(
        "That is every step, in order. Answer anything they ask about the plan from this "
        "list alone — never from a problems list, never from memory of earlier turns."
    )
    return "\n".join(lines)


def step_problem_context(node, problem, version=None) -> str:
    """Render problem statement, constraints, and worked examples for a plan step."""
    target = version or problem
    if target is None:
        return (
            f"STEP {node.sequence_index + 1} ({node.skill_name or node.skill_id}) HAS NO "
            "QUESTION YET — one is written the first time they open it, so there is nothing "
            "to read and nothing to judge. Say exactly that; do not describe a question."
        )

    lines = [
        f"STEP {node.sequence_index + 1} QUESTION — '{problem.title}' "
        f"({problem.difficulty}, {problem.language.value}):",
        "",
        target.statement_md.strip(),
    ]
    if target.constraints:
        lines += ["", f"Constraints: {target.constraints.strip()}"]
    if target.examples:
        lines.append("")
        lines.append("Worked examples shown to the learner:")
        for index, example in enumerate(target.examples, start=1):
            lines.append(f"{index}. input {example.input!r} -> output {example.output!r}")
            if example.explanation:
                lines.append(f"   explanation: {' '.join(example.explanation.split())}")
    lines += [
        "",
        "Every expected output above was produced by running the reference solution in the "
        "sandbox, and a problem whose examples disagreed with that run is rejected before "
        "it is ever served — so an output here cannot contradict the statement's logic. "
        "Read the statement and the examples yourself before answering. If the user says a "
        "test case is wrong, work it through and tell them what the right answer is, "
        "including when that means telling them the question is fine. Do NOT agree that "
        "something is broken because they said so.",
    ]
    return "\n".join(lines)

