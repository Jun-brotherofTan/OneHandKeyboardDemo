"""Command-line entry point for corpus shortcut analysis."""

import argparse

from corpus_analyzer import analyze_text, format_table, read_corpus, write_csv
from shortcut_optimizer import format_optimization, optimize_shortcuts, write_selected_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="a .txt file or a directory containing .txt files")
    parser.add_argument("--csv", required=True, help="output CSV path")
    parser.add_argument("--min-frequency", type=int, default=2)
    parser.add_argument("--min-length", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=10)
    parser.add_argument("--shortcut-cost", type=int, default=2)
    parser.add_argument("--top", type=int, default=100, help="number of results per table")
    parser.add_argument("--num-shortcuts", type=int, default=20)
    parser.add_argument(
        "--selected-csv", default="selected_shortcuts.csv", help="CSV path for selected shortcuts"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    text = read_corpus(args.input)
    substring_candidates, word_candidates = analyze_text(
        text,
        minimum_frequency=args.min_frequency,
        minimum_length=args.min_length,
        maximum_length=args.max_length,
        shortcut_cost=args.shortcut_cost,
        top_n=args.top,
    )
    print(format_table("SUBSTRING CANDIDATES", substring_candidates))
    print()
    print(format_table("WORD CANDIDATES", word_candidates))
    write_csv(args.csv, substring_candidates, word_candidates)
    result = optimize_shortcuts(
        text,
        [*substring_candidates, *word_candidates],
        num_shortcuts=args.num_shortcuts,
        shortcut_cost=args.shortcut_cost,
    )
    print()
    print(format_optimization(result))
    write_selected_csv(args.selected_csv, result)


if __name__ == "__main__":
    main()