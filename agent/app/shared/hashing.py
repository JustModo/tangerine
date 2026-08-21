import hashlib


def normalize_output(output: str) -> str:
    """Mirrors web/server/services/runner_service.ts normalizeOutput exactly, so hashes
    computed here match hashes the existing sandbox computes when grading."""
    return output.strip().replace("\r\n", "\n")


def hash_output(output: str) -> str:
    return hashlib.sha256(normalize_output(output).encode("utf-8")).hexdigest()
