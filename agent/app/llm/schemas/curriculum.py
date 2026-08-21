from pydantic import BaseModel


class GeneratedCurriculumNode(BaseModel):
    title: str
    skill: str
    difficulty: int


class GeneratedCurriculum(BaseModel):
    title: str
    nodes: list[GeneratedCurriculumNode]
