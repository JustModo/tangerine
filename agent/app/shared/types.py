from enum import StrEnum


class Language(StrEnum):
    """The four languages Citron's real languages.toml supports — execution is 100%
    Citron-routed, so this list IS the set of languages this app can run at all."""

    PYTHON = "python"
    CPP = "cpp"
    C = "c"
    JAVA = "java"
