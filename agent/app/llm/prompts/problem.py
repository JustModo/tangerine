PROBLEM_SYSTEM_PROMPT = (
    "You write a single DSA practice problem for a given skill, language, and difficulty. "
    "Produce a clear statement (markdown), a language-appropriate function-signature "
    "boilerplate, a correct reference solution, and 2-4 worked examples. The reference "
    "solution must actually solve the stated problem — it will be executed and checked."
)


def problem_user_prompt(skill: str, language: str, difficulty: str) -> str:
    return f"Skill: {skill}\nLanguage: {language}\nDifficulty: {difficulty}"
