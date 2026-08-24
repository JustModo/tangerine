def assemble_program(pre_code: str, user_code: str, post_code: str) -> str:
    """Wraps the hidden harness around the learner's code. No per-language branching: the
    language-specific shape lives in the generation prompt."""
    return "\n\n".join(part.strip("\n") for part in (pre_code, user_code, post_code))
