from pydantic import BaseModel, Field


class GeneratedCurriculumNode(BaseModel):
    # `skill` is the only thing persisted, and it IS the step's name in the UI. There is no
    # separate title field: one used to exist, was never read, and cost a token budget per
    # node to produce something nobody saw.
    skill: str = Field(
        description="The single primary skill this step covers, as a SHORT name: 2-4 words, "
        "lowercase, no filler. 'sliding window', 'hash map counting', 'binary search on "
        "answer'. Never a sentence or a description of the activity."
    )
    difficulty: int = Field(description="1-5.")


class GeneratedCurriculum(BaseModel):
    nodes: list[GeneratedCurriculumNode]
