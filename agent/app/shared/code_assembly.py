def assemble_program(pre_code: str, user_code: str, post_code: str) -> str:
    """Wraps the hidden harness around the learner's code. No per-language branching: the
    language-specific shape lives in the generation prompt."""
    return "\n\n".join(part.strip("\n") for part in (pre_code, user_code, post_code))


def annotated_program(pre_code: str, user_code: str, post_code: str) -> str:
    """The same concatenation, numbered and with the fragment boundaries marked, so a
    compiler's `Main.java:14` resolves to the fragment that has to be fixed."""
    lines = assemble_program(pre_code, user_code, post_code).split("\n")

    # Numbered off the real assembly so it cannot drift; each join adds one blank line.
    starts: dict[int, str] = {}
    at = 0
    for name, part in (
        ("pre_code", pre_code.strip("\n")),
        ("user_code", user_code.strip("\n")),
        ("post_code", post_code.strip("\n")),
    ):
        starts[at] = name
        at += part.count("\n") + 2

    out: list[str] = []
    for index, line in enumerate(lines):
        if index in starts:
            out.append(f"--- {starts[index]} ---")
        out.append(f"{index + 1:4} | {line}")
    return "\n".join(out)
