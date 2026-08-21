from enum import StrEnum


class Language(StrEnum):
    """Mirrors web/server/schemas/question_schema.ts LanguageEnum — keep values in sync."""

    JAVASCRIPT = "javascript"
    PYTHON = "python"
    CPP = "cpp"
    C = "c"
    JAVA = "java"
