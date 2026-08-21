CURRICULUM_SYSTEM_PROMPT = (
    "You are a DSA curriculum designer. Given a topic, target programming language, and "
    "skill level, produce a short, ordered sequence of lesson nodes that build toward "
    "mastery of the topic. Each node names the single primary skill it covers and a "
    "1-5 difficulty rating.\n\n"

    "Length: if the request states how many steps the learner wants, honour that EXACTLY — "
    "one step means one step. Otherwise keep the sequence focused at 4 to 8 nodes; that "
    "range is a default, never an override of an explicit request.\n\n"

    "If a target problem is supplied, every step must be a prerequisite skill that builds "
    "toward solving it, ordered easiest first. Do NOT emit a step for the target problem "
    "itself — it is appended automatically as the final step."
)


def curriculum_user_prompt(
    topic: str,
    language: str,
    level: str,
    step_count: int | None = None,
    target_problem: str | None = None,
) -> str:
    prompt = f"Topic: {topic}\nLanguage: {language}\nLevel: {level}"
    if step_count is not None:
        prompt += f"\nThe learner explicitly asked for exactly {step_count} step(s)."
    if target_problem:
        prompt += (
            "\n\nTarget problem the learner wants to solve — build prerequisite steps "
            f"leading up to it (do not include it as a step):\n{target_problem}"
        )
    return prompt
