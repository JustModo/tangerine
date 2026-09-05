import hashlib


def normalize_output(output: str) -> str:
    return output.strip().replace("\r\n", "\n")


def hash_output(output: str) -> str:
    return hashlib.sha256(normalize_output(output).encode("utf-8")).hexdigest()


def comparable_output(value: str | None) -> str:
    """Sandbox stdout vs. a statement's example output: trailing whitespace and line
    endings differ constantly and mean nothing.

    Deliberately NOT normalize_output: that one backs the stored test hashes, and both
    sides of any single comparison must go through the same one."""
    return "\n".join(line.rstrip() for line in (value or "").strip().splitlines())
