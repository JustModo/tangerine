from app.llm.graphs.problem import MAX_REVISION_ROUNDS, generate_problem
from app.llm.schemas.problem import (
    GeneratedExample,
    GeneratedProblem,
    ProblemCritique,
    ProblemRevision,
)
from tests.fakes import FakeLLMProvider

_ARITHMETIC = "examples[0].explanation: says 3 x 4 = 14"


def _generated_problem(statement: str = "Given an array, answer sum queries.") -> GeneratedProblem:
    return GeneratedProblem(
        title="Static Range Sum",
        statement_md=statement,
        difficulty="easy",
        skills=["prefix-sum"],
        pre_code="nums = list(map(int, input().split()))",
        user_code="def solve(nums: list[int]) -> int: pass",
        post_code="print(solve(nums))",
        reference_user_code="def solve(nums: list[int]) -> int: return sum(nums)",
        examples=[GeneratedExample(input="1 2 3", output="6", explanation="1 + 2 + 3 = 6")],
        hidden_tests=["0", "5", "-1 -2"],
        constraints="1 <= len(nums) <= 10^5",
        input_format="nums: list[int], the array to sum.",
        output_format="Returns the sum as an int.",
        hints=["Consider a running total."],
        tags=["prefix-sum"],
    )


def _reject(*violations: str) -> ProblemCritique:
    return ProblemCritique(approved=False, violations=list(violations))


async def test_a_rejected_problem_is_revised_against_the_violations() -> None:
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem()],
        critiques=[_reject(_ARITHMETIC)],
        revisions=[ProblemRevision(statement_md="Sum the array.")],
    )

    problem = await generate_problem(llm, "prefix-sum", "python", "easy")

    assert problem.statement_md == "Sum the array."
    assert problem.title == "Static Range Sum"
    assert _ARITHMETIC in llm.last_revision_request.user_prompt


async def test_the_critique_runs_on_the_happy_path() -> None:
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])

    problem = await generate_problem(llm, "prefix-sum", "python", "easy")

    assert llm.last_critique_request is not None
    assert llm.last_revision_request is None
    assert problem.statement_md == "Given an array, answer sum queries."


async def test_a_judge_that_never_approves_still_serves_a_problem() -> None:
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem()],
        critiques=[_reject(_ARITHMETIC)] * (MAX_REVISION_ROUNDS + 1),
        revisions=[ProblemRevision(title=f"Round {index}") for index in range(MAX_REVISION_ROUNDS)],
    )

    problem = await generate_problem(llm, "prefix-sum", "python", "easy")

    assert problem.title == f"Round {MAX_REVISION_ROUNDS - 1}"


async def test_a_verdict_with_no_violations_is_an_approval() -> None:
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem()], critiques=[ProblemCritique(approved=False)]
    )

    problem = await generate_problem(llm, "prefix-sum", "python", "easy")

    assert problem.title == "Static Range Sum"
    assert llm.last_revision_request is None


async def test_a_judge_that_cannot_run_is_never_fatal() -> None:
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem()], critiques=[RuntimeError("judge is down")]
    )

    problem = await generate_problem(llm, "prefix-sum", "python", "easy")

    assert problem.title == "Static Range Sum"


async def test_a_reviser_that_cannot_run_serves_the_unrevised_problem() -> None:
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem()],
        critiques=[_reject(_ARITHMETIC)],
        revisions=[RuntimeError("reviser is down")],
    )

    problem = await generate_problem(llm, "prefix-sum", "python", "easy")

    assert problem.statement_md == "Given an array, answer sum queries."


async def test_a_revision_never_rewrites_a_pasted_question() -> None:
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem()],
        critiques=[_reject("hints[0]: names the technique")],
        revisions=[ProblemRevision(statement_md="A different question.", hints=["Try a loop."])],
    )

    problem = await generate_problem(
        llm, "prefix-sum", "python", "easy", source_problem="Sum the numbers on stdin."
    )

    assert problem.statement_md == "Given an array, answer sum queries."
    assert problem.hints == ["Try a loop."]
