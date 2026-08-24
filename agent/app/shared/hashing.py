import hashlib


def normalize_output(output: str) -> str:
    return output.strip().replace("\r\n", "\n")


def hash_output(output: str) -> str:
    return hashlib.sha256(normalize_output(output).encode("utf-8")).hexdigest()
