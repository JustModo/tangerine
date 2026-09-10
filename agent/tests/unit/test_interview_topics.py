"""The interview catalog is the whole premise of test mode: drilling a random DSA question
is not interview practice, so these pin the shape of what gets drawn."""

import random
from collections import Counter

from app.problems.domain.interview_topics import (
    AREAS,
    DEMOTED,
    DIFFICULTIES,
    DIFFICULTY_WEIGHTS,
    MAX_TOPIC_LENGTH,
    TWIST_CHANCE,
    TWISTS,
    random_target,
)


def test_areas_are_broad_directions_not_a_recipe() -> None:
    """Naming specific algorithms made the generator produce only those. These are areas to
    aim at; the model picks the actual question."""
    assert len(AREAS) >= 12
    assert len(set(AREAS)) == len(AREAS)
    for area in AREAS:
        assert area == area.strip().lower(), area
        # A whole recipe here ("Dijkstra with a priority queue over weighted edges") is what
        # made the generator produce that exact question and nothing else.
        assert len(area.split()) <= 5, area


def test_areas_are_uniform_unless_deliberately_demoted() -> None:
    """The draw is meant to be flat across the core: an area is only ever weighted DOWN,
    never up, so no area can quietly crowd the rest out."""
    assert set(DEMOTED) <= set(AREAS), set(DEMOTED) - set(AREAS)
    for area, weight in DEMOTED.items():
        assert 0 < weight < 1, area


def test_a_draw_composes_two_different_areas() -> None:
    """A draw landing twice in one area is the direct, single-technique question this
    replaced."""
    random.seed(0)
    for _ in range(500):
        target = random_target()
        primary, secondary = target.areas

        assert target.skill == primary
        assert primary in AREAS and secondary in AREAS
        assert primary != secondary
        assert target.twist is None or target.twist in TWISTS
        assert target.difficulty in DIFFICULTIES


def test_no_core_area_dominates_the_draw() -> None:
    """The complaint that prompted this shape: heavy weights made the picker predictable."""
    random.seed(0)
    counts = Counter(random_target().skill for _ in range(20000))
    core = [count for skill, count in counts.items() if skill not in DEMOTED]

    assert max(core) < min(core) * 1.4
    for skill in DEMOTED:
        assert counts[skill] < min(core)


def test_the_draw_leans_hard_because_a_test_is_not_a_lesson() -> None:
    """Guards the weights against a transposition — (60, 15, 25) would still sum to 100 and
    still pass every other test here while drilling mostly easies."""
    random.seed(0)
    counts = Counter(random_target().difficulty for _ in range(2000))

    # A test is applying what was learned, so easy warm-ups are the rare case here.
    assert counts["medium"] > counts["hard"] > counts["easy"]
    assert DIFFICULTY_WEIGHTS[1] == max(DIFFICULTY_WEIGHTS)


def test_the_areas_are_the_popular_ones_worth_drilling() -> None:
    """These are directions the solver is expected to recognise, not a taxonomy. They may
    name a familiar technique — the prompt is what forbids the statement from repeating it."""
    for expected in ("sliding window", "two pointers", "dynamic programming"):
        assert expected in AREAS


def test_only_some_draws_carry_a_complication() -> None:
    """Every question having an awkward extra condition made them all read the same way. A
    clean question with one real insight in it is a legitimate test question too."""
    random.seed(0)
    twists = [random_target().twist for _ in range(2000)]
    with_twist = sum(1 for twist in twists if twist is not None)

    assert 0.4 < with_twist / len(twists) < 0.75
    assert 0 < TWIST_CHANCE < 1


def test_a_typed_topic_becomes_the_primary_area() -> None:
    """Test mode lets the learner name what they want to drill, so the typed text has to
    reach generation as the primary area and as the skill mastery is recorded against."""
    target = random_target(topic="  Two   Pointers ")

    assert target.skill == "two pointers"
    assert target.areas[0] == "two pointers"
    # Still composed: a named topic narrows the draw, it does not make it single-technique.
    assert target.areas[1] != "two pointers"
    assert target.areas[1] in AREAS


def test_a_named_difficulty_overrides_the_draw() -> None:
    for _ in range(20):
        assert random_target(difficulty="hard").difficulty == "hard"


def test_an_empty_topic_still_draws_at_random() -> None:
    for value in (None, "", "   "):
        assert random_target(topic=value).skill in AREAS


def test_a_long_topic_is_clipped_before_it_becomes_a_skill_row() -> None:
    target = random_target(topic="x" * 500)

    assert len(target.skill) <= MAX_TOPIC_LENGTH
