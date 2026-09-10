import random
from typing import NamedTuple


class InterviewTarget(NamedTuple):
    skill: str
    areas: tuple[str, str]
    twist: str | None
    difficulty: str


AREAS: tuple[str, ...] = (
    "arrays and prefix sums",
    "strings",
    "sliding window",
    "two pointers",
    "hashing and grouping",
    "sorting and ordering",
    "greedy choices",
    "binary search on the answer",
    "matrix traversal",
    "graph traversal and shortest paths",
    "union-find and connectivity",
    "trees",
    "dynamic programming",
    "dp optimisation",
    "intervals and scheduling",
    "monotonic stack",
    "heaps and priority queues",
    "simulation",
    "bitmasking",
    "math and number theory",
)

DEMOTED = {
    "math and number theory": 0.4,
    "bitmasking": 0.5,
    "strings": 0.7,
    "monotonic stack": 0.7,
}

TWISTS: tuple[str, ...] = (
    "a budget that may be spent at most K times, so the answer has to track how much is left",
    "a rule that forbids the move the solver would otherwise take",
    "two objectives ranked one after the other, where the second is decided only among "
    "the answers already optimal for the first",
    "elements that may be revisited during the process but counted at most once in the answer",
    "an answer demanded over every starting point at once rather than a single query",
    "a quantity that must satisfy a numeric property (Fibonacci, prime, power of two, "
    "divisibility) as well as a bound",
    "a count so large it must be reported modulo 10^9 + 7",
    "a grouping rule that couples items by identity, not merely by value",
    "an exact number of parts required rather than an upper bound",
    "a reachability condition, with an explicit sentinel value when the goal cannot be reached",
    "a cost that depends on the previous choice as well as the current one",
    "a restriction that only bites at the extremes of the input range",
    "a quantity that is cheap to check but expensive to search for directly",
    "a condition that must hold for every prefix of the answer, not only at the end",
)

TWIST_CHANCE = 0.55

DIFFICULTIES = ("easy", "medium", "hard")
DIFFICULTY_WEIGHTS = (10, 50, 40)


MAX_TOPIC_LENGTH = 60


def random_target(topic: str | None = None, difficulty: str | None = None) -> InterviewTarget:
    chosen = " ".join((topic or "").split()).lower()[:MAX_TOPIC_LENGTH]
    primary = chosen or random.choices(
        AREAS, weights=[DEMOTED.get(name, 1.0) for name in AREAS]
    )[0]
    secondary = random.choice([name for name in AREAS if name != primary])
    return InterviewTarget(
        skill=primary,
        areas=(primary, secondary),
        twist=random.choice(TWISTS) if random.random() < TWIST_CHANCE else None,
        difficulty=difficulty or random.choices(DIFFICULTIES, weights=DIFFICULTY_WEIGHTS)[0],
    )
