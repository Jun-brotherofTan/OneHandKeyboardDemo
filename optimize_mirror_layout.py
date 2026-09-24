"""CLI for optimizing a one-handed mirrored alphabet layer."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from corpus import count_bigrams, count_unigrams, read_corpus
from layout import ROWS, conventional_layout
from optimizer import ObjectiveWeights, evaluate, optimize


def _print_layer(title: str, rows: tuple[str, ...]) -> None:
    print(title)
    print("\n".join(rows))
    print()


def _print_evaluation(title: str, result) -> None:
    print(title)
    print("Same-finger or same-column repetition:")
    print(f"  count: {result.repetition_count}")
    print(f"  rate: {result.repetition_rate:.2%}")
    print("Row jump:")
    print(f"  total cost: {result.row_jump_cost}")
    print(f"  average distance: {result.average_row_distance:.2f}")
    print("Pinky usage:")
    print(f"  count: {result.pinky_usage_count}")
    print(f"  rate: {result.pinky_usage_rate:.2%}")
    print("Index usage:")
    print(f"  count: {result.index_usage_count}")
    print(f"  rate: {result.index_usage_rate:.2%}")
    print(f"Weighted total cost: {result.weighted_total_cost:.4f}\n")


def _print_improvement(conventional_result, optimized_result) -> None:
    def reduction(before: float, after: float) -> float:
        return (before - after) / before if before else 0.0

    print("IMPROVEMENT")
    print(f"repetition reduction: {reduction(conventional_result.repetition_count, optimized_result.repetition_count):.2%}")
    print(f"row-jump reduction: {reduction(conventional_result.row_jump_cost, optimized_result.row_jump_cost):.2%}")
    print(f"pinky usage reduction: {reduction(conventional_result.pinky_usage_count, optimized_result.pinky_usage_count):.2%}")
    print(f"index usage reduction: {reduction(conventional_result.index_usage_count, optimized_result.index_usage_count):.2%}")
    print(f"total ergonomic cost reduction: {reduction(conventional_result.weighted_total_cost, optimized_result.weighted_total_cost):.2%}\n")


def _write_csv(path: Path, conventional_layout, optimized_layout, conventional_result, optimized_result) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("physical_key", "row", "column", "finger", "normal_character", "mirror_character"))
        for key, mirror in optimized_layout.as_rows():
            writer.writerow((key.normal, key.row, key.column, key.finger, key.normal, mirror))
    summary_path = path.with_name(f"{path.stem}.summary.csv")
    with summary_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow((
            "layout_type", "repetition_count", "repetition_rate", "row_jump_cost",
            "average_row_distance", "pinky_usage_count", "pinky_usage_rate",
            "index_usage_count", "index_usage_rate", "weighted_total_cost",
            "same_finger_count", "same_finger_rate",
        ))
        for name, result in (("conventional", conventional_result), ("optimized", optimized_result)):
            writer.writerow((
                name, result.repetition_count, f"{result.repetition_rate:.8f}",
                result.row_jump_cost, f"{result.average_row_distance:.8f}",
                result.pinky_usage_count, f"{result.pinky_usage_rate:.8f}",
                result.index_usage_count, f"{result.index_usage_rate:.8f}",
                f"{result.weighted_total_cost:.8f}", result.same_finger_count,
                f"{result.same_finger_rate:.8f}",
            ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--weight-repetition", type=float, default=10.0)
    parser.add_argument("--weight-row-jump", type=float, default=3.0)
    parser.add_argument("--weight-pinky", type=float, default=2.0)
    parser.add_argument("--weight-index", type=float, default=1.0)
    parser.add_argument(
        "--weight-same-finger", type=float, dest="weight_repetition", default=argparse.SUPPRESS
    )
    args = parser.parse_args()

    text = read_corpus(args.corpus)
    bigrams = count_bigrams(text)
    unigrams = count_unigrams(text)
    weights = ObjectiveWeights(
        repetition=args.weight_repetition,
        row_jump=args.weight_row_jump,
        pinky=args.weight_pinky,
        index=args.weight_index,
    )
    conventional = conventional_layout()
    optimized = optimize(
        bigrams, unigrams, iterations=args.iterations, seed=args.seed, weights=weights
    )
    conventional_result = evaluate(conventional, bigrams, unigrams, weights)
    optimized_result = evaluate(optimized, bigrams, unigrams, weights)
    _print_layer("FIXED NORMAL LAYER", tuple(" ".join(row) for row in ROWS))
    _print_layer("CONVENTIONAL MIRROR LAYER", ("Y U I O P", "H J K L ;", "N M , . /"))
    _print_evaluation("CONVENTIONAL MIRROR", conventional_result)
    _print_layer("OPTIMIZED MIRROR LAYER", optimized.mirror_display_rows())
    _print_evaluation("OPTIMIZED MIRROR", optimized_result)
    _print_improvement(conventional_result, optimized_result)
    print("MACHINE-READABLE MAPPING")
    for key, mirror in optimized.as_rows():
        print(f"{key.normal} -> {mirror}")
    if args.output_csv:
        _write_csv(
            args.output_csv,
            conventional,
            optimized,
            conventional_result,
            optimized_result,
        )
        print(f"\nWrote {args.output_csv} and {args.output_csv.with_name(args.output_csv.stem + '.summary.csv')}")


if __name__ == "__main__":
    main()
