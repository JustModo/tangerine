import pytest

from app.llm.graphs.curriculum import generate_curriculum
from app.llm.graphs.problem import generate_problem
from app.llm.infrastructure.gemini.mapping import SchemaValidationError
from app.llm.schemas.curriculum import GeneratedCurriculum, GeneratedCurriculumNode
from app.llm.schemas.problem import GeneratedExample, GeneratedProblem
from tests.fakes import FakeLLMProvider


async def test_generate_curriculum_retries_on_invalid_then_succeeds() -> None:
    good = GeneratedCurriculum(
        nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)],
    )
    provider = FakeLLMProvider(structured_responses=[SchemaValidationError("bad json"), good])

    result = await generate_curriculum(provider, "prefix sums", "python", "beginner")

    assert len(result.nodes) == 1
    assert result.nodes[0].skill == "prefix-sum"


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
        constraints="1 <= len(nums) <= 10^5",
        input_format="nums: list[int], the array to sum.",
        output_format="Return the sum as an int; printed on one line.",
    )
    provider = FakeLLMProvider(structured_responses=[problem])

    result = await generate_problem(provider, "prefix-sum", "python", "easy")

    assert result.title == "Static Range Sum"


async def test_a_retry_tells_the_model_why_it_was_rejected() -> None:
    """A blind retry re-sends a byte-identical prompt and relies purely on sampling."""
    good = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    provider = FakeLLMProvider(
        structured_responses=[SchemaValidationError("nodes: field required"), good]
    )

    await generate_curriculum(provider, "prefix sums", "python", "beginner")

    retry_prompt = provider.last_structured_request.user_prompt
    assert "REJECTED" in retry_prompt
    assert "nodes: field required" in retry_prompt


async def test_the_first_attempt_carries_no_rejection_note() -> None:
    good = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    provider = FakeLLMProvider(structured_responses=[good])

    await generate_curriculum(provider, "prefix sums", "python", "beginner")

    assert "REJECTED" not in provider.last_structured_request.user_prompt


async def test_mastered_skills_reach_the_prompt() -> None:
    good = GeneratedCurriculum(nodes=[GeneratedCurriculumNode(skill="prefix-sum", difficulty=1)])
    provider = FakeLLMProvider(structured_responses=[good])

    await generate_curriculum(
        provider, "arrays", "python", "beginner", known_skills=["two pointers"]
    )

    assert "two pointers" in provider.last_structured_request.user_prompt
