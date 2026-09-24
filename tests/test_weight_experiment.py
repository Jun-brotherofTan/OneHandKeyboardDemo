import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from corpus import count_bigrams, count_unigrams
from experiment_weights import build_parser, choose_configs, main
from layout import KEYS, conventional_layout
from optimizer import Evaluation, ObjectiveWeights
from weight_experiment import (
    DEFAULT_WEIGHT_CONFIGS,
    ExperimentResult,
    WeightConfig,
    aggregate_results,
    dominates,
    grid_weight_configs,
    layout_signature,
    layout_similarity,
    load_weight_configs,
    mark_pareto_optimal,
    run_experiments,
    write_results_csv,
)


class WeightExperimentTests(unittest.TestCase):
    def test_default_weight_configurations(self):
        self.assertEqual([config.name for config in DEFAULT_WEIGHT_CONFIGS], ["A", "B", "C", "D", "E"])
        self.assertEqual(DEFAULT_WEIGHT_CONFIGS[0].weights, ObjectiveWeights(10, 3, 2, 1))
        self.assertEqual(DEFAULT_WEIGHT_CONFIGS[-1].weights, ObjectiveWeights(15, 5, 4, 1))

    def test_custom_csv_weight_configurations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weights.csv"
            path.write_text(
                "name,repetition,row_jump,pinky,index\nrow_heavy,10,6,2,1\n",
                encoding="utf-8",
            )
            configs = load_weight_configs(path)
        self.assertEqual(configs, [WeightConfig("row_heavy", ObjectiveWeights(10, 6, 2, 1))])

    def test_custom_csv_replaces_defaults_unless_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weights.csv"
            path.write_text("name,repetition,row_jump,pinky,index\ncustom,1,2,3,4\n", encoding="utf-8")
            parser = build_parser()
            args = parser.parse_args(["corpus.txt", "--weights-csv", str(path)])
            self.assertEqual([config.name for config in choose_configs(args)], ["custom"])
            args = parser.parse_args(["corpus.txt", "--weights-csv", str(path), "--use-default-weights"])
            self.assertEqual(len(choose_configs(args)), 6)

    def test_same_seed_reproduces_experiment_result(self):
        bigrams = count_bigrams("the quick brown fox jumps")
        unigrams = count_unigrams("the quick brown fox jumps")
        config = [DEFAULT_WEIGHT_CONFIGS[0]]
        first = run_experiments(bigrams, unigrams, config, [7], iterations=100)
        second = run_experiments(bigrams, unigrams, config, [7], iterations=100)
        self.assertEqual(first[0].layout_signature, second[0].layout_signature)
        self.assertEqual(first[0].evaluation, second[0].evaluation)

    def test_multiple_seed_aggregation_mean_std_and_best_seed(self):
        config = WeightConfig("test", ObjectiveWeights())
        layout = conventional_layout()
        results = [
            ExperimentResult(config, 7, Evaluation(1, 2, 2, 4, 1, 2, 3.0), layout),
            ExperimentResult(config, 11, Evaluation(3, 2, 4, 4, 3, 2, 1.0), layout),
        ]
        summary = aggregate_results(results)[0]
        self.assertEqual(summary["best_seed"], 11)
        self.assertEqual(summary["mean_repetition_rate"], 1.0)
        self.assertAlmostEqual(summary["std_repetition_rate"], 0.5)
        self.assertEqual(summary["mean_weighted_total_cost"], 2.0)
        self.assertEqual(summary["std_weighted_total_cost"], 1.0)
        self.assertEqual(summary["most_common_layout_frequency"], 2)

    def test_layout_signature_and_similarity(self):
        layout = conventional_layout()
        self.assertEqual(layout_signature(layout), layout_signature(layout))
        self.assertEqual(layout_similarity(layout, layout), 1.0)
        other = type(layout).from_letters(tuple("mnlkjihpouy"))
        self.assertLess(layout_similarity(layout, other), 1.0)

    def test_pareto_dominance_and_tradeoff(self):
        config = WeightConfig("test", ObjectiveWeights())
        layout = conventional_layout()
        dominated_config = WeightConfig("dominated", ObjectiveWeights())
        dominator_config = WeightConfig("dominator", ObjectiveWeights())
        tradeoff_config = WeightConfig("tradeoff", ObjectiveWeights())
        dominated = ExperimentResult(dominated_config, 1, Evaluation(2, 1, 1, 1, 2, 1, 1), layout)
        dominator = ExperimentResult(dominator_config, 2, Evaluation(1, 1, 1, 1, 1, 1, 1), layout)
        tradeoff = ExperimentResult(tradeoff_config, 3, Evaluation(1, 1, 1, 1, 3, 1, 1), layout)
        self.assertTrue(dominates(dominator, dominated))
        self.assertFalse(dominates(tradeoff, dominator))
        marked = mark_pareto_optimal([dominated, dominator])
        self.assertFalse(marked[0].pareto_optimal)
        self.assertTrue(marked[1].pareto_optimal)

    def test_results_csv_contains_required_columns(self):
        config = DEFAULT_WEIGHT_CONFIGS[0]
        result = ExperimentResult(config, 7, Evaluation(1, 2, 1, 3, 1, 1, 2.0), conventional_layout())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            write_results_csv(path, [result])
            with path.open(encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
        self.assertIn("layout_signature", row)
        self.assertIn("weighted_total_cost", row)
        self.assertIn("pareto_optimal", row)

    def test_grid_count_and_large_run_warning(self):
        self.assertEqual(len(grid_weight_configs([1, 2], [3, 4], [5], [6, 7, 8])), 12)
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "corpus.txt"
            corpus.write_text("hello world", encoding="utf-8")
            output = io.StringIO()
            argv = [
                "experiment_weights.py", str(corpus), "--grid",
                "--repetition-values", *[str(value) for value in range(101)],
                "--row-values", "1", "--pinky-values", "1", "--index-values", "1",
                "--iterations", "0", "--output-dir", directory,
            ]
            with patch("sys.argv", argv), redirect_stdout(output):
                main()
        self.assertIn("WARNING: more than 100 optimization runs", output.getvalue())

    def test_precomputed_statistics_are_reused_and_normal_layer_stays_fixed(self):
        bigrams = count_bigrams("hello world")
        unigrams = count_unigrams("hello world")
        with patch("weight_experiment.optimize", wraps=__import__("optimizer").optimize) as mocked:
            results = run_experiments(
                bigrams, unigrams, [DEFAULT_WEIGHT_CONFIGS[0]], [1, 2], iterations=0
            )
        self.assertEqual(mocked.call_count, 2)
        for call in mocked.call_args_list:
            self.assertIs(call.args[0], bigrams)
            self.assertIs(call.args[1], unigrams)
        self.assertTrue(all(tuple(key.normal for key in KEYS) == tuple("qwertasdfgzxcvb") for _ in results))


if __name__ == "__main__":
    unittest.main()
