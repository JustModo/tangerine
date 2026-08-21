def assemble_program(pre_code: str, user_code: str, post_code: str) -> str:
    """Concatenates a problem's hidden harness around the learner's (or reference) code
    into one program to execute. No per-language branching here — the language-specific
    shape (e.g. Java's brace-split class) lives entirely in the generation prompt."""
    return "\n\n".join(part.strip("\n") for part in (pre_code, user_code, post_code))
