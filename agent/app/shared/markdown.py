import re

FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def prose_only(markdown: str) -> str:
    return FENCE.sub("", markdown)
