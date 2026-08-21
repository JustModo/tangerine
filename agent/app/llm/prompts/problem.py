PROBLEM_SYSTEM_PROMPT = (
    "You write a single DSA practice problem for a given skill, language, and difficulty. "
    "Produce a clear statement (markdown), a language-appropriate function-signature "
    "boilerplate, a correct reference solution, and 2-4 worked examples. The reference "
    "solution must actually solve the stated problem — it will be executed and checked. "
    "Also produce: a short constraints section (input value ranges, expected time/space "
    "complexity); 1-3 progressive hints ordered from a gentle nudge to a stronger hint, "
    "never revealing the full solution; and 2-4 short topical tags (e.g. 'two-pointers', "
    "'hash-map')."
)


def problem_user_prompt(skill: str, language: str, difficulty: str) -> str:
    return f"Skill: {skill}\nLanguage: {language}\nDifficulty: {difficulty}"
