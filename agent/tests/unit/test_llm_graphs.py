import pytest

from app.llm.graphs.curriculum import generate_curriculum
from app.llm.graphs.problem import generate_problem
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.llm.schemas.problem import GeneratedExample, GeneratedProblem
from tests.fakes import FakeLLMProvider


async def test_generate_curriculum_retries_on_invalid_then_succeeds() -> None:
    good = GeneratedCurriculum(
        title="Prefix Sums",
        nodes=[GeneratedCurriculumNode(title="Fundamentals", skill="prefix-sum", difficulty=1)],
    )
    provider = FakeLLMProvider(structured_responses=[SchemaValidationError("bad json"), good])

    result = await generate_curriculum(provider, "prefix sums", "python", "beginner")

    assert result.title == "Prefix Sums"
    assert len(result.nodes) == 1


async def test_generate_curriculum_gives_up_after_max_attempts() -> None:
    provider = FakeLLMProvider(structured_responses=[SchemaValidationError("bad")] * 3)

    with pytest.raises(SchemaValidationError):
        await generate_curriculum(provider, "prefix sums", "python", "beginner")


async def test_generate_problem_returns_structured_result() -> None:
    problem = GeneratedProblem(
        title="Static Range Sum",
        statement_md="Given an array...",
        difficulty="easy",
        skills=["prefix-sum"],
        pre_code="nums = list(map(int, input().split()))",
        user_code="def solve(nums): pass",
        post_code="print(solve(nums))",
        reference_user_code="def solve(nums): return sum(nums)",
        examples=[GeneratedExample(input="[1,2,3]", output="6")],
    )
    provider = FakeLLMProvider(structured_responses=[problem])

    result = await generate_problem(provider, "prefix-sum", "python", "easy")

    assert result.title == "Static Range Sum"
