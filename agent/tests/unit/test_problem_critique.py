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


async def test_a_revision_keeps_examples_as_model_instances() -> None:
    """model_dump() would hand back plain dicts here, and validation reads ex.input."""
    llm = FakeLLMProvider(
        structured_responses=[_generated_problem()],
        critiques=[_reject("examples[0].explanation: says 1 + 2 + 3 = 7")],
        revisions=[
            ProblemRevision(
                examples=[GeneratedExample(input="1 2 3", output="6", explanation="1 + 2 + 3 = 6")]
            )
        ],
    )

    problem = await generate_problem(llm, "prefix-sum", "python", "easy")

    assert isinstance(problem.examples[0], GeneratedExample)
    assert problem.examples[0].explanation == "1 + 2 + 3 = 6"


async def test_a_pasted_question_is_generated_with_the_adaptation_prompt() -> None:
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])

    await generate_problem(
        llm, "prefix-sum", "python", "easy", source_problem="Return the k-th largest element."
    )

    system_prompt = llm.last_structured_request.system_prompt
    assert "WRITE A CONTEST PROBLEM, NOT A STORY" not in system_prompt
    assert "VERBATIM" in system_prompt


async def test_a_generated_question_is_generated_with_the_authoring_prompt() -> None:
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])

    await generate_problem(llm, "prefix-sum", "python", "easy")

    assert "WRITE A CONTEST PROBLEM, NOT A STORY" in llm.last_structured_request.system_prompt


async def test_the_interview_pattern_survives_the_graph() -> None:
    """Threaded through three signatures and a TypedDict, so it is the easiest thing in the
    feature to drop silently — the problem would still generate, just untargeted."""
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])

    await generate_problem(
        llm, "graphs", "python", "medium",
        areas=("sliding window", "dynamic programming"),
        twist="a budget that may be spent at most K times",
    )

    prompt = llm.last_structured_request.user_prompt
    assert "sliding window" in prompt
    assert "dynamic programming" in prompt
    assert "a budget that may be spent at most K times" in prompt


async def test_a_pasted_question_ignores_any_interview_pattern() -> None:
    llm = FakeLLMProvider(structured_responses=[_generated_problem()])

    await generate_problem(
        llm, "graphs", "python", "medium",
        source_problem="Return the k-th largest element.",
        areas=("sliding window", "dynamic programming"),
    )

    assert "TEST-MODE TARGET" not in llm.last_structured_request.user_prompt
