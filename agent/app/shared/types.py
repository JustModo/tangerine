from enum import StrEnum


class Language(StrEnum):
    PYTHON = "python"
    CPP = "cpp"
    C = "c"
    JAVA = "java"


SUPPORTED_LANGUAGES = [language.value for language in Language]
