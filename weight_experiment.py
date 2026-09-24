"""Reusable weight-sensitivity experiment helpers for mirror layouts."""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable, Sequence

from layout import Layout, conventional_layout
from optimizer import Evaluation, ObjectiveWeights, evaluate, optimize


METRIC_NAMES = (
    "repetition_rate",
    "average_row_distance",
    "pinky_usage_rate",
    "index_usage_rate",
)


@dataclass(frozen=True)
class WeightConfig:
    name: str
    weights: ObjectiveWeights


DEFAULT_WEIGHT_CONFIGS = (
    WeightConfig("A", ObjectiveWeights(10, 3, 2, 1)),
    WeightConfig("B", ObjectiveWeights(10, 5, 3, 1)),
    WeightConfig("C", ObjectiveWeights(15, 3, 3, 1)),
    WeightConfig("D", ObjectiveWeights(10, 3, 4, 1)),
    WeightConfig("E", ObjectiveWeights(15, 5, 4, 1)),
)


@dataclass(frozen=True)
class ExperimentResult:
    config: WeightConfig
    seed: int
    evaluation: Evaluation
    layout: Layout
    pareto_optimal: bool = False

    @property
    def layout_signature(self) -> str:
        return layout_signature(self.layout)

    def as_row(self) -> dict[str, str | int | float | bool]:
        weights = self.config.weights
        result = self.evaluation
        return {
            "config_name": self.config.name,
            "seed": self.seed,
            "weight_repetition": weights.repetition,
            "weight_row_jump": weights.row_jump,
            "weight_pinky": weights.pinky,
            "weight_index": weights.index,
            "repetition_count": result.repetition_count,
            "repetition_rate": result.repetition_rate,
            "row_jump_cost": result.row_jump_cost,
            "average_row_distance": result.average_row_distance,
            "pinky_usage_count": result.pinky_usage_count,
            "pinky_usage_rate": result.pinky_usage_rate,
            "index_usage_count": result.index_usage_count,
            "index_usage_rate": result.index_usage_rate,
            "weighted_total_cost": result.weighted_total_cost,
            "layout_signature": self.layout_signature,
            "pareto_optimal": self.pareto_optimal,
        }


def load_weight_configs(path: str | Path) -> list[WeightConfig]:
    """Load named weight rows with the required CSV header."""
    configs = []
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"name", "repetition", "row_jump", "pinky", "index"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("weights CSV must contain name,repetition,row_jump,pinky,index")
        for row in reader:
            configs.append(
                WeightConfig(
                    row["name"].strip(),
                    ObjectiveWeights(
                        float(row["repetition"]),
                        float(row["row_jump"]),
                        float(row["pinky"]),
                        float(row["index"]),
                    ),
                )
            )
    if not configs:
        raise ValueError("weights CSV contains no configurations")
    return configs


def grid_weight_configs(
    repetition_values: Sequence[float],
    row_values: Sequence[float],
    pinky_values: Sequence[float],
    index_values: Sequence[float],
) -> list[WeightConfig]:
    configs = []
    for repetition in repetition_values:
        for row_jump in row_values:
            for pinky in pinky_values:
                for index in index_values:
                    name = f"grid_{repetition:g}_{row_jump:g}_{pinky:g}_{index:g}"
                    configs.append(
                        WeightConfig(name, ObjectiveWeights(repetition, row_jump, pinky, index))
                    )
    return configs


def layout_signature(layout: Layout) -> str:
    """Return a deterministic signature for the 11 optimized positions."""
    return "".join(mirror for _, mirror in layout.as_rows() if mirror.isalpha())


def layout_similarity(first: Layout | str, second: Layout | str) -> float:
    first_signature = first if isinstance(first, str) else layout_signature(first)
    second_signature = second if isinstance(second, str) else layout_signature(second)
    if len(first_signature) != len(second_signature):
        raise ValueError("layout signatures must have equal length")
    return (
        sum(left == right for left, right in zip(first_signature, second_signature))
        / len(first_signature)
        if first_signature
        else 1.0
    )


def run_experiments(
    bigrams,
    unigrams,
    configs: Sequence[WeightConfig],
    seeds: Sequence[int],
    *,
    iterations: int = 10_000,
) -> list[ExperimentResult]:
    """Run the existing optimizer for every config/seed pair."""
    results = []
    for config in configs:
        for seed in seeds:
            layout = optimize(
                bigrams,
                unigrams,
                iterations=iterations,
                seed=seed,
                weights=config.weights,
            )
            results.append(
                ExperimentResult(config, seed, evaluate(layout, bigrams, unigrams, config.weights), layout)
            )
    return mark_pareto_optimal(results)


def dominates(first: ExperimentResult, second: ExperimentResult) -> bool:
    first_values = tuple(getattr(first.evaluation, name) for name in METRIC_NAMES)
    second_values = tuple(getattr(second.evaluation, name) for name in METRIC_NAMES)
    return all(left <= right for left, right in zip(first_values, second_values)) and any(
        left < right for left, right in zip(first_values, second_values)
    )


def mark_pareto_optimal(results: Sequence[ExperimentResult]) -> list[ExperimentResult]:
    representatives = representative_results(results)
    representative_values = tuple(representatives.values())
    pareto_names = {
        result.config.name
        for result in representative_values
        if not any(dominates(other, result) for other in representative_values if other is not result)
    }
    return [
        replace(result, pareto_optimal=result.config.name in pareto_names)
        for result in results
    ]


def representative_results(results: Sequence[ExperimentResult]) -> dict[str, ExperimentResult]:
    representatives = {}
    for result in results:
        current = representatives.get(result.config.name)
        if current is None or (result.evaluation.weighted_total_cost, result.seed) < (
            current.evaluation.weighted_total_cost,
            current.seed,
        ):
            representatives[result.config.name] = result
    return representatives


def aggregate_results(results: Sequence[ExperimentResult]) -> list[dict[str, str | int | float | bool]]:
    rows = []
    for config_name, group in _group_results(results).items():
        config = group[0].config
        best = min(group, key=lambda result: (result.evaluation.weighted_total_cost, result.seed))
        signatures = Counter(result.layout_signature for result in group)
        most_common_layout, frequency = signatures.most_common(1)[0]
        row: dict[str, str | int | float | bool] = {
            "config_name": config_name,
            "weight_repetition": config.weights.repetition,
            "weight_row_jump": config.weights.row_jump,
            "weight_pinky": config.weights.pinky,
            "weight_index": config.weights.index,
            "best_weighted_total_cost": best.evaluation.weighted_total_cost,
            "best_seed": best.seed,
            "most_common_layout": most_common_layout,
            "most_common_layout_frequency": frequency,
            "pareto_optimal": any(result.pareto_optimal for result in group),
        }
        for metric in METRIC_NAMES:
            values = [getattr(result.evaluation, metric) for result in group]
            row[f"mean_{metric}"] = mean(values)
            row[f"std_{metric}"] = pstdev(values) if len(values) > 1 else 0.0
        weighted_values = [result.evaluation.weighted_total_cost for result in group]
        row["mean_weighted_total_cost"] = mean(weighted_values)
        row["std_weighted_total_cost"] = pstdev(weighted_values) if len(weighted_values) > 1 else 0.0
        rows.append(row)
    return rows


def _group_results(results: Iterable[ExperimentResult]) -> dict[str, list[ExperimentResult]]:
    groups: dict[str, list[ExperimentResult]] = {}
    for result in results:
        groups.setdefault(result.config.name, []).append(result)
    return groups


def balanced_recommendation(results: Sequence[ExperimentResult]) -> ExperimentResult | None:
    representatives = list(representative_results(results).values())
    pareto = [result for result in representatives if result.pareto_optimal]
    if not pareto:
        return None
    values = {metric: [getattr(result.evaluation, metric) for result in pareto] for metric in METRIC_NAMES}
    minima = {metric: min(items) for metric, items in values.items()}
    maxima = {metric: max(items) for metric, items in values.items()}

    def distance(result: ExperimentResult) -> float:
        return math.sqrt(
            sum(
                (
                    (getattr(result.evaluation, metric) - minima[metric])
                    / (maxima[metric] - minima[metric])
                    if maxima[metric] != minima[metric]
                    else 0.0
                )
                ** 2
                for metric in METRIC_NAMES
            )
        )

    return min(pareto, key=lambda result: (distance(result), result.config.name, result.seed))


def best_recommendations(results: Sequence[ExperimentResult]) -> dict[str, ExperimentResult | None]:
    if not results:
        return {"weighted_total_cost": None, "repetition_rate": None, "balanced_pareto": None}
    return {
        "weighted_total_cost": min(results, key=lambda result: (result.evaluation.weighted_total_cost, result.seed)),
        "repetition_rate": min(results, key=lambda result: (result.evaluation.repetition_rate, result.seed)),
        "balanced_pareto": balanced_recommendation(results),
    }


RESULT_FIELDS = tuple(ExperimentResult(
    DEFAULT_WEIGHT_CONFIGS[0], 0, Evaluation(0, 0, 0, 0, 0, 0, 0.0), conventional_layout()
).as_row().keys())
SUMMARY_FIELDS = (
    "config_name", "weight_repetition", "weight_row_jump", "weight_pinky", "weight_index",
    "mean_repetition_rate", "std_repetition_rate", "mean_average_row_distance", "std_average_row_distance",
    "mean_pinky_usage_rate", "std_pinky_usage_rate", "mean_index_usage_rate", "std_index_usage_rate",
    "mean_weighted_total_cost", "std_weighted_total_cost", "best_weighted_total_cost", "best_seed",
    "most_common_layout", "most_common_layout_frequency", "pareto_optimal",
)


def write_results_csv(path: str | Path, results: Sequence[ExperimentResult]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(result.as_row() for result in results)


def write_summary_csv(path: str | Path, results: Sequence[ExperimentResult]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(aggregate_results(results))


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def write_layout_mapping(path: str | Path, layout: Layout) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("physical_key", "row", "column", "finger", "normal_character", "mirror_character"))
        for key, mirror in layout.as_rows():
            writer.writerow((key.physical_key, key.row, key.column, key.finger, key.normal, mirror))
