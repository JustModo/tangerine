from pydantic import BaseModel


class GeneratedExample(BaseModel):
    input: str
    output: str
    explanation: str | None = None


class GeneratedProblem(BaseModel):
    title: str
    statement_md: str
    difficulty: str
    skills: list[str]
    boilerplate: str
    reference_solution: str
    examples: list[GeneratedExample]
    constraints: str | None = None
    hints: list[str] = []
    tags: list[str] = []
