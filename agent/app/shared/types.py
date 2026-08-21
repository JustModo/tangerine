from enum import StrEnum


class Language(StrEnum):
    """Mirrors web/server/schemas/question_schema.ts LanguageEnum — keep values in sync."""

    JAVASCRIPT = "javascript"
    PYTHON = "python"
    CPP = "cpp"
    C = "c"
    JAVA = "java"


LANGUAGE_EXTENSIONS: dict[Language, str] = {
    Language.PYTHON: "py",
    Language.JAVASCRIPT: "js",
    Language.CPP: "cpp",
    Language.C: "c",
    Language.JAVA: "java",
}
