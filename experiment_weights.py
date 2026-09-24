"""Run a reproducible weight-sensitivity experiment for mirror layouts."""

from __future__ import annotations

import argparse
from pathlib import Path

from corpus import count_bigrams, count_unigrams, read_corpus
from layout import conventional_layout
from optimizer import evaluate
from weight_experiment import (
    DEFAULT_WEIGHT_CONFIGS,
    WeightConfig,
    aggregate_results,
    best_recommendations,
    grid_weight_configs,
    layout_similarity,
    load_weight_configs,
    representative_results,
    run_experiments,
    safe_filename,
    write_layout_mapping,
    write_results_csv,
    write_summary_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--weights-csv", type=Path)
    parser.add_argument(
        "--use-default-weights",
        action="store_true",
        help="include defaults in addition to --weights-csv",
    )
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--repetition-values", type=float, nargs="+")
    parser.add_argument("--row-values", type=float, nargs="+")
    parser.add_argument("--pinky-values", type=float, nargs="+")
    parser.add_argument("--index-values", type=float, nargs="+")
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    return parser


def choose_configs(args: argparse.Namespace) -> list[WeightConfig]:
    configs: list[WeightConfig] = []
    if args.grid:
        value_sets = (
            args.repetition_values,
            args.row_values,
            args.pinky_values,
            args.index_values,
        )
        if any(values is None for values in value_sets):
            raise ValueError("--grid requires all four *-values options")
        if args.use_default_weights:
            configs.extend(DEFAULT_WEIGHT_CONFIGS)
        configs.extend(grid_weight_configs(*value_sets))
    elif args.use_default_weights or args.weights_csv is None:
        configs.extend(DEFAULT_WEIGHT_CONFIGS)
    if args.weights_csv is not None:
        configs.extend(load_weight_configs(args.weights_csv))
    if not configs:
        raise ValueError("no weight configurations selected")
    names = [config.name for config in configs]
    if len(names) != len(set(names)):
        raise ValueError("weight configuration names must be unique")
    return configs


def choose_seeds(args: argparse.Namespace) -> list[int]:
    if args.seed is not None and args.seeds is not None:
        raise ValueError("use either --seed or --seeds, not both")
    if args.seeds is not None:
        return args.seeds
    return [args.seed if args.seed is not None else 0]


def _improvement(baseline: float, optimized: float) -> float:
    return (baseline - optimized) / baseline if baseline else 0.0


def print_comparison(results, bigrams, unigrams) -> None:
    representatives = representative_results(results)
    print("COMPARISON BY WEIGHT SET")
    print("Name\tRepW\tRowW\tPinkyW\tIndexW\tRep%\tRowDist\tPinky%\tIndex%\tTotal")
    for name, result in representatives.items():
        weights = result.config.weights
        metric = result.evaluation
        print(
            f"{name}\t{weights.repetition:g}\t{weights.row_jump:g}\t{weights.pinky:g}\t"
            f"{weights.index:g}\t{metric.repetition_rate:.2%}\t{metric.average_row_distance:.3f}\t"
            f"{metric.pinky_usage_rate:.2%}\t{metric.index_usage_rate:.2%}\t"
            f"{metric.weighted_total_cost:.4f}"
        )
    print("\nMULTI-SEED MEAN +/- STD")
    print("Name\tRep\tRowDist\tPinky\tIndex\tTotal\tBest\tBestSeed\tSameLayout")
    for row in aggregate_results(results):
        print(
            f"{row['config_name']}\t"
            f"{row['mean_repetition_rate']:.2%} +/- {row['std_repetition_rate']:.2%}\t"
            f"{row['mean_average_row_distance']:.3f} +/- {row['std_average_row_distance']:.3f}\t"
            f"{row['mean_pinky_usage_rate']:.2%} +/- {row['std_pinky_usage_rate']:.2%}\t"
            f"{row['mean_index_usage_rate']:.2%} +/- {row['std_index_usage_rate']:.2%}\t"
            f"{row['mean_weighted_total_cost']:.4f} +/- {row['std_weighted_total_cost']:.4f}\t"
            f"{row['best_weighted_total_cost']:.4f}\t{row['best_seed']}\t"
            f"{row['most_common_layout_frequency']}"
        )
    print("\nPARETO-OPTIMAL CONFIGURATIONS")
    pareto_names = [name for name, result in representatives.items() if result.pareto_optimal]
    print("\n".join(pareto_names) if pareto_names else "none")

    conventional = conventional_layout()
    baseline_config = next(
        (result.config for result in representatives.values()
         if result.config.weights == DEFAULT_WEIGHT_CONFIGS[0].weights),
        None,
    )
    print("\nBASELINE COMPARISON")
    for name, result in representatives.items():
        baseline = evaluate(conventional, bigrams, unigrams, result.config.weights)
        metric = result.evaluation
        print(f"{name}:")
        print(f"  repetition improvement: {_improvement(baseline.repetition_rate, metric.repetition_rate):.2%}")
        print(f"  row jump improvement: {_improvement(baseline.average_row_distance, metric.average_row_distance):.2%}")
        print(f"  pinky improvement: {_improvement(baseline.pinky_usage_rate, metric.pinky_usage_rate):.2%}")
        print(f"  index improvement: {_improvement(baseline.index_usage_rate, metric.index_usage_rate):.2%}")

    if baseline_config is not None:
        baseline_layout = representatives[baseline_config.name].layout
        print("\nLAYOUT SIMILARITY TO BASELINE WEIGHTS")
        for name, result in representatives.items():
            print(f"{name}: {layout_similarity(baseline_layout, result.layout):.2%}")

    print("\nOPTIMIZED LAYOUTS")
    for name, result in representatives.items():
        print(f"\nWEIGHT SET: {name}")
        print("\n".join(result.layout.mirror_display_rows()))
        print("physical_key -> mirror_character")
        print("\n".join(f"{key.physical_key} -> {mirror}" for key, mirror in result.layout.as_rows()))


def print_recommendations(results) -> None:
    recommendations = best_recommendations(results)
    print("\nRECOMMENDATIONS")
    for label, result in recommendations.items():
        if result is None:
            print(f"{label}: unavailable")
        else:
            print(f"{label}: {result.config.name} (seed {result.seed})")
    print("balanced_pareto is a heuristic based on min-max normalized raw metrics.")


def main() -> None:
    args = build_parser().parse_args()
    configs = choose_configs(args)
    seeds = choose_seeds(args)
    run_count = len(configs) * len(seeds)
    print(f"number of configurations: {len(configs)}")
    print(f"number of seeds: {len(seeds)}")
    print(f"total optimization runs: {run_count}")
    if run_count > 100:
        print("WARNING: more than 100 optimization runs may be computationally expensive.")

    text = read_corpus(args.corpus)
    bigrams = count_bigrams(text)
    unigrams = count_unigrams(text)
    results = run_experiments(bigrams, unigrams, configs, seeds, iterations=args.iterations)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_results_csv(args.output_dir / "weight_experiment_results.csv", results)
    write_summary_csv(args.output_dir / "weight_experiment_summary.csv", results)
    for result in representative_results(results).values():
        write_layout_mapping(
            args.output_dir / f"layout_{safe_filename(result.config.name)}.csv",
            result.layout,
        )
    print_comparison(results, bigrams, unigrams)
    print_recommendations(results)
    print(f"\nWrote results to {args.output_dir.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(f"error: {error}") from error
