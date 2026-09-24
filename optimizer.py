"""Ergonomic evaluation and simulated annealing for mirror layouts."""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass

from layout import Layout


@dataclass(frozen=True)
class ObjectiveWeights:
    repetition: float = 10.0
    row_jump: float = 3.0
    pinky: float = 2.0
    index: float = 1.0


DEFAULT_WEIGHTS = ObjectiveWeights()


def repetition_count(layout: Layout, bigrams: Counter[tuple[str, str]]) -> int:
    """Count same-finger OR same-column transitions, once per bigram."""
    return sum(
        frequency
        for (first, second), frequency in bigrams.items()
        if layout.finger_for(first) == layout.finger_for(second)
        or layout.column_for(first) == layout.column_for(second)
    )


def same_finger_count(layout: Layout, bigrams: Counter[tuple[str, str]]) -> int:
    """Backward-compatible name for same-finger-or-column repetition."""
    return repetition_count(layout, bigrams)


def row_jump_cost(layout: Layout, bigrams: Counter[tuple[str, str]]) -> int:
    return sum(
        frequency * abs(layout.row_for(first) - layout.row_for(second))
        for (first, second), frequency in bigrams.items()
    )


def finger_usage(layout: Layout, unigrams: Counter[str], finger: str) -> int:
    return sum(
        frequency
        for character, frequency in unigrams.items()
        if layout.finger_for(character) == finger
    )


@dataclass(frozen=True)
class Evaluation:
    repetition_count: int
    total_alphabet_bigram_count: int
    row_jump_cost: int
    total_alphabet_character_count: int
    pinky_usage_count: int
    index_usage_count: int
    weighted_total_cost: float

    @property
    def same_finger_count(self) -> int:
        return self.repetition_count

    @property
    def total_transitions(self) -> int:
        return self.total_alphabet_bigram_count

    @property
    def rate(self) -> float:
        return self.repetition_rate

    @property
    def repetition_rate(self) -> float:
        if not self.total_alphabet_bigram_count:
            return 0.0
        return self.repetition_count / self.total_alphabet_bigram_count

    @property
    def same_finger_rate(self) -> float:
        return self.repetition_rate

    @property
    def average_row_distance(self) -> float:
        if not self.total_alphabet_bigram_count:
            return 0.0
        return self.row_jump_cost / self.total_alphabet_bigram_count

    @property
    def total_row_jump_cost(self) -> int:
        return self.row_jump_cost

    @property
    def total_alphabet_characters(self) -> int:
        return self.total_alphabet_character_count

    @property
    def pinky_usage(self) -> int:
        return self.pinky_usage_count

    @property
    def index_usage(self) -> int:
        return self.index_usage_count

    @property
    def pinky_usage_rate(self) -> float:
        if not self.total_alphabet_character_count:
            return 0.0
        return self.pinky_usage_count / self.total_alphabet_character_count

    @property
    def index_usage_rate(self) -> float:
        if not self.total_alphabet_character_count:
            return 0.0
        return self.index_usage_count / self.total_alphabet_character_count


def evaluate(
    layout: Layout,
    bigrams: Counter[tuple[str, str]],
    unigrams: Counter[str] | None = None,
    weights: ObjectiveWeights = DEFAULT_WEIGHTS,
) -> Evaluation:
    if unigrams is None:
        unigrams = Counter()
        for (first, second), frequency in bigrams.items():
            unigrams[first] += frequency
            unigrams[second] += frequency
    repetitions = repetition_count(layout, bigrams)
    transitions = sum(bigrams.values())
    jumps = row_jump_cost(layout, bigrams)
    characters = sum(unigrams.values())
    pinky = finger_usage(layout, unigrams, "left_pinky")
    index = finger_usage(layout, unigrams, "left_index")
    weighted = (
        weights.repetition * (repetitions / transitions if transitions else 0.0)
        + weights.row_jump * (jumps / transitions if transitions else 0.0)
        + weights.pinky * (pinky / characters if characters else 0.0)
        + weights.index * (index / characters if characters else 0.0)
    )
    return Evaluation(repetitions, transitions, jumps, characters, pinky, index, weighted)


def optimize(
    bigrams: Counter[tuple[str, str]],
    unigrams: Counter[str] | None = None,
    *,
    iterations: int = 10_000,
    seed: int = 0,
    weights: ObjectiveWeights = DEFAULT_WEIGHTS,
) -> Layout:
    if iterations < 0:
        raise ValueError("iterations must be non-negative")
    if unigrams is None:
        unigrams = Counter()
        for (first, second), frequency in bigrams.items():
            unigrams[first] += frequency
            unigrams[second] += frequency
    rng = random.Random(seed)
    current = list("yuiophjklnm")
    current_cost = evaluate(
        Layout.from_letters(current), bigrams, unigrams, weights
    ).weighted_total_cost
    best = current[:]
    best_cost = current_cost
    for iteration in range(iterations):
        first, second = rng.sample(range(len(current)), 2)
        current[first], current[second] = current[second], current[first]
        candidate_cost = evaluate(
            Layout.from_letters(current), bigrams, unigrams, weights
        ).weighted_total_cost
        temperature = max(0.01, 1.0 - iteration / max(1, iterations))
        accept = candidate_cost <= current_cost or rng.random() < math.exp(
            (current_cost - candidate_cost) / temperature
        )
        if accept:
            current_cost = candidate_cost
            if candidate_cost < best_cost:
                best, best_cost = current[:], candidate_cost
        else:
            current[first], current[second] = current[second], current[first]
    return Layout.from_letters(best)
