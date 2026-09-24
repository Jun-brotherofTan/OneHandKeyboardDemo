import tempfile
import unittest
from collections import Counter
from pathlib import Path

import csv

from corpus import count_bigrams, count_unigrams, read_corpus
from layout import KEYS, NORMAL_TO_FINGER, conventional_layout
from optimize_mirror_layout import _write_csv
from optimizer import ObjectiveWeights, evaluate, optimize, repetition_count


class MirrorLayoutTests(unittest.TestCase):
    def test_finger_assignments(self):
        self.assertEqual(NORMAL_TO_FINGER["q"], "left_pinky")
        self.assertEqual(NORMAL_TO_FINGER["e"], "left_middle")
        self.assertEqual(NORMAL_TO_FINGER["t"], "left_index")

    def test_bigrams_filter_and_normalize(self):
        self.assertEqual(count_bigrams("A!b C"), Counter({("a", "b"): 1, ("b", "c"): 1}))

    def test_same_finger_detection(self):
        result = evaluate(conventional_layout(), Counter({("q", "a"): 2, ("q", "w"): 3}))
        self.assertEqual(result.same_finger_count, 2)

    def test_repetition_uses_same_finger_or_same_column_once(self):
        layout = conventional_layout()
        result = evaluate(
            layout,
            Counter({("r", "t"): 1, ("q", "a"): 1, ("q", "w"): 1, ("e", "c"): 1}),
            Counter("r t q a q w e c".replace(" ", "")),
        )
        self.assertEqual(result.repetition_count, 3)
        self.assertEqual(repetition_count(layout, Counter({("q", "a"): 5})), 5)

    def test_custom_same_column_without_same_finger_counts(self):
        class CustomLayout:
            def finger_for(self, letter):
                return {"a": "left_pinky", "b": "left_ring"}[letter]

            def column_for(self, letter):
                return 0

        self.assertEqual(repetition_count(CustomLayout(), Counter({("a", "b"): 4})), 4)

    def test_row_distance_uses_zero_one_and_two(self):
        result = evaluate(
            conventional_layout(),
            Counter({("q", "w"): 1, ("q", "a"): 1, ("q", "z"): 1}),
            Counter("qwaqz"),
        )
        self.assertEqual(result.row_jump_cost, 3)
        self.assertEqual(result.average_row_distance, 1.0)

    def test_pinky_and_index_usage_rates(self):
        pinky = evaluate(conventional_layout(), Counter(), count_unigrams("qaz"))
        index = evaluate(conventional_layout(), Counter(), count_unigrams("rftgbv"))
        self.assertEqual(pinky.pinky_usage_rate, 1.0)
        self.assertEqual(index.index_usage_rate, 1.0)

    def test_weighted_cost_is_sum_of_normalized_components(self):
        weights = ObjectiveWeights(4.0, 3.0, 2.0, 1.0)
        result = evaluate(
            conventional_layout(),
            count_bigrams("qazrt"),
            count_unigrams("qazrt"),
            weights,
        )
        expected = (
            weights.repetition * result.repetition_rate
            + weights.row_jump * result.average_row_distance
            + weights.pinky * result.pinky_usage_rate
            + weights.index * result.index_usage_rate
        )
        self.assertAlmostEqual(result.weighted_total_cost, expected)

    def test_changing_weights_changes_total_predictably(self):
        bigrams = Counter({("q", "a"): 2})
        unigrams = Counter("qa")
        base = evaluate(conventional_layout(), bigrams, unigrams, ObjectiveWeights())
        changed = evaluate(
            conventional_layout(), bigrams, unigrams,
            ObjectiveWeights(repetition=20.0, row_jump=3.0, pinky=2.0, index=1.0),
        )
        self.assertAlmostEqual(changed.weighted_total_cost - base.weighted_total_cost, 10.0)

    def test_layout_is_a_valid_permutation(self):
        layout = conventional_layout()
        self.assertEqual(len(layout.mirror_by_physical), 15)
        self.assertEqual(
            {value for value in layout.mirror_by_physical.values() if value.isalpha()},
            set("hijklmnopuy"),
        )

    def test_optimizer_keeps_normal_layer(self):
        layout = optimize(count_bigrams("the quick brown fox"), iterations=100, seed=4)
        self.assertEqual(tuple(key.normal for key in KEYS), tuple("qwertasdfgzxcvb"))
        self.assertEqual(layout.finger_for("q"), "left_pinky")

    def test_mirror_mapping_changes_metrics_but_normal_layer_does_not(self):
        conventional = conventional_layout()
        swapped = type(conventional).from_letters(tuple("uiyophjklnm"))
        bigrams = Counter({("y", "q"): 3})
        self.assertNotEqual(
            evaluate(conventional, bigrams, count_unigrams("yq")).weighted_total_cost,
            evaluate(swapped, bigrams, count_unigrams("yq")).weighted_total_cost,
        )
        self.assertEqual(tuple(key.normal for key in KEYS), tuple("qwertasdfgzxcvb"))

    def test_conventional_baseline_is_reproducible(self):
        bigrams = count_bigrams("the quick brown fox")
        self.assertEqual(evaluate(conventional_layout(), bigrams), evaluate(conventional_layout(), bigrams))

    def test_same_seed_reproduces_optimization(self):
        bigrams = count_bigrams("the quick brown fox jumps over the lazy dog")
        first = optimize(bigrams, iterations=200, seed=12)
        second = optimize(bigrams, iterations=200, seed=12)
        self.assertEqual(first.mirror_by_physical, second.mirror_by_physical)

    def test_synthetic_corpus_improves_obvious_pair(self):
        bigrams = Counter({("q", "h"): 100, ("q", "u"): 1})
        baseline = evaluate(conventional_layout(), bigrams)
        result = evaluate(optimize(bigrams, iterations=500, seed=2), bigrams)
        self.assertLess(result.same_finger_count, baseline.same_finger_count)

    def test_recursive_corpus_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            (root / "nested" / "part.txt").write_text("hello", encoding="utf-8")
            self.assertEqual(read_corpus(root), "hello")

    def test_summary_csv_contains_all_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "layout.csv"
            layout = conventional_layout()
            result = evaluate(layout, count_bigrams("qwerty"), count_unigrams("qwerty"))
            _write_csv(output, layout, layout, result, result)
            with output.with_name("layout.summary.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            required = {
                "repetition_count", "repetition_rate", "row_jump_cost", "average_row_distance",
                "pinky_usage_count", "pinky_usage_rate", "index_usage_count", "index_usage_rate",
                "weighted_total_cost", "same_finger_count", "same_finger_rate",
            }
            self.assertTrue(required.issubset(rows[0]))
            self.assertEqual({row["layout_type"] for row in rows}, {"conventional", "optimized"})


if __name__ == "__main__":
    unittest.main()
