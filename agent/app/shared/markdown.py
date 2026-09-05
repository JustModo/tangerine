import re

# Fenced blocks with the language tag captured — the shape every generation prompt here
# asks its markdown to use.
FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def prose_only(markdown: str) -> str:
    """The part a word budget should count. Code, traces and diagrams are not prose."""
    return FENCE.sub("", markdown)
